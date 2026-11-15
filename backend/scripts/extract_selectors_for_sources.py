#!/usr/bin/env python3
"""
Extract selectors for HTML sources that are missing them.

Tests each HTML source, tries to extract selectors, and updates sources.json with working selectors.

Usage:
    python extract_selectors_for_sources.py --dry-run
    python extract_selectors_for_sources.py --apply
"""
import sys
import json
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from collections import Counter

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.pipeline import run_source_pipeline


SOURCES_FILE = backend_dir / "sources.json"


def extract_selectors_from_html(url: str) -> Optional[Dict]:
    """Try to extract CSS selectors from an HTML page."""
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            return None
        
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for common event container patterns
        event_keywords = ['event', 'webinar', 'card', 'item', 'article', 'listing', 'entry']
        
        # Count classes
        class_counter = Counter()
        for tag in soup.find_all(class_=True):
            for cls in tag.get('class', []):
                class_counter[cls] += 1
        
        # Find potential item containers
        potential_items = []
        
        # Strategy 1: Look for article tags
        articles = soup.find_all('article', limit=10)
        if len(articles) >= 3:
            potential_items = articles
            item_selector = 'article'
        
        # Strategy 2: Look for divs with event-like classes
        if not potential_items:
            for keyword in event_keywords:
                for cls, count in class_counter.most_common(20):
                    if keyword in cls.lower() and count >= 3:
                        items = soup.select(f'.{cls}')
                        if len(items) >= 3:
                            potential_items = items[:10]
                            item_selector = f'.{cls}'
                            break
                if potential_items:
                    break
        
        # Strategy 3: Look for common card/item patterns
        if not potential_items:
            for pattern in ['.card', '.item', '.event-item', '.event-card', '.listing', '.entry']:
                items = soup.select(pattern)
                if len(items) >= 3:
                    potential_items = items[:10]
                    item_selector = pattern
                    break
        
        if not potential_items:
            return None
        
        # Extract selectors from first item
        first_item = potential_items[0]
        
        # Find title/link
        title_selector = None
        link_selector = None
        
        # Try to find heading with link
        for heading in ['h1', 'h2', 'h3', 'h4', 'h5']:
            heading_elem = first_item.find(heading)
            if heading_elem:
                link_in_heading = heading_elem.find('a', href=True)
                if link_in_heading:
                    title_selector = f'{heading} a'
                    link_selector = f'{heading} a'
                    break
                else:
                    title_selector = heading
                    # Find link nearby
                    link_elem = first_item.find('a', href=True)
                    if link_elem:
                        # Try to find relative selector
                        if link_elem.parent == heading_elem.parent:
                            link_selector = 'a[href]'
                        else:
                            link_selector = 'a[href]'
                    break
        
        # Fallback: just find first link
        if not link_selector:
            link_elem = first_item.find('a', href=True)
            if link_elem:
                link_selector = 'a[href]'
                if not title_selector:
                    title_selector = 'a[href]'
        
        # Find date selector
        date_selector = None
        date_keywords = ['date', 'time', 'when', 'datetime']
        for keyword in date_keywords:
            # Look for time tag
            time_elem = first_item.find('time')
            if time_elem:
                date_selector = 'time'
                break
            # Look for class with date keyword
            for cls in class_counter:
                if keyword in cls.lower():
                    if first_item.select(f'.{cls}'):
                        date_selector = f'.{cls}'
                        break
            if date_selector:
                break
        
        if not date_selector:
            # Common fallbacks
            for fallback in ['time', '.date', '[datetime]', '.event-date']:
                if first_item.select(fallback):
                    date_selector = fallback
                    break
        
        selectors = {
            'item_selector': item_selector
        }
        
        if title_selector:
            selectors['title_selector'] = title_selector
        if link_selector:
            selectors['link_selector'] = link_selector
        if date_selector:
            selectors['date_selector'] = date_selector
        
        return selectors
        
    except Exception as e:
        print(f"  Error extracting selectors: {e}")
        return None


def test_selectors(source: Dict, selectors: Dict) -> Dict:
    """Test if selectors work by running the pipeline."""
    test_source = source.copy()
    test_source['selectors_json'] = selectors
    
    try:
        pipeline_result = run_source_pipeline(test_source)
        kept_events = pipeline_result.get('kept_events', [])
        run_stats = pipeline_result.get('run_stats', {})
        
        return {
            'success': True,
            'events_found': len(kept_events),
            'dated_count': run_stats.get('dated_count', 0),
            'future_count': run_stats.get('future_count', 0),
            'dated_ratio': run_stats.get('dated_ratio', 0.0),
            'stats': run_stats
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'events_found': 0
        }


def main():
    parser = argparse.ArgumentParser(description='Extract selectors for HTML sources')
    parser.add_argument('--apply', action='store_true',
                       help='Update sources.json with working selectors')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Dry run mode (default)')
    parser.add_argument('--min-events', type=int, default=3,
                       help='Minimum events required to consider selectors working (default: 3)')
    
    args = parser.parse_args()
    
    if args.apply:
        args.dry_run = False
    
    # Load sources
    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)
    
    # Find HTML sources missing selectors
    html_sources = [
        s for s in sources
        if s.get('adapter_type') == 'html_list' and
        s.get('active', 0) == 0 and
        (not s.get('selectors_json') or not s.get('selectors_json').get('item_selector'))
    ]
    
    print(f"=== Extract Selectors for HTML Sources ===")
    print(f"HTML sources missing selectors: {len(html_sources)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()
    
    updated_count = 0
    working_count = 0
    
    for i, source in enumerate(html_sources, 1):
        source_id = source.get('id', '')
        firm_name = source.get('firm_name', '')
        url = source.get('url', '')
        
        print(f"{i}. {firm_name} ({source_id})")
        print(f"   URL: {url[:80]}...")
        
        # Extract selectors
        selectors = extract_selectors_from_html(url)
        
        if not selectors:
            print(f"   ✗ Could not extract selectors")
            print()
            continue
        
        print(f"   Found selectors:")
        print(f"     item_selector: {selectors.get('item_selector', 'N/A')}")
        print(f"     title_selector: {selectors.get('title_selector', 'N/A')}")
        print(f"     link_selector: {selectors.get('link_selector', 'N/A')}")
        print(f"     date_selector: {selectors.get('date_selector', 'N/A')}")
        
        # Test selectors
        test_result = test_selectors(source, selectors)
        
        if test_result['success']:
            events_found = test_result['events_found']
            future_count = test_result['future_count']
            dated_ratio = test_result['dated_ratio']
            
            print(f"   Test results: {events_found} events, {future_count} future, {dated_ratio:.1%} dated")
            
            if events_found >= args.min_events:
                print(f"   ✓ WORKING - Selectors extract {events_found} events")
                working_count += 1
                
                # Update source if --apply
                if not args.dry_run:
                    for s in sources:
                        if s.get('id') == source_id:
                            s['selectors_json'] = selectors
                            s['selector_extracted_at'] = datetime.now(timezone.utc).isoformat()
                            updated_count += 1
                            print(f"   → Updated sources.json")
                            break
            else:
                print(f"   ⚠ PARTIAL - Only {events_found} events (need {args.min_events}+)")
        else:
            print(f"   ✗ Selectors failed: {test_result.get('error', 'Unknown error')}")
        
        print()
    
    # Save if --apply
    if not args.dry_run and updated_count > 0:
        with open(SOURCES_FILE, 'w') as f:
            json.dump(sources, f, indent=2)
        print(f"✓ Updated {updated_count} sources with selectors")
        print(f"  {working_count} sources are now working")
        print(f"  Run validate_new_sources.py --activate-working to activate them")
    elif args.dry_run:
        print(f"[DRY RUN] Would update {working_count} sources with working selectors")
        print(f"Use --apply to update sources.json")
    
    print()
    print(f"Summary:")
    print(f"  Sources tested: {len(html_sources)}")
    print(f"  Selectors extracted: {sum(1 for s in html_sources if extract_selectors_from_html(s.get('url', '')))}")
    print(f"  Working selectors: {working_count}")


if __name__ == '__main__':
    main()
