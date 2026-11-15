#!/usr/bin/env python3
"""
Test HTML autoparser on actual sources from sources.json.

Usage:
    python test_autoparser_on_sources.py --source-id <source_id>
    python test_autoparser_on_sources.py --all-inactive
"""
import sys
import json
import argparse
import requests
from pathlib import Path
from typing import Dict, List

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.html_autoparser import parse_html_autoparser


SOURCES_FILE = backend_dir / "sources.json"


def test_source(source: Dict) -> Dict:
    """Test autoparser on a single source."""
    source_id = source.get('id', '')
    firm_name = source.get('firm_name', '')
    url = source.get('url', '')
    
    print(f"\n{'='*70}")
    print(f"Testing: {firm_name} ({source_id})")
    print(f"URL: {url}")
    print(f"{'='*70}")
    
    try:
        # Fetch HTML
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            print(f"✗ HTTP {response.status_code}")
            return {
                'source_id': source_id,
                'success': False,
                'error': f'HTTP {response.status_code}'
            }
        
        # Run autoparser
        result = parse_html_autoparser(url, response.text, response.url)
        
        # Print results
        print(f"\nDetected Mode: {result['detected_mode']}")
        print(f"Tier: {result['tier']}")
        print(f"Sample Events: {len(result.get('sample_events', []))}")
        
        if result.get('selectors_json'):
            print(f"\n✓ Selectors Generated:")
            for key, value in result['selectors_json'].items():
                print(f"  {key}: {value}")
        else:
            print(f"\n✗ No selectors generated")
        
        if result.get('detail_fetch_patch'):
            print(f"\n⚠ Detail Fetch Required:")
            for key, value in result['detail_fetch_patch'].items():
                print(f"  {key}: {value}")
        
        if result.get('sample_events'):
            print(f"\nSample Events (first 3):")
            for i, event in enumerate(result['sample_events'][:3], 1):
                print(f"  {i}. {event.get('title', 'N/A')[:60]}")
                print(f"     URL: {event.get('url', 'N/A')[:60]}")
                if event.get('date_iso'):
                    print(f"     Date: {event['date_iso']}")
                elif event.get('date_text'):
                    print(f"     Date: {event['date_text']}")
                else:
                    print(f"     Date: (not found)")
        
        diagnostics = result.get('diagnostics', {})
        if diagnostics:
            print(f"\nDiagnostics:")
            for key, value in diagnostics.items():
                if key != 'sample_events':
                    print(f"  {key}: {value}")
        
        return {
            'source_id': source_id,
            'success': True,
            'detected_mode': result['detected_mode'],
            'tier': result['tier'],
            'has_selectors': bool(result.get('selectors_json')),
            'events_found': len(result.get('sample_events', [])),
            'needs_detail_fetch': bool(result.get('detail_fetch_patch')),
            'selectors': result.get('selectors_json', {}),
            'detail_fetch': result.get('detail_fetch_patch')
        }
        
    except requests.RequestException as e:
        print(f"✗ Request failed: {e}")
        return {
            'source_id': source_id,
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'source_id': source_id,
            'success': False,
            'error': str(e)
        }


def main():
    parser = argparse.ArgumentParser(description='Test HTML autoparser on sources')
    parser.add_argument('--source-id', help='Test specific source ID')
    parser.add_argument('--all-inactive', action='store_true',
                       help='Test all inactive HTML sources without selectors')
    parser.add_argument('--limit', type=int, default=10,
                       help='Limit number of sources to test (default: 10)')
    
    args = parser.parse_args()
    
    # Load sources
    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)
    
    # Filter sources to test
    if args.source_id:
        sources_to_test = [s for s in sources if s.get('id') == args.source_id]
        if not sources_to_test:
            print(f"Source '{args.source_id}' not found")
            return 1
    elif args.all_inactive:
        sources_to_test = [
            s for s in sources
            if s.get('adapter_type') == 'html_list' and
            s.get('active', 0) == 0 and
            (not s.get('selectors_json') or not s.get('selectors_json').get('item_selector'))
        ][:args.limit]
    else:
        print("Error: Must specify --source-id or --all-inactive")
        parser.print_help()
        return 1
    
    print(f"=== Testing HTML Autoparser on {len(sources_to_test)} Sources ===\n")
    
    results = []
    for source in sources_to_test:
        result = test_source(source)
        results.append(result)
    
    # Summary
    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    
    successful = [r for r in results if r.get('success')]
    with_selectors = [r for r in successful if r.get('has_selectors')]
    with_events = [r for r in successful if r.get('events_found', 0) > 0]
    needs_detail_fetch = [r for r in successful if r.get('needs_detail_fetch')]
    
    print(f"\nTotal tested: {len(results)}")
    print(f"  ✓ Successful: {len(successful)}")
    print(f"  ✗ Failed: {len(results) - len(successful)}")
    print(f"\nResults:")
    print(f"  ✓ Selectors generated: {len(with_selectors)}")
    print(f"  ✓ Events found: {len(with_events)}")
    print(f"  ⚠ Needs detail fetch: {len(needs_detail_fetch)}")
    
    # Breakdown by detected_mode
    modes = {}
    for r in successful:
        mode = r.get('detected_mode', 'unknown')
        modes[mode] = modes.get(mode, 0) + 1
    
    if modes:
        print(f"\nDetected Modes:")
        for mode, count in sorted(modes.items()):
            print(f"  {mode}: {count}")
    
    # Show sources that now have selectors
    if with_selectors:
        print(f"\n✓ Sources with generated selectors:")
        for r in with_selectors:
            print(f"  - {r['source_id']}: {r.get('events_found', 0)} events, tier {r.get('tier', '?')}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
