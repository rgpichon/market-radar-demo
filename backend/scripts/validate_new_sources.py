#!/usr/bin/env python3
"""
Validate new sources from bulk discovery and activate those that work.

Tests each new source, shows which ones return events, and optionally activates them.

Usage:
    python validate_new_sources.py --dry-run
    python validate_new_sources.py --activate-working
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from db import get_sources, init_db
from utils.pipeline import run_source_pipeline
from utils.lanes import infer_lane_from_source


SOURCES_FILE = backend_dir / "sources.json"
RESULTS_FILE = backend_dir / "new_sources_validation_results.json"


def get_new_sources() -> List[Dict]:
    """Get sources generated from bulk discovery."""
    # Load directly from sources.json to ensure we get all sources
    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)
    
    return [
        s for s in sources
        if 'Generated from bulk discovery' in s.get('comment', '') and s.get('active', 0) == 0
    ]


def validate_source(source: Dict) -> Dict:
    """Validate a source and return results."""
    source_id = source.get('id', '')
    firm_name = source.get('firm_name', '')
    url = source.get('url', '')
    adapter_type = source.get('adapter_type', '')
    
    print(f"\n{'='*60}")
    print(f"Validating: {firm_name} ({source_id})")
    print(f"URL: {url}")
    print(f"Lane: {adapter_type}")
    print(f"{'='*60}")
    
    result = {
        'source_id': source_id,
        'firm_name': firm_name,
        'url': url,
        'adapter_type': adapter_type,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'status': 'unknown',
        'events_found': 0,
        'dated_count': 0,
        'future_count': 0,
        'dated_ratio': 0.0,
        'errors': [],
        'warnings': []
    }
    
    try:
        # Run pipeline
        pipeline_result = run_source_pipeline(source)
        kept_events = pipeline_result.get('kept_events', [])
        run_stats = pipeline_result.get('run_stats', {})
        
        result['events_found'] = len(kept_events)
        result['dated_count'] = run_stats.get('dated_count', 0)
        result['future_count'] = run_stats.get('future_count', 0)
        result['dated_ratio'] = run_stats.get('dated_ratio', 0.0)
        result['kept_ratio'] = run_stats.get('kept_ratio', 0.0)
        result['raw_count'] = run_stats.get('raw_count', 0)
        
        print(f"\nResults:")
        print(f"  Raw events: {result['raw_count']}")
        print(f"  Kept events: {result['events_found']}")
        print(f"  Dated events: {result['dated_count']}")
        print(f"  Future events: {result['future_count']}")
        print(f"  Dated ratio: {result['dated_ratio']:.1%}")
        
        if kept_events:
            print(f"\n  Sample events:")
            for i, event in enumerate(kept_events[:3], 1):
                title = event.get('event_name', 'N/A')[:60]
                date = event.get('date_time', 'No date')
                print(f"    {i}. {title}")
                print(f"       Date: {date}")
        
        # Determine status
        if result['events_found'] >= 3 and result['dated_ratio'] >= 0.70 and result['future_count'] >= 1:
            result['status'] = 'working'
            print(f"\n  ✓ WORKING - Meets quality gates")
        elif result['events_found'] > 0:
            result['status'] = 'partial'
            print(f"\n  ⚠ PARTIAL - Has events but doesn't meet all gates")
            if result['events_found'] < 3:
                result['warnings'].append(f"Only {result['events_found']} events (need 3+)")
            if result['dated_ratio'] < 0.70:
                result['warnings'].append(f"Low date coverage: {result['dated_ratio']:.1%} (need 70%+)")
            if result['future_count'] < 1:
                result['warnings'].append(f"No future events (need 1+)")
        else:
            result['status'] = 'no_events'
            print(f"\n  ✗ NO EVENTS - No events found")
            result['errors'].append("No events extracted")
        
        if run_stats.get('rejected'):
            print(f"\n  Rejections:")
            for reason, count in run_stats['rejected'].items():
                print(f"    {reason}: {count}")
        
    except Exception as e:
        result['status'] = 'error'
        result['errors'].append(str(e))
        print(f"\n  ✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    return result


def activate_source(source_id: str):
    """Activate a source in sources.json."""
    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)
    
    updated = False
    for source in sources:
        if source.get('id') == source_id:
            if source.get('active', 0) != 1:
                source['active'] = 1
                source['activated_at'] = datetime.now(timezone.utc).isoformat()
                updated = True
            break
    
    if updated:
        with open(SOURCES_FILE, 'w') as f:
            json.dump(sources, f, indent=2)
        return True
    
    return False


def main():
    parser = argparse.ArgumentParser(description='Validate new sources from bulk discovery')
    parser.add_argument('--activate-working', action='store_true',
                       help='Activate sources that are working')
    parser.add_argument('--activate-partial', action='store_true',
                       help='Also activate sources with partial results')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Dry run mode (default)')
    
    args = parser.parse_args()
    
    if args.activate_working or args.activate_partial:
        args.dry_run = False
    
    init_db()
    
    # Get new sources
    new_sources = get_new_sources()
    
    print(f"=== Validate New Sources ===")
    print(f"New sources found: {len(new_sources)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    
    if not new_sources:
        print("\nNo new sources to validate.")
        return
    
    # Sort by priority: RSS/ICS first
    def priority_key(source):
        adapter = source.get('adapter_type', '')
        if adapter == 'ics':
            return 0
        elif adapter == 'rss':
            return 1
        elif adapter == 'html_list':
            return 2
        else:
            return 3
    
    new_sources.sort(key=priority_key)
    
    # Validate each source
    results = []
    working_count = 0
    partial_count = 0
    no_events_count = 0
    error_count = 0
    
    for source in new_sources:
        result = validate_source(source)
        results.append(result)
        
        if result['status'] == 'working':
            working_count += 1
        elif result['status'] == 'partial':
            partial_count += 1
        elif result['status'] == 'no_events':
            no_events_count += 1
        else:
            error_count += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"=== Summary ===")
    print(f"{'='*60}")
    print(f"Total validated: {len(results)}")
    print(f"  ✓ Working: {working_count}")
    print(f"  ⚠ Partial: {partial_count}")
    print(f"  ✗ No events: {no_events_count}")
    print(f"  ✗ Errors: {error_count}")
    
    # Working sources
    if working_count > 0:
        print(f"\n=== Working Sources ({working_count}) ===")
        for result in results:
            if result['status'] == 'working':
                print(f"  {result['firm_name']} ({result['source_id']})")
                print(f"    Events: {result['events_found']}, Future: {result['future_count']}, Dated: {result['dated_ratio']:.1%}")
    
    # Partial sources
    if partial_count > 0:
        print(f"\n=== Partial Sources ({partial_count}) ===")
        for result in results:
            if result['status'] == 'partial':
                print(f"  {result['firm_name']} ({result['source_id']})")
                print(f"    Events: {result['events_found']}, Future: {result['future_count']}, Dated: {result['dated_ratio']:.1%}")
                if result['warnings']:
                    print(f"    Warnings: {', '.join(result['warnings'])}")
    
    # Activate working sources
    activated = []
    if not args.dry_run:
        print(f"\n=== Activation ===")
        for result in results:
            should_activate = False
            if result['status'] == 'working' and args.activate_working:
                should_activate = True
            elif result['status'] == 'partial' and args.activate_partial:
                should_activate = True
            
            if should_activate:
                if activate_source(result['source_id']):
                    activated.append(result['source_id'])
                    print(f"  ✓ Activated: {result['firm_name']} ({result['source_id']})")
        
        if activated:
            print(f"\n✓ Activated {len(activated)} sources")
            print(f"  Run sync_registry.py and run_scrape.py to update data")
        else:
            print(f"\nNo sources activated (use --activate-working or --activate-partial)")
    
    # Save results
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'summary': {
            'total': len(results),
            'working': working_count,
            'partial': partial_count,
            'no_events': no_events_count,
            'errors': error_count
        },
        'results': results,
        'activated': activated if not args.dry_run else []
    }
    
    with open(RESULTS_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults saved to: {RESULTS_FILE}")


if __name__ == '__main__':
    main()
