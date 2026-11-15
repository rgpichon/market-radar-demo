#!/usr/bin/env python3
"""
Validate a feed URL (RSS/Atom/ICS).
Parses the feed and shows sample items.

Usage:
    python validate_feed.py <feed_url> [rss|ics|auto]
"""
import sys
import requests
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Import adapters
from adapters.rss_feed import extract_events as extract_rss
from adapters.ics_calendar import extract_events as extract_ics


def validate_feed(feed_url, feed_type='auto'):
    """Validate a feed URL."""
    print(f"\n=== Validating feed: {feed_url} ===\n")
    
    # Auto-detect type from URL
    if feed_type == 'auto':
        if feed_url.endswith('.ics') or '/calendar' in feed_url.lower():
            feed_type = 'ics'
        elif 'rss' in feed_url.lower() or 'atom' in feed_url.lower() or 'feed' in feed_url.lower():
            feed_type = 'rss'
        else:
            # Try RSS first
            feed_type = 'rss'
    
    # Fetch and show HTTP info
    try:
        response = requests.get(feed_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        print(f"HTTP Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        print(f"Content Length: {len(response.text)} bytes")
        print(f"First 200 chars: {response.text[:200].replace(chr(10), ' ').replace(chr(13), ' ')}")
        print()
        
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code}")
            sys.exit(1)
        
    except requests.RequestException as e:
        print(f"Error fetching feed: {e}")
        sys.exit(1)
    
    # Parse feed
    source_config = {
        'firm_name': 'Test Source',
        'default_tags_json': [],
        'enforce_events_only': False  # Don't filter for validation
    }
    
    try:
        if feed_type == 'ics':
            events, stats = extract_ics(feed_url, source_config, return_stats=True)
        else:  # rss/atom
            events, stats = extract_rss(feed_url, source_config, return_stats=True)
        
        print(f"=== Parse Results ===")
        print(f"Feed Type: {feed_type.upper()}")
        print(f"Raw items: {stats.get('raw', 0)}")
        print(f"Kept items: {stats.get('kept', len(events))}")
        
        if stats.get('rejected'):
            print(f"Rejected: {sum(stats['rejected'].values())}")
            for reason, count in stats['rejected'].items():
                print(f"  - {reason}: {count}")
        
        print(f"\n=== Sample Items (first 3) ===")
        if len(events) == 0:
            print("No items found!")
            sys.exit(1)
        
        for i, event in enumerate(events[:3], 1):
            print(f"\n{i}. {event.get('event_name', 'N/A')}")
            print(f"   Link: {event.get('link', 'N/A')}")
            if event.get('date_time'):
                print(f"   Date: {event['date_time']}")
            else:
                print(f"   Date: (not available)")
        
        if len(events) < 5:
            print(f"\n⚠️  Warning: Only {len(events)} items found (recommend >= 5)")
        else:
            print(f"\n✓ Feed validated: {len(events)} items found")
        
        # Count items with dates
        dated_count = sum(1 for e in events if e.get('date_time'))
        dated_ratio = dated_count / len(events) if events else 0
        print(f"   Items with dates: {dated_count}/{len(events)} ({dated_ratio:.1%})")
        
        if dated_ratio < 0.5:
            print(f"⚠️  Warning: Low date coverage ({dated_ratio:.1%})")
        
        sys.exit(0)
        
    except Exception as e:
        print(f"\nError parsing feed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_feed.py <feed_url> [rss|ics|auto]")
        sys.exit(1)
    
    feed_url = sys.argv[1]
    feed_type = sys.argv[2] if len(sys.argv) > 2 else 'auto'
    
    if feed_type not in ['rss', 'ics', 'auto']:
        print(f"Error: feed_type must be 'rss', 'ics', or 'auto'")
        sys.exit(1)
    
    validate_feed(feed_url, feed_type)


if __name__ == '__main__':
    main()
