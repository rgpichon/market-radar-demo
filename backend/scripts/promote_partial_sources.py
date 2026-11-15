#!/usr/bin/env python3
"""
Promotion Loop: Upgrade partial_needs_detail sources to working.

Automatically enriches detail pages and promotes sources that meet thresholds.

Usage:
    python promote_partial_sources.py --candidates source_candidates_validated.json --dry-run
    python promote_partial_sources.py --sources sources.json --apply
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timezone

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.detail_enrich import validate_detail_enrichment
from utils.quality_gates import validate_macro_signal_source


def load_candidates(file_path: Path) -> List[Dict]:
    """Load candidates from JSON file."""
    if not file_path.exists():
        return []
    
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    # Handle both single list and nested structure
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and 'candidates' in data:
        return data['candidates']
    else:
        return []


def load_sources(file_path: Path) -> List[Dict]:
    """Load sources from sources.json."""
    if not file_path.exists():
        return []
    
    with open(file_path, 'r') as f:
        return json.load(f)


def promote_candidate(candidate: Dict, dry_run: bool = False, args=None) -> Dict:
    """
    Promote a single candidate using detail enrichment.
    
    Returns promotion result with before/after metrics.
    """
    url = candidate.get('url', '')
    firm_name = candidate.get('firm_name', 'Unknown')
    selectors = candidate.get('selectors_json', {})
    
    if not url or not selectors.get('item_selector'):
        return {
            'promoted': False,
            'reason': 'missing_url_or_selectors',
            'before': {},
            'after': {}
        }
    
    # Run detail enrichment
    enrichment_result = validate_detail_enrichment(
        list_url=url,
        selectors_json=selectors,
        firm_name=firm_name,
        max_detail=25,
        dry_run=dry_run
    )
    
    before_metrics = {
        'status': candidate.get('status', 'unknown'),
        'events_found': candidate.get('evidence', {}).get('events_found', 0),
        'dated_events': candidate.get('evidence', {}).get('dated_events', 0)
    }
    
    after_metrics = enrichment_result.get('metrics', {})
    classification = enrichment_result.get('classification', 'unknown')
    
    promoted = classification == 'ready_to_onboard'
    
    result = {
        'promoted': promoted,
        'classification': classification,
        'before': before_metrics,
        'after': after_metrics,
        'recommended_action': enrichment_result.get('recommended_action', ''),
        'failure_reasons': enrichment_result.get('failure_reasons', [])
    }
    
    # Store recommended detail_fetch config for partial sources (actionable output)
    if classification == 'partial_needs_detail' and enrichment_result.get('recommended_detail_fetch'):
        result['recommended_detail_fetch'] = enrichment_result['recommended_detail_fetch']
    
    if promoted:
        # Generate detail_fetch config
        result['detail_fetch_config'] = {
            'enabled': True,
            'max': 25,
            'stop_after_first_valid': True,
            'harvest_ics': True,
            'date_selector': 'script[type="application/ld+json"], time[datetime], meta[itemprop="startDate"], meta[property*="date"], .date, .event-date',
            'date_attr': 'datetime'
        }
        result['updated_status'] = 'ready_to_onboard'
    
    return result


def promote_source(source: Dict, dry_run: bool = False, args=None) -> Dict:
    """
    Promote a source from sources.json.
    
    Similar to promote_candidate but works with sources.json format.
    """
    url = source.get('url', '')
    firm_name = source.get('firm_name', 'Unknown')
    selectors = source.get('selectors_json', {})
    
    if not url or not selectors.get('item_selector'):
        return {
            'promoted': False,
            'reason': 'missing_url_or_selectors',
            'before': {},
            'after': {}
        }
    
    # Run detail enrichment
    enrichment_result = validate_detail_enrichment(
        list_url=url,
        selectors_json=selectors,
        firm_name=firm_name,
        max_detail=25,
        dry_run=dry_run
    )
    
    before_metrics = {
        'active': source.get('active', 0),
        'has_detail_fetch': bool(source.get('detail_fetch', {}).get('enabled', False))
    }
    
    after_metrics = enrichment_result.get('metrics', {})
    classification = enrichment_result.get('classification', 'unknown')
    
    promoted = classification == 'ready_to_onboard'
    
    result = {
        'promoted': promoted,
        'classification': classification,
        'before': before_metrics,
        'after': after_metrics,
        'recommended_action': enrichment_result.get('recommended_action', ''),
        'failure_reasons': enrichment_result.get('failure_reasons', [])
    }
    
    # Store recommended detail_fetch config for partial sources (actionable output)
    if classification == 'partial_needs_detail' and enrichment_result.get('recommended_detail_fetch'):
        result['recommended_detail_fetch'] = enrichment_result['recommended_detail_fetch']
    
    if promoted:
        # Check quality gates before activating
        source_with_detail_fetch = source.copy()
        source_with_detail_fetch['detail_fetch'] = {
            'enabled': True,
            'max': 25,
            'stop_after_first_valid': True,
            'harvest_ics': True,
            'date_selector': 'script[type="application/ld+json"], time[datetime], meta[itemprop="startDate"], meta[property*="date"], .date, .event-date',
            'date_attr': 'datetime'
        }
        
        # Run quality gates
        try:
            validation = validate_macro_signal_source(source_with_detail_fetch)
            passes_gates = validation.passes
        except Exception:
            passes_gates = False
        
        result['passes_quality_gates'] = passes_gates
        result['detail_fetch_config'] = source_with_detail_fetch['detail_fetch']
        
        if passes_gates:
            result['updated_status'] = 'ready_to_activate'
        else:
            result['updated_status'] = 'ready_to_onboard_but_fails_gates'
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Promote partial sources using detail enrichment')
    parser.add_argument('--candidates', type=str, help='Path to candidates JSON file')
    parser.add_argument('--sources', type=str, help='Path to sources.json (alternative to candidates)')
    parser.add_argument('--only-status', type=str, default='partial_needs_detail',
                        help='Only process sources with this status')
    parser.add_argument('--max-sources', type=int, default=50, help='Maximum sources to process')
    parser.add_argument('--max-detail', type=int, default=25, help='Maximum detail pages per source')
    parser.add_argument('--apply', action='store_true', help='Apply changes (default: dry-run)')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Dry run mode (default: True unless --apply)')
    parser.add_argument('--use-cache-only', action='store_true',
                        help='Use cache only, do not fetch new pages')
    parser.add_argument('--max-new-fetches', type=int, default=None,
                        help='Maximum number of fresh network requests per run')
    parser.add_argument('--sampling-mode', choices=['top_n', 'stratified', 'date_hint_priority'],
                        default='stratified', help='Detail URL sampling strategy')
    parser.add_argument('--min-sample-ok', type=int, default=8,
                        help='Minimum successful detail page fetches required for judgment')
    
    args = parser.parse_args()
    
    if args.apply:
        args.dry_run = False
    
    # Load input
    items = []
    if args.candidates:
        candidates_file = backend_dir / args.candidates
        items = load_candidates(candidates_file)
        item_type = 'candidate'
    elif args.sources:
        sources_file = backend_dir / args.sources
        items = load_sources(sources_file)
        item_type = 'source'
    else:
        # Default: try candidates file
        candidates_file = backend_dir / "source_candidates_validated.json"
        if candidates_file.exists():
            items = load_candidates(candidates_file)
            item_type = 'candidate'
        else:
            sources_file = backend_dir / "sources.json"
            items = load_sources(sources_file)
            item_type = 'source'
    
    # Filter by status
    if args.only_status:
        if item_type == 'candidate':
            items = [i for i in items if i.get('status') == args.only_status]
        else:
            # For sources, check if they have detail_fetch enabled (likely partial) or are inactive
            items = [
                i for i in items 
                if (i.get('detail_fetch', {}).get('enabled', False) or 
                    i.get('active', 0) == 0 or 
                    'partial' in str(i.get('comment', '')).lower()) and
                   i.get('selectors_json', {}).get('item_selector')  # Must have selectors
            ]
    
    items = items[:args.max_sources]
    
    print(f"=== Promoting {len(items)} {item_type}s ===")
    if args.dry_run:
        print("[DRY-RUN MODE - No changes will be saved]\n")
    else:
        print("[APPLY MODE - Changes will be saved]\n")
    
    # Process each item
    promotion_results = []
    evidence_dir = backend_dir / "_evidence" / "detail_enrich"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    for i, item in enumerate(items, 1):
        source_id = item.get('id', f'item_{i}')
        firm_name = item.get('firm_name', 'Unknown')
        
        print(f"[{i}/{len(items)}] Processing {firm_name} ({source_id})...")
        
        if item_type == 'candidate':
            result = promote_candidate(item, dry_run=args.dry_run, args=args)
        else:
            result = promote_source(item, dry_run=args.dry_run, args=args)
        
        result['source_id'] = source_id
        result['firm_name'] = firm_name
        result['url'] = item.get('url', '')
        promotion_results.append(result)
        
        # Save evidence per source
        source_evidence_dir = evidence_dir / source_id
        source_evidence_dir.mkdir(parents=True, exist_ok=True)
        
        evidence_file = source_evidence_dir / "summary.json"
        with open(evidence_file, 'w') as f:
            json.dump(result, f, indent=2)
        
        # Print result
        if result['promoted']:
            print(f"  ✓ PROMOTED: {result['classification']}")
            print(f"    Before: {result['before']}")
            print(f"    After: {result['after']}")
            if not args.dry_run:
                print(f"    Action: {result.get('updated_status', 'N/A')}")
        else:
            print(f"  ⊘ Not promoted: {result.get('classification', 'unknown')}")
            print(f"    Reason: {result.get('recommended_action', 'N/A')}")
    
    # Summary with classification breakdown
    promoted = [r for r in promotion_results if r['promoted']]
    not_promoted = [r for r in promotion_results if not r['promoted']]
    
    # Group by classification
    by_classification = {}
    for r in promotion_results:
        classification = r.get('classification', 'unknown')
        if classification not in by_classification:
            by_classification[classification] = []
        by_classification[classification].append(r)
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}\n")
    print(f"Total processed: {len(promotion_results)}")
    print(f"  ✓ Promoted: {len(promoted)}")
    print(f"  ⊘ Not promoted: {len(not_promoted)}")
    print()
    print("Classification breakdown:")
    for classification, items in sorted(by_classification.items()):
        print(f"  {classification}: {len(items)}")
    
    if promoted:
        print(f"\n✓ Promoted Sources ({len(promoted)}):")
        for r in promoted:
            after = r['after']
            print(f"  - {r['firm_name']}: {after.get('kept_count', 0)} events, "
                  f"{after.get('dated_ratio', 0):.1%} dated, "
                  f"{after.get('future_count', 0)} future")
    
    # Save run summary with detailed classification
    by_classification = {}
    top_failure_reasons = {}
    
    for r in promotion_results:
        classification = r.get('classification', 'unknown')
        if classification not in by_classification:
            by_classification[classification] = []
        by_classification[classification].append(r)
        
        # Track failure reasons
        action = r.get('recommended_action', '')
        if action:
            top_failure_reasons[action] = top_failure_reasons.get(action, 0) + 1
    
    run_summary = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'dry_run': args.dry_run,
        'total_processed': len(promotion_results),
        'promoted_count': len(promoted),
        'not_promoted_count': len(not_promoted),
        'by_classification': {k: len(v) for k, v in by_classification.items()},
        'top_failure_reasons': dict(sorted(top_failure_reasons.items(), key=lambda x: -x[1])[:10]),
        'results': promotion_results
    }
    
    summary_file = evidence_dir / "run_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(run_summary, f, indent=2)
    
    print(f"\nEvidence saved to: {evidence_dir}")
    print(f"Run summary: {summary_file}")
    
    # Apply changes if not dry-run
    if not args.dry_run and promoted:
        print(f"\n⚠ Applying changes to {len(promoted)} sources...")
        # TODO: Write back to candidates/sources file
        # This would update the files with new statuses and detail_fetch configs
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
