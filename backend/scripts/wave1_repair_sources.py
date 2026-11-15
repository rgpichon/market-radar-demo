#!/usr/bin/env python3
"""
Wave-1 Mass Repair Runner

Automated loop to convert failing/partial sources into working sources.

Usage:
    python wave1_repair_sources.py --dry-run --max-sources 10
    python wave1_repair_sources.py --repair --dry-run --max-sources 10
    python wave1_repair_sources.py --repair --apply --max-sources 10
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone
from collections import Counter

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.source_ops import (
    test_source_and_return_metrics,
    autoparser_generation,
    detail_enrichment_validator,
    apply_patch_to_source,
    meets_working_threshold
)
from utils.host_budget import get_budget, reset_budget, HostBudgetExceeded


def load_sources(sources_file: Path) -> List[Dict]:
    """Load sources from JSON file."""
    if not sources_file.exists():
        return []
    with open(sources_file, 'r') as f:
        return json.load(f)


def select_cohort(
    sources: List[Dict],
    only_status: str = 'failed,partial',
    only_adapter: str = 'html_list',
    max_sources: int = 15,
    max_unique_hosts: Optional[int] = None,
    host_budget=None
) -> List[Dict]:
    """
    Select sources to repair based on filters.
    
    Diversifies by host to avoid hitting the same host repeatedly.
    Skips hosts in persistent cooldown.
    """
    import random
    from urllib.parse import urlparse
    
    cohort = []
    statuses = [s.strip() for s in only_status.split(',')]
    
    # Filter sources
    for source in sources:
        # Filter by adapter
        if only_adapter and source.get('adapter_type') != only_adapter:
            continue
        
        # Filter by status (heuristic: check active flag and failure_class)
        active = source.get('active', 1) == 1
        failure_class = source.get('failure_class')
        
        # Determine source status
        source_status = 'active' if active else 'inactive'
        if failure_class:
            if failure_class in ['no_events', 'selector_drift_suspected', 'blocked_hard', 'gated_login']:
                source_status = 'failed'
            elif failure_class in ['partial_needs_detail', 'low_date_coverage']:
                source_status = 'partial'
        elif not active:
            # Inactive sources without failure_class are likely failed
            source_status = 'failed'
        
        # Check status match
        status_match = False
        if 'all' in statuses:
            status_match = True
        elif source_status in statuses:
            status_match = True
        elif 'partial' in statuses and active and not failure_class:
            # Include active sources that might need repair (we'll test them)
            status_match = True
        
        if not status_match:
            continue
        
        # Check if host is in persistent cooldown
        url = source.get('url', '')
        if url and host_budget:
            if host_budget.is_host_in_cooldown(url):
                continue  # Skip hosts in cooldown
        
        cohort.append(source)
    
    # Shuffle to diversify by host
    random.shuffle(cohort)
    
    # Limit by unique hosts if specified
    if max_unique_hosts:
        seen_hosts = set()
        diversified = []
        for source in cohort:
            url = source.get('url', '')
            if url:
                host = urlparse(url).netloc
                if host not in seen_hosts:
                    seen_hosts.add(host)
                    diversified.append(source)
                elif len(seen_hosts) < max_unique_hosts:
                    # Still add if we haven't hit the limit
                    diversified.append(source)
            else:
                diversified.append(source)
            
            if len(seen_hosts) >= max_unique_hosts and len(diversified) >= max_sources:
                break
        
        cohort = diversified
    
    return cohort[:max_sources]


def choose_repair_plan(
    source: Dict,
    baseline_metrics: Dict
) -> Dict:
    """
    Choose repair plan deterministically.
    
    Returns:
        {
            'plan': str,  # 'autoparser', 'detail_enrichment', 'ics_harvest', 'deferred'
            'reason': str
        }
    """
    kept_count = baseline_metrics.get('kept_count', 0)
    dated_ratio = baseline_metrics.get('dated_ratio', 0.0)
    error_class = baseline_metrics.get('error_class')
    
    # Hard block / login
    if error_class in ['blocked_hard', 'gated_login']:
        return {
            'plan': 'deferred',
            'reason': f'Hard block detected: {error_class}'
        }
    
    # No events or empty extraction
    if kept_count == 0:
        return {
            'plan': 'autoparser',
            'reason': 'kept_count=0, need to regenerate selectors'
        }
    
    # Low dated_ratio
    if dated_ratio < 0.5:
        # Check if ICS links might be available
        detail_fetch = source.get('detail_fetch', {})
        if detail_fetch.get('enabled'):
            # Already has detail_fetch, might need ICS harvesting
            return {
                'plan': 'ics_harvest',
                'reason': f'dated_ratio={dated_ratio:.1%} low, try ICS harvesting'
            }
        else:
            return {
                'plan': 'detail_enrichment',
                'reason': f'dated_ratio={dated_ratio:.1%} low, enable detail enrichment'
            }
    
    # Already working
    return {
        'plan': 'none',
        'reason': 'Source already meets thresholds'
    }


def main():
    parser = argparse.ArgumentParser(description='Wave-1 Mass Repair Runner')
    parser.add_argument('--sources', type=str, default='backend/sources.json',
                       help='Path to sources.json (default: backend/sources.json)')
    parser.add_argument('--only-status', type=str, default='failed,partial',
                       help='Filter by status: failed,partial,inactive,all (default: failed,partial)')
    parser.add_argument('--only-adapter', type=str, default='html_list',
                       help='Filter by adapter type (default: html_list)')
    parser.add_argument('--max-sources', type=int, default=15,
                       help='Maximum sources to process (default: 15)')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Dry-run mode (default: ON, no writes)')
    parser.add_argument('--apply', action='store_true',
                       help='Apply patches to sources.json')
    parser.add_argument('--repair', action='store_true',
                       help='Run repair actions (network requests)')
    parser.add_argument('--use-cache-only', action='store_true',
                       help='Use cache only, no new network requests')
    parser.add_argument('--sampling-mode', type=str, default='adaptive',
                       choices=['stratified', 'date_hint_priority', 'top_n', 'adaptive'],
                       help='Sampling mode for detail enrichment (default: adaptive)')
    parser.add_argument('--per-host-max', type=int, default=20,
                       help='Max requests per host per run (default: 20)')
    parser.add_argument('--per-host-delay', type=float, default=1.0,
                       help='Min delay between requests to same host in seconds (default: 1.0)')
    parser.add_argument('--max-detail', type=int, default=25,
                       help='Max detail pages to fetch (default: 25)')
    parser.add_argument('--min-sample-ok', type=int, default=8,
                       help='Min successful detail fetches required (default: 8)')
    parser.add_argument('--max-unique-hosts', type=int, default=None,
                       help='Stop after processing N unique hosts (default: None, no limit)')
    parser.add_argument('--max-transient-failures', type=int, default=10,
                       help='Max transient failures before marking source as deferred (default: 10)')
    
    args = parser.parse_args()
    
    if args.apply:
        args.dry_run = False
    
    print("=" * 70)
    print("WAVE-1 MASS REPAIR RUNNER")
    print("=" * 70)
    if args.dry_run:
        print("[DRY-RUN MODE - No changes will be saved]\n")
    else:
        print("[APPLY MODE - Changes will be saved]\n")
    
    # Load sources
    sources_file = Path(args.sources)
    if not sources_file.is_absolute():
        sources_file = backend_dir.parent / sources_file
    
    sources = load_sources(sources_file)
    if not sources:
        print(f"Error: No sources found in {sources_file}")
        return 1
    
    # Initialize host budget (loads persistent cooldowns)
    host_budget = get_budget(
        min_delay_seconds=args.per_host_delay,
        max_requests_per_run=args.per_host_max,
        default_cooldown_seconds=60
    )
    reset_budget()  # Reset in-memory state, but keep persistent cooldowns
    
    # Select cohort (diversifies by host, skips cooldown hosts)
    cohort = select_cohort(
        sources,
        only_status=args.only_status,
        only_adapter=args.only_adapter,
        max_sources=args.max_sources,
        max_unique_hosts=args.max_unique_hosts,
        host_budget=host_budget
    )
    
    print(f"Selected {len(cohort)} sources for repair")
    if args.max_unique_hosts:
        from urllib.parse import urlparse
        unique_hosts = len(set(urlparse(s.get('url', '')).netloc for s in cohort if s.get('url')))
        print(f"  ({unique_hosts} unique hosts)\n")
    else:
        print()
    
    # Create evidence directory
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    evidence_dir = backend_dir / "_evidence" / "wave1_repair" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each source
    results = []
    improved_count = 0
    promoted_to_working = 0
    deferred_count = 0
    
    for source in cohort:
        source_id = source.get('id', 'unknown')
        firm_name = source.get('firm_name', 'Unknown')
        url = source.get('url', '')
        
        print(f"\n[{source_id}] {firm_name}")
        print(f"  URL: {url}")
        
        result = {
            'source_id': source_id,
            'firm_name': firm_name,
            'url': url,
            'baseline_metrics': {},
            'repair_plan': {},
            'post_repair_metrics': {},
            'patch': {},
            'verified_working': False,
            'network_diagnostics': {}
        }
        
        # Step 1: Baseline test
        print("  → Baseline test...")
        baseline_metrics = test_source_and_return_metrics(source, dry_run=args.dry_run)
        result['baseline_metrics'] = baseline_metrics
        
        print(f"    kept_count={baseline_metrics['kept_count']}, "
              f"dated_ratio={baseline_metrics['dated_ratio']:.1%}, "
              f"future_count={baseline_metrics['future_count']}")
        
        # Step 2: Choose repair plan
        repair_plan = choose_repair_plan(source, baseline_metrics)
        result['repair_plan'] = repair_plan
        print(f"  → Repair plan: {repair_plan['plan']} ({repair_plan['reason']})")
        
        if repair_plan['plan'] == 'none':
            result['verified_working'] = meets_working_threshold(baseline_metrics)
            results.append(result)
            continue
        
        if repair_plan['plan'] == 'deferred':
            deferred_count += 1
            results.append(result)
            continue
        
        # Step 3: Execute repair (only if --repair)
        if not args.repair:
            print("  → [SKIP] Repair actions (use --repair to enable)")
            results.append(result)
            continue
        
        patch = {}
        
        if repair_plan['plan'] == 'autoparser':
            print("  → Running autoparser regeneration...")
            autoparser_result = autoparser_generation(
                url,
                dry_run=args.dry_run,
                host_budget=host_budget
            )
            
            if autoparser_result.get('success') and autoparser_result.get('selectors_json'):
                patch['selectors_json'] = autoparser_result['selectors_json']
                if autoparser_result.get('detail_fetch_patch'):
                    patch['detail_fetch'] = autoparser_result['detail_fetch_patch']
                print(f"    ✓ Generated selectors: {len(autoparser_result.get('sample_events', []))} sample events")
            else:
                print(f"    ✗ Autoparser failed: {autoparser_result.get('error', 'unknown error')}")
                result['error'] = autoparser_result.get('error')
                results.append(result)
                continue
        
        elif repair_plan['plan'] in ['detail_enrichment', 'ics_harvest']:
            print("  → Running detail enrichment validator...")
            selectors_json = source.get('selectors_json', {})
            if not selectors_json:
                print("    ✗ No selectors available for detail enrichment")
                result['error'] = 'no_selectors_for_detail_enrichment'
                results.append(result)
                continue
            
            enrichment_result = detail_enrichment_validator(
                list_url=url,
                selectors_json=selectors_json,
                firm_name=firm_name,
                max_detail=args.max_detail,
                dry_run=args.dry_run,
                use_cache_only=args.use_cache_only,
                max_new_fetches=None if args.use_cache_only else args.max_detail,
                sampling_mode=args.sampling_mode,
                min_sample_ok=args.min_sample_ok,
                host_budget=host_budget
            )
            
            # Check for transient failures in metrics
            metrics = enrichment_result.get('metrics', {})
            accessibility_counts = metrics.get('accessibility_counts', {})
            transient_count = accessibility_counts.get('deferred_transient_network', 0)
            succeeded = metrics.get('detail_pages_succeeded', 0)
            
            # Early escalation: if 0 successes and >K transient failures, mark as deferred
            max_transient_failures = args.max_transient_failures
            if succeeded == 0 and transient_count >= max_transient_failures:
                print(f"    ⚠ Early escalation: {transient_count} transient failures, 0 successes")
                print(f"    → Marking source as deferred_transient_network")
                result['error'] = 'deferred_transient_network'
                result['error_class'] = 'deferred_transient_network'
                result['error_evidence'] = f'{transient_count} transient failures, 0 successes'
                # Record persistent cooldown for this host
                if host_budget:
                    host_budget.record_result(url, error_class='deferred_transient_network')
                results.append(result)
                continue
            
            if enrichment_result.get('recommended_detail_fetch'):
                patch['detail_fetch'] = enrichment_result['recommended_detail_fetch']
                print(f"    ✓ Detail enrichment: {enrichment_result.get('classification')}")
                print(f"      dated_ratio={enrichment_result['metrics'].get('dated_ratio', 0):.1%}")
            else:
                print(f"    ✗ Detail enrichment failed: {enrichment_result.get('recommended_action', 'unknown')}")
                result['error'] = enrichment_result.get('recommended_action')
                # If transient network issue, record cooldown
                if 'transient' in enrichment_result.get('recommended_action', '').lower():
                    if host_budget:
                        host_budget.record_result(url, error_class='deferred_transient_network')
                results.append(result)
                continue
        
        # Step 4: Test with patch (if patch was generated)
        if patch:
            print("  → Testing with patch...")
            patched_source = apply_patch_to_source(source, patch)
            post_repair_metrics = test_source_and_return_metrics(patched_source, dry_run=args.dry_run)
            result['post_repair_metrics'] = post_repair_metrics
            result['patch'] = patch
            
            print(f"    kept_count={post_repair_metrics['kept_count']}, "
                  f"dated_ratio={post_repair_metrics['dated_ratio']:.1%}, "
                  f"future_count={post_repair_metrics['future_count']}")
            
            # Step 5: Decide whether to apply patch
            if meets_working_threshold(post_repair_metrics):
                result['verified_working'] = True
                promoted_to_working += 1
                print("    ✓ Meets working threshold - will apply patch")
                
                if args.apply:
                    # Apply patch to sources.json
                    source_map = {s['id']: s for s in sources}
                    if source_id in source_map:
                        sources[sources.index(source_map[source_id])] = patched_source
                        print("    ✓ Patch applied to sources.json")
            else:
                print("    ⚠ Does not meet working threshold - patch not applied")
                if args.apply:
                    print("    [SKIP] Patch not applied (threshold not met)")
        else:
            print("  → No patch generated")
        
        # Collect network diagnostics
        result['network_diagnostics'] = host_budget.get_diagnostics()
        
        results.append(result)
        
        # Check if improved
        if result.get('post_repair_metrics'):
            baseline_kept = baseline_metrics.get('kept_count', 0)
            post_kept = result['post_repair_metrics'].get('kept_count', 0)
            if post_kept > baseline_kept:
                improved_count += 1
    
    # Step 6: Write patches to sources.json if --apply
    if args.apply and promoted_to_working > 0:
        print(f"\n{'='*70}")
        print(f"APPLYING {promoted_to_working} PATCHES TO sources.json")
        print(f"{'='*70}\n")
        
        # Backup
        backup_file = sources_file.with_suffix('.json.backup')
        import shutil
        shutil.copy2(sources_file, backup_file)
        print(f"Backed up to {backup_file.name}")
        
        # Write
        with open(sources_file, 'w') as f:
            json.dump(sources, f, indent=2)
        print(f"Updated {sources_file}")
    
    # Step 7: Generate summary
    run_summary = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'run_id': run_id,
        'dry_run': args.dry_run,
        'total_processed': len(cohort),
        'improved_count': improved_count,
        'promoted_to_working': promoted_to_working,
        'deferred_count': deferred_count,
        'failure_classes': Counter(r.get('baseline_metrics', {}).get('error_class') for r in results if r.get('baseline_metrics', {}).get('error_class')),
        'host_budget_summary': {
            host: {
                'requests': diag.get('requests', 0),
                '429_count': diag.get('429_count', 0),
                '503_count': diag.get('503_count', 0),
                'blocked': diag.get('blocked', False)
            }
            for host, diag in host_budget.get_diagnostics().items()
        },
        'results': results
    }
    
    # Save per-source evidence
    for result in results:
        source_evidence_dir = evidence_dir / result['source_id']
        source_evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_file = source_evidence_dir / "result.json"
        with open(evidence_file, 'w') as f:
            json.dump(result, f, indent=2)
    
    # Save run summary
    summary_file = evidence_dir / "run_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(run_summary, f, indent=2)
    
    # Save cooldown registry state (for inspection)
    cooldown_state_file = evidence_dir / "cooldown_registry.json"
    with open(cooldown_state_file, 'w') as f:
        json.dump(host_budget.get_cooldown_registry(), f, indent=2)
    
    # Print summary
    print(f"\n{'='*70}")
    print("WAVE-1 REPAIR SUMMARY")
    print(f"{'='*70}\n")
    print(f"Total processed: {len(cohort)}")
    print(f"  ✓ Improved: {improved_count}")
    print(f"  ✓ Promoted to working: {promoted_to_working}")
    print(f"  ⚠ Deferred: {deferred_count}")
    
    if run_summary['failure_classes']:
        print("\nTop failure classes:")
        for failure_class, count in run_summary['failure_classes'].most_common(5):
            print(f"  {failure_class}: {count}")
    
    if run_summary['host_budget_summary']:
        print("\nHost budget summary:")
        for host, diag in list(run_summary['host_budget_summary'].items())[:5]:
            print(f"  {host}: {diag['requests']} requests, "
                  f"{diag['429_count']} 429s, {diag['503_count']} 503s")
    
    print(f"\nEvidence saved to: {evidence_dir}")
    print(f"Run summary: {summary_file}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
