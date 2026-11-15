#!/usr/bin/env python3
"""
Test all sources to determine which work 100%, partial, or failed.

Usage:
    python test_all_sources.py [--active-only] [--inactive-only] [--adapter-type TYPE]
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
import requests
from bs4 import BeautifulSoup

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.pipeline import run_source_pipeline
from utils.html_autoparser import parse_html_autoparser


SOURCES_FILE = backend_dir / "sources.json"


def test_source(source: Dict, verbose: bool = False) -> Dict:
    """
    Test a single source and return results.
    
    Returns:
        {
            'source_id': str,
            'firm_name': str,
            'adapter_type': str,
            'url': str,
            'status': 'working'|'partial'|'failed'|'skipped',
            'events_found': int,
            'dated_events': int,
            'future_events': int,
            'dated_ratio': float,
            'error': str or None,
            'details': dict
        }
    """
    source_id = source.get('id', 'unknown')
    firm_name = source.get('firm_name', 'Unknown')
    adapter_type = source.get('adapter_type', 'unknown')
    url = source.get('url', '')
    
    result = {
        'source_id': source_id,
        'firm_name': firm_name,
        'adapter_type': adapter_type,
        'url': url,
        'status': 'skipped',
        'events_found': 0,
        'dated_events': 0,
        'future_events': 0,
        'dated_ratio': 0.0,
        'error': None,
        'details': {}
    }
    
    if not url:
        result['status'] = 'skipped'
        result['error'] = 'No URL'
        return result
    
    try:
        # Run pipeline
        pipeline_result = run_source_pipeline(source)
        
        kept_events = pipeline_result.get('kept_events', [])
        run_stats = pipeline_result.get('run_stats', {})
        diagnostics = pipeline_result.get('diagnostics', {})
        
        # Count events
        events_found = len(kept_events)
        dated_events = sum(1 for e in kept_events if e.get('date_time'))
        future_events = run_stats.get('future_count', 0)
        dated_ratio = (dated_events / events_found * 100) if events_found > 0 else 0.0
        
        result['events_found'] = events_found
        result['dated_events'] = dated_events
        result['future_events'] = future_events
        result['dated_ratio'] = dated_ratio
        result['details'] = {
            'raw_count': run_stats.get('raw_count', 0),
            'kept_count': run_stats.get('kept_count', 0),
            'rejected': run_stats.get('rejected', {}),
            'extraction_stats': diagnostics.get('extraction_stats', {})
        }
        
        # Determine status
        if events_found == 0:
            result['status'] = 'failed'
            result['error'] = 'No events found'
        elif events_found < 3:
            result['status'] = 'partial'
            result['error'] = f'Only {events_found} events (need 3+)'
        elif dated_ratio < 50:
            result['status'] = 'partial'
            result['error'] = f'Low dated ratio: {dated_ratio:.1f}%'
        elif future_events == 0:
            result['status'] = 'partial'
            result['error'] = 'No future events'
        else:
            result['status'] = 'working'
        
        # Additional checks for HTML sources
        if adapter_type == 'html_list' and result['status'] == 'working':
            # Check if selectors exist
            selectors = source.get('selectors_json', {})
            if not selectors.get('item_selector'):
                result['status'] = 'partial'
                result['error'] = 'Missing selectors'
        
    except Exception as e:
        result['status'] = 'failed'
        result['error'] = str(e)
        if verbose:
            import traceback
            result['details']['traceback'] = traceback.format_exc()
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Test all sources')
    parser.add_argument('--active-only', action='store_true', help='Test only active sources')
    parser.add_argument('--inactive-only', action='store_true', help='Test only inactive sources')
    parser.add_argument('--adapter-type', type=str, help='Filter by adapter type')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--limit', type=int, help='Limit number of sources to test')
    args = parser.parse_args()
    
    # Load sources
    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)
    
    # Filter sources
    if args.active_only:
        sources = [s for s in sources if s.get('active', 0) == 1]
    elif args.inactive_only:
        sources = [s for s in sources if s.get('active', 0) == 0]
    
    if args.adapter_type:
        sources = [s for s in sources if s.get('adapter_type') == args.adapter_type]
    
    if args.limit:
        sources = sources[:args.limit]
    
    print(f"=== Testing {len(sources)} Sources ===\n")
    
    results = []
    for i, source in enumerate(sources, 1):
        source_id = source.get('id', 'unknown')
        firm_name = source.get('firm_name', 'Unknown')
        
        if args.verbose:
            print(f"[{i}/{len(sources)}] Testing {firm_name} ({source_id})...")
        
        result = test_source(source, verbose=args.verbose)
        results.append(result)
        
        if args.verbose:
            status_icon = {
                'working': '✓',
                'partial': '⚠',
                'failed': '✗',
                'skipped': '⊘'
            }.get(result['status'], '?')
            print(f"  {status_icon} {result['status'].upper()}: {result['events_found']} events, {result['dated_ratio']:.1f}% dated")
            if result['error']:
                print(f"    Error: {result['error']}")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    working = [r for r in results if r['status'] == 'working']
    partial = [r for r in results if r['status'] == 'partial']
    failed = [r for r in results if r['status'] == 'failed']
    skipped = [r for r in results if r['status'] == 'skipped']
    
    print(f"\nTotal tested: {len(results)}")
    print(f"  ✓ Working (100%): {len(working)}")
    print(f"  ⚠ Partial: {len(partial)}")
    print(f"  ✗ Failed: {len(failed)}")
    print(f"  ⊘ Skipped: {len(skipped)}")
    
    # By adapter type
    print(f"\nBy Adapter Type:")
    by_type = {}
    for r in results:
        t = r['adapter_type']
        if t not in by_type:
            by_type[t] = {'working': 0, 'partial': 0, 'failed': 0, 'skipped': 0}
        by_type[t][r['status']] = by_type[t].get(r['status'], 0) + 1
    
    for adapter_type in sorted(by_type.keys()):
        stats = by_type[adapter_type]
        total = sum(stats.values())
        working_pct = (stats['working'] / total * 100) if total > 0 else 0
        print(f"  {adapter_type}: {stats['working']}/{total} working ({working_pct:.1f}%)")
    
    # Working sources
    if working:
        print(f"\n✓ Working Sources ({len(working)}):")
        for r in sorted(working, key=lambda x: x['firm_name']):
            print(f"  - {r['firm_name']}: {r['events_found']} events, {r['dated_ratio']:.1f}% dated, {r['future_events']} future")
    
    # Partial sources
    if partial:
        print(f"\n⚠ Partial Sources ({len(partial)}):")
        for r in sorted(partial, key=lambda x: x['firm_name'])[:10]:  # Top 10
            print(f"  - {r['firm_name']}: {r['events_found']} events, {r['dated_ratio']:.1f}% dated - {r['error']}")
        if len(partial) > 10:
            print(f"  ... and {len(partial) - 10} more")
    
    # Failed sources
    if failed:
        print(f"\n✗ Failed Sources ({len(failed)}):")
        for r in sorted(failed, key=lambda x: x['firm_name'])[:10]:  # Top 10
            print(f"  - {r['firm_name']}: {r['error']}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
