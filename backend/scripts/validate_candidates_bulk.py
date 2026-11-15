#!/usr/bin/env python3
"""
Bulk validation of source candidates.

Validates candidates from source_candidates.json and produces validated candidates.

Usage:
    python validate_candidates_bulk.py --priority p0 --dry-run
    python validate_candidates_bulk.py --priority p0 --apply
"""
import sys
import json
import argparse
import requests
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import Counter

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from adapters.rss_feed import extract_events as extract_rss
from adapters.ics_calendar import extract_events as extract_ics
from utils.pipeline import run_source_pipeline


CANDIDATES_FILE = backend_dir / "source_candidates.json"
VALIDATED_FILE = backend_dir / "source_candidates_validated.json"


def validate_rss_ics_candidate(candidate: Dict) -> Dict:
    """Validate RSS/ICS candidate."""
    url = candidate['url']
    lane = candidate['lane']
    
    result = {
        'url': url,
        'lane': lane,
        'status': 'unknown',
        'item_count': 0,
        'dated_count': 0,
        'dated_ratio': 0.0,
        'future_count': 0,
        'future_ratio': 0.0,
        'failure_class': None,
        'evidence': {}
    }
    
    try:
        # Test fetch
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        result['evidence']['status_code'] = response.status_code
        result['evidence']['content_type'] = response.headers.get('Content-Type', '')
        
        if response.status_code != 200:
            result['status'] = 'failed'
            result['failure_class'] = 'http_error'
            result['evidence']['error'] = f"HTTP {response.status_code}"
            return result
        
        # Parse feed
        source_config = {
            'firm_name': candidate.get('firm_name', 'Test'),
            'default_tags_json': [],
            'enforce_events_only': False  # Don't filter for validation
        }
        
        if lane == 'ics':
            events, stats = extract_ics(url, source_config, return_stats=True)
        else:  # rss/atom
            events, stats = extract_rss(url, source_config, return_stats=True)
        
        result['item_count'] = len(events)
        result['evidence']['raw_count'] = stats.get('raw', 0)
        result['evidence']['kept_count'] = stats.get('kept', len(events))
        
        if stats.get('rejected'):
            result['evidence']['rejected'] = stats['rejected']
        
        # Count dated and future events
        from datetime import datetime, timezone as tz
        now = datetime.now(tz.utc)
        
        dated_count = 0
        future_count = 0
        
        for event in events:
            date_time = event.get('date_time')
            if date_time:
                dated_count += 1
                try:
                    # Parse ISO datetime
                    if isinstance(date_time, str):
                        if date_time.endswith('Z'):
                            date_time = date_time[:-1] + '+00:00'
                        dt = datetime.fromisoformat(date_time)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=tz.utc)
                        if dt >= now:
                            future_count += 1
                except (ValueError, TypeError):
                    pass
        
        result['dated_count'] = dated_count
        result['dated_ratio'] = dated_count / len(events) if events else 0.0
        result['future_count'] = future_count
        result['future_ratio'] = future_count / len(events) if events else 0.0
        
        # Determine status
        if len(events) == 0:
            result['status'] = 'failed'
            result['failure_class'] = 'no_events'
        elif len(events) < 3:
            result['status'] = 'deferred'
            result['failure_class'] = 'insufficient_events'
        elif result['dated_ratio'] < 0.70:
            result['status'] = 'deferred'
            result['failure_class'] = 'low_date_coverage'
        elif result['future_count'] == 0:
            result['status'] = 'deferred'
            result['failure_class'] = 'no_future_events'
        else:
            result['status'] = 'ready_to_onboard'
        
        # Check for press release patterns
        if events:
            press_keywords = ['press release', 'announcement', 'earnings', 'quarterly results']
            press_count = 0
            for event in events:
                title = event.get('event_name', '').lower()
                if any(kw in title for kw in press_keywords):
                    press_count += 1
            
            press_ratio = press_count / len(events)
            if press_ratio > 0.7:
                result['status'] = 'failed'
                result['failure_class'] = 'press_release_only'
                result['evidence']['press_ratio'] = press_ratio
    
    except requests.RequestException as e:
        result['status'] = 'failed'
        result['failure_class'] = 'network_error'
        result['evidence']['error'] = str(e)
    except Exception as e:
        result['status'] = 'failed'
        result['failure_class'] = 'parse_error'
        result['evidence']['error'] = str(e)
    
    return result


def validate_html_candidate(candidate: Dict) -> Dict:
    """Validate HTML candidate using metadata-first approach."""
    from utils.metadata_first_validator import validate_html_source_metadata_first
    
    url = candidate['url']
    
    result = {
        'url': url,
        'lane': candidate['lane'],
        'status': 'unknown',
        'tier': 'C',
        'html_feasible': False,
        'js_rendered': False,
        'failure_class': None,
        'evidence': {},
        'selectors_json': {},
        'detail_fetch_patch': None
    }
    
    try:
        # Use metadata-first validator
        validation_result = validate_html_source_metadata_first(url, candidate.get('firm_name', 'Unknown'))
        
        # Map new validation statuses to legacy format
        status_mapping = {
            'validated_structured': 'ready_to_onboard',
            'validated_detail_recovered': 'ready_to_onboard_with_detail_fetch',
            'validated_json_api': 'ready_to_onboard',
            'validated_selector': 'ready_to_onboard',
            'partial_needs_detail': 'ready_to_onboard_with_detail_fetch',
            'no_events': 'deferred',
            'gated_login': 'failed',
            'js_rendered_blocked': 'deferred'
        }
        
        result['status'] = status_mapping.get(validation_result['status'], 'deferred')
        result['tier'] = 'A' if validation_result['validation_method'] in ['jsonld', 'microdata'] else 'B'
        result['selectors_json'] = validation_result.get('selectors_json', {})
        result['detail_fetch_patch'] = validation_result.get('detail_fetch_config')
        result['html_feasible'] = validation_result['status'].startswith('validated') or validation_result['status'] == 'partial_needs_detail'
        
        # Map failure classes
        failure_class_mapping = {
            'validated_structured': None,
            'validated_detail_recovered': None,
            'validated_json_api': None,
            'validated_selector': None,
            'partial_needs_detail': None,
            'no_events': 'no_events',
            'gated_login': 'gated_login',
            'js_rendered_blocked': 'js_rendered_suspected'
        }
        result['failure_class'] = failure_class_mapping.get(validation_result['status'])
        
        # Evidence
        result['evidence'] = {
            'validation_method': validation_result['validation_method'],
            'events_found': validation_result['events_found'],
            'future_events': validation_result['future_events'],
            'dated_events': validation_result['dated_events'],
            **validation_result.get('evidence', {})
        }
        
        # Save evidence
        candidate_id = candidate.get('firm_name', 'unknown').replace(' ', '_').lower() + '_' + url.split('/')[-1][:20]
        evidence_dir = backend_dir / "_evidence" / "source_validation" / candidate_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        
        evidence_file = evidence_dir / "metadata_first_validation.json"
        with open(evidence_file, 'w') as f:
            json.dump(validation_result, f, indent=2)
        
        result['evidence']['validation_evidence'] = str(evidence_file.relative_to(backend_dir))
        
        # Add recommended_next_action from validation
        if validation_result.get('recommended_next_action'):
            result['recommended_next_action'] = validation_result['recommended_next_action']
        
        # Detail enrichment (if enabled and candidate is partial)
        if args.enable_detail_enrichment:
            # Check if candidate would benefit from detail enrichment
            is_partial = result['status'] in ['ready_to_onboard_with_detail_fetch', 'partial_needs_detail', 'deferred']
            has_selectors = result.get('selectors_json', {}).get('item_selector')
            
            if is_partial and has_selectors:
                from utils.detail_enrich import validate_detail_enrichment
                enrichment_result = validate_detail_enrichment(
                    list_url=url,
                    selectors_json=result['selectors_json'],
                    firm_name=candidate.get('firm_name', 'Unknown'),
                    max_detail=25,
                    dry_run=not args.apply,
                    sampling_mode='stratified',
                    min_sample_ok=8
                )
                
                # Update result if enrichment improved classification
                enrichment_class = enrichment_result.get('classification', 'unknown')
                enrichment_metrics = enrichment_result.get('metrics', {})
                
                if enrichment_class == 'ready_to_onboard':
                    result['status'] = 'ready_to_onboard'
                    result['detail_fetch_patch'] = {
                        'enabled': True,
                        'max': 25,
                        'stop_after_first_valid': True,
                        'harvest_ics': True,
                        'date_selector': 'script[type="application/ld+json"], time[datetime], meta[itemprop="startDate"], meta[property*="date"], .date, .event-date',
                        'date_attr': 'datetime'
                    }
                    result['evidence']['detail_enrichment'] = enrichment_metrics
                    result['recommended_next_action'] = 'ready_to_onboard_after_enrichment'
                    result['tier'] = 'A'  # Upgraded tier
                elif enrichment_class == 'partial_needs_detail':
                    # Still partial but with better metrics
                    result['evidence']['detail_enrichment'] = enrichment_metrics
                    result['recommended_next_action'] = enrichment_result.get('recommended_action', result.get('recommended_next_action'))
                    # Update status if metrics improved
                    if enrichment_metrics.get('dated_ratio', 0) > 0.3:
                        result['status'] = 'ready_to_onboard_with_detail_fetch'
                        if not result.get('detail_fetch_patch'):
                            result['detail_fetch_patch'] = {
                                'enabled': True,
                                'max': 25,
                                'harvest_ics': True
                            }
                    
                    # Use maintenance playbooks if requested
                    if args.use_maintenance_playbooks:
                        from utils.source_repair import select_playbook
                        # Create a mock source dict for playbook
                        mock_source = {
                            'id': candidate.get('firm_name', 'candidate').replace(' ', '_').lower(),
                            'url': url,
                            'detail_fetch': result.get('detail_fetch_patch', {})
                        }
                        mock_degradation = {
                            'degraded': True,
                            'degradation_class': 'drop_dated_ratio',
                            'recommended_playbook': 'dates_on_detail'
                        }
                        patch, actions, why = select_playbook(mock_source, mock_degradation, evidence=enrichment_metrics)
                        if patch:
                            # Merge patch into detail_fetch_patch
                            if 'detail_fetch' in patch:
                                current = result.get('detail_fetch_patch', {})
                                current.update(patch['detail_fetch'])
                                result['detail_fetch_patch'] = current
                            result['evidence']['maintenance_playbook'] = {
                                'playbook': 'dates_on_detail',
                                'why': why,
                                'patch': patch
                            }
        
        # Test with generated selectors if available (only for selector-based validation)
        if result['selectors_json'] and result['status'] in ['ready_to_onboard', 'ready_to_onboard_with_detail_fetch'] and validation_result['validation_method'] in ['dom_cluster', 'jsonld', 'microdata']:
            try:
                source_config = {
                    'id': 'test_validation',
                    'firm_name': candidate.get('firm_name', 'Test'),
                    'url': url,
                    'adapter_type': 'html_list',
                    'selectors_json': result['selectors_json'],
                    'default_tags_json': [],
                    'enforce_events_only': False  # Don't filter for validation
                }
                
                # Add detail_fetch if needed
                if result['detail_fetch_patch']:
                    source_config['detail_fetch'] = result['detail_fetch_patch']
                
                pipeline_result = run_source_pipeline(source_config)
                kept_events = pipeline_result.get('kept_events', [])
                result['evidence']['test_scrape_count'] = len(kept_events)
                
                if len(kept_events) == 0:
                    # Selectors didn't work, downgrade
                    result['status'] = 'deferred'
                    result['failure_class'] = 'no_events_extracted'
            except Exception as e:
                # Pipeline failed - log but don't fail validation
                result['evidence']['test_scrape_error'] = str(e)
        
    except requests.RequestException as e:
        result['status'] = 'failed'
        result['failure_class'] = 'http_error'
        result['evidence']['error'] = str(e)
    except Exception as e:
        result['status'] = 'failed'
        result['failure_class'] = 'validation_error'
        result['evidence']['error'] = str(e)
    
    return result


def validate_candidate(candidate: Dict) -> Dict:
    """Validate a single candidate."""
    lane = candidate.get('lane', '')
    
    if lane in ['rss', 'ics']:
        return validate_rss_ics_candidate(candidate)
    elif lane == 'html_list':
        return validate_html_candidate(candidate)
    else:
        return {
            'url': candidate['url'],
            'lane': lane,
            'status': 'failed',
            'failure_class': 'unsupported_lane',
            'evidence': {'error': f"Unsupported lane: {lane}"}
        }


def main():
    parser = argparse.ArgumentParser(description='Bulk validation of source candidates')
    parser.add_argument('--priority', choices=['p0', 'p1', 'p2', 'all'], default='p0',
                       help='Priority filter')
    parser.add_argument('--apply', action='store_true',
                       help='Write results to source_candidates_validated.json')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Dry run mode (default)')
    parser.add_argument('--top-n', type=int, default=3,
                       help='Validate top N candidates per firm')
    parser.add_argument('--enable-detail-enrichment', action='store_true',
                       help='Enable detail enrichment for partial_needs_detail candidates')
    parser.add_argument('--use-maintenance-playbooks', action='store_true',
                       help='Use maintenance playbooks for partial_needs_detail and selector_drift_suspected candidates')
    
    args = parser.parse_args()
    
    if args.apply:
        args.dry_run = False
    
    # Load candidates
    if not CANDIDATES_FILE.exists():
        print(f"Error: {CANDIDATES_FILE} not found. Run discover_sources_bulk.py first.")
        sys.exit(1)
    
    with open(CANDIDATES_FILE, 'r') as f:
        candidates_data = json.load(f)
    
    firms = candidates_data.get('firms', [])
    
    # Filter by priority if needed
    if args.priority != 'all':
        firms = [f for f in firms if f.get('firm_type')]  # We'll filter by firm_type if needed
    
    print(f"=== Bulk Validation ===")
    print(f"Priority: {args.priority}")
    print(f"Firms to process: {len(firms)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()
    
    validated_results = []
    
    for firm_data in firms:
        firm_name = firm_data.get('firm_name', '')
        candidates = firm_data.get('candidates', [])
        
        print(f"\n=== Validating: {firm_name} ===")
        print(f"Candidates: {len(candidates)}")
        
        # Take top N candidates
        top_candidates = candidates[:args.top_n]
        
        firm_validated = {
            'firm_name': firm_name,
            'firm_type': firm_data.get('firm_type', ''),
            'candidates_validated': []
        }
        
        for candidate in top_candidates:
            print(f"  Validating: {candidate['url']} ({candidate['lane']})")
            
            # Add firm_name to candidate for validation
            candidate['firm_name'] = firm_name
            
            validated = validate_candidate(candidate)
            firm_validated['candidates_validated'].append(validated)
            
            status = validated.get('status', 'unknown')
            failure_class = validated.get('failure_class')
            
            if status == 'ready_to_onboard':
                print(f"    ✓ Ready to onboard")
            elif status == 'deferred':
                print(f"    ⚠ Deferred: {failure_class}")
            else:
                print(f"    ✗ Failed: {failure_class}")
        
        validated_results.append(firm_validated)
    
    # Summary
    total_validated = sum(len(r['candidates_validated']) for r in validated_results)
    ready_count = sum(
        1 for r in validated_results
        for c in r['candidates_validated']
        if c.get('status') == 'ready_to_onboard'
    )
    deferred_count = sum(
        1 for r in validated_results
        for c in r['candidates_validated']
        if c.get('status') == 'deferred'
    )
    failed_count = sum(
        1 for r in validated_results
        for c in r['candidates_validated']
        if c.get('status') == 'failed'
    )
    
    print(f"\n=== Summary ===")
    print(f"Total validated: {total_validated}")
    print(f"Ready to onboard: {ready_count}")
    print(f"Deferred: {deferred_count}")
    print(f"Failed: {failed_count}")
    
    # Group by failure class
    failure_classes = Counter()
    for r in validated_results:
        for c in r['candidates_validated']:
            fc = c.get('failure_class')
            if fc:
                failure_classes[fc] += 1
    
    if failure_classes:
        print(f"\nFailure classes:")
        for fc, count in failure_classes.most_common():
            print(f"  {fc}: {count}")
    
    # Write results if --apply
    if not args.dry_run:
        output = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'priority': args.priority,
            'firms': validated_results
        }
        
        with open(VALIDATED_FILE, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"\nResults written to: {VALIDATED_FILE}")
    else:
        print(f"\n[DRY RUN] Results would be written to: {VALIDATED_FILE}")
        print(f"Use --apply to write results")
    
    # Acceptance criteria check
    firms_with_ready = sum(
        1 for r in validated_results
        if any(c.get('status') == 'ready_to_onboard' for c in r['candidates_validated'])
    )
    
    if firms_with_ready >= len(firms) * 0.5:  # At least 50% have ready candidates
        print(f"\n✓ Acceptance criteria met: {firms_with_ready}/{len(firms)} firms have ready candidates")
    else:
        print(f"\n⚠ Acceptance criteria: {firms_with_ready}/{len(firms)} firms have ready candidates")


if __name__ == '__main__':
    main()
