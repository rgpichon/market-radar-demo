#!/usr/bin/env python3
"""
Source onboarding and testing tool.
Usage: 
    python test_source.py --source <source_id> [N]
    python test_source.py --source <source_id> --print-selectors-hints
    python test_source.py --source <source_id> --dump-snippet
    python test_source.py --url <url> --adapter <html_list|json_ld> [--selectors <json>]
"""
import sys
import json
import argparse
import requests
from pathlib import Path
from collections import Counter

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from db import get_sources, get_db, init_db
from scrape_runner import scrape_source, load_preferences, load_packs
from adapters.html_list import extract_events as extract_html_list
from adapters.json_ld import extract_events as extract_json_ld
from utils.json_utils import ensure_dict, ensure_list
from bs4 import BeautifulSoup


def sanitize_html(html, max_length=2000):
    """Sanitize HTML snippet for display."""
    # Remove scripts and styles
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup(['script', 'style']):
        script.decompose()
    
    text = str(soup)
    if len(text) > max_length:
        text = text[:max_length] + "..."
    return text


def print_selectors_hints(url):
    """Fetch page and print hints for deriving CSS selectors."""
    print(f"\n=== Selector Hints for {url} ===\n")
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        response.raise_for_status()
        html = response.text
        final_url = response.url
        
        soup = BeautifulSoup(html, 'html.parser')
        
        print(f"Response Status: {response.status_code}")
        print(f"Final URL: {final_url}")
        print(f"Content Length: {len(html)} bytes")
        
        # Page title
        title = soup.find('title')
        print(f"\nPage Title: {title.get_text().strip() if title else '(none)'}")
        
        # First h1
        h1 = soup.find('h1')
        print(f"First H1: {h1.get_text().strip()[:100] if h1 else '(none)'}")
        
        # Count links
        links = soup.find_all('a', href=True)
        print(f"Total <a href> links: {len(links)}")
        
        # Top 15 most common class names
        class_counter = Counter()
        for tag in soup.find_all(class_=True):
            for cls in tag.get('class', []):
                class_counter[cls] += 1
        
        print(f"\nTop 15 most common CSS classes:")
        for cls, count in class_counter.most_common(15):
            print(f"  .{cls}: {count} occurrences")
        
        # Look for common event-related patterns
        print(f"\n=== Potential Event Containers ===")
        event_keywords = ['event', 'webinar', 'card', 'item', 'article', 'listing', 'entry']
        found_patterns = []
        
        for keyword in event_keywords:
            for cls, count in class_counter.items():
                if keyword in cls.lower() and count >= 2:
                    found_patterns.append((cls, count))
        
        # Sort by count descending
        found_patterns.sort(key=lambda x: -x[1])
        
        if found_patterns:
            for cls, count in found_patterns[:10]:
                print(f"  .{cls}: {count} occurrences")
        else:
            print("  (no obvious event-like class patterns found)")
        
        # Show sample structure
        print(f"\n=== Sample Article/Card Structure ===")
        sample_containers = soup.find_all(['article', 'div'], class_=True, limit=20)
        shown = 0
        for container in sample_containers:
            classes = ' '.join(container.get('class', []))
            if any(kw in classes.lower() for kw in ['card', 'event', 'item', 'article', 'listing']):
                # Get inner structure
                inner_tags = [child.name for child in container.find_all(recursive=False) if child.name]
                links_in = len(container.find_all('a', href=True))
                text_preview = container.get_text()[:80].replace('\n', ' ').strip()
                print(f"\n  <{container.name} class=\"{classes[:60]}...\">")
                print(f"    Inner tags: {inner_tags[:5]}")
                print(f"    Links: {links_in}")
                print(f"    Text preview: {text_preview}...")
                shown += 1
                if shown >= 3:
                    break
        
        if shown == 0:
            print("  (no card/article containers found)")
        
        # Check for JS-rendered
        html_lower = html.lower()
        js_indicators = ['enable javascript', 'javascript required', 'please enable javascript', 
                        'react-root', 'ng-app', 'data-reactroot']
        if any(indicator in html_lower for indicator in js_indicators):
            print(f"\n⚠️  WARNING: Page may be JS-rendered (found JS indicators)")
            print("   Consider finding a different URL or using a different approach")
        
    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
    except Exception as e:
        print(f"Error analyzing page: {e}")


def dump_snippet(url, item_selector):
    """Print HTML snippet around first matched item."""
    print(f"\n=== HTML Snippet (first match for '{item_selector}') ===\n")
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        response.raise_for_status()
        html = response.text
        
        soup = BeautifulSoup(html, 'html.parser')
        items = soup.select(item_selector)
        
        if not items:
            print(f"No items found for selector: {item_selector}")
            return
        
        first_item = items[0]
        snippet = sanitize_html(str(first_item), max_length=2000)
        print(snippet)
        
    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
    except Exception as e:
        print(f"Error: {e}")


def test_url(url, adapter_type, selectors_json=None):
    """Test an arbitrary URL with given adapter and selectors."""
    print(f"\n=== Testing URL: {url} ===")
    print(f"Adapter: {adapter_type}\n")
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        print(f"Response Status: {response.status_code}")
        print(f"Final URL: {response.url}")
        print(f"Content Length: {len(response.text)} bytes")
        
        response.raise_for_status()
        html = response.text
        
        # Build source config
        source_config = {
            'firm_name': 'Test Source',
            'url': response.url,
            'adapter_type': adapter_type,
            'selectors_json': selectors_json if selectors_json else {},
            'default_tags_json': []
        }
        
        # Extract events
        if adapter_type == 'json_ld':
            events = extract_json_ld(html, source_config)
            print(f"\nJSON-LD Scripts Found: {len(BeautifulSoup(html, 'html.parser').find_all('script', type='application/ld+json'))}")
        elif adapter_type == 'html_list':
            events = extract_html_list(html, source_config)
            if selectors_json:
                selectors = ensure_dict(selectors_json)
                item_selector = selectors.get('item_selector')
                if item_selector:
                    soup = BeautifulSoup(html, 'html.parser')
                    matched = soup.select(item_selector)
                    print(f"\nItems Matched by item_selector: {len(matched)}")
        else:
            print(f"Unknown adapter type: {adapter_type}")
            return
        
        print(f"Events Extracted: {len(events)}\n")
        
        # Show first 5 events
        for i, event in enumerate(events[:5], 1):
            print(f"{i}. {event['event_name']}")
            if event.get('date_time'):
                print(f"   Date: {event['date_time']}")
            print(f"   Link: {event['link']}")
            print()
        
        if len(events) > 5:
            print(f"... and {len(events) - 5} more events")
        
        # Check for JS-rendered
        if len(events) == 0 and len(html) > 10000:
            html_lower = html.lower()
            js_indicators = ['enable javascript', 'javascript required', 'react-root', 'ng-app']
            if any(indicator in html_lower for indicator in js_indicators):
                print("\n⚠️  WARNING: Likely JS-rendered page.")
                print("   Large HTML but no events extracted. Consider finding a different URL.")
        
    except requests.RequestException as e:
        print(f"\nRequest Error: {e}")
    except Exception as e:
        print(f"\nError: {e}")


def main():
    parser = argparse.ArgumentParser(description='Test and onboard sources')
    parser.add_argument('--source', help='ID of the source to test')
    parser.add_argument('--url', help='Test arbitrary URL (requires --adapter)')
    parser.add_argument('--adapter', choices=['html_list', 'json_ld'], 
                       help='Adapter type (required with --url)')
    parser.add_argument('--selectors', help='JSON string for selectors (html_list only)')
    parser.add_argument('n_items', nargs='?', type=int, default=5, 
                       help='Number of items to print (default: 5)')
    parser.add_argument('--print-selectors-hints', action='store_true',
                       help='Print hints for deriving CSS selectors')
    parser.add_argument('--dump-snippet', action='store_true',
                       help='Print HTML snippet of first matched item')
    
    args = parser.parse_args()
    
    # Test arbitrary URL
    if args.url:
        if not args.adapter:
            print("Error: --adapter is required when using --url")
            sys.exit(1)
        
        selectors_json = None
        if args.selectors:
            try:
                selectors_json = json.loads(args.selectors)
            except json.JSONDecodeError:
                print("Error: --selectors must be valid JSON")
                sys.exit(1)
        
        test_url(args.url, args.adapter, selectors_json)
        return
    
    # Test source from DB
    if not args.source:
        print("Error: Either --source or --url must be provided")
        parser.print_help()
        sys.exit(1)
    
    # Initialize DB to ensure sources are synced
    init_db()
    
    sources = get_sources(active_only=False)
    source = None
    for s in sources:
        if s['id'] == args.source:
            source = s
            break
    
    if not source:
        print(f"Source '{args.source}' not found.")
        print("\nAvailable sources:")
        for s in sources:
            status = "active" if s.get('active') else "inactive"
            print(f"  - {s['id']} ({s['firm_name']}) [{status}]")
        sys.exit(1)
    
    print(f"Testing source: {source['firm_name']} ({args.source})")
    print(f"URL: {source['url']}")
    print(f"Adapter: {source['adapter_type']}")
    
    # Print selector hints if requested
    if args.print_selectors_hints:
        print_selectors_hints(source['url'])
        return
    
    # Dump snippet if requested
    if args.dump_snippet:
        selectors = ensure_dict(source.get('selectors_json'))
        item_selector = selectors.get('item_selector')
        if not item_selector:
            print("Error: No item_selector found in source config")
            sys.exit(1)
        dump_snippet(source['url'], item_selector)
        return
    
    print("\nRunning scrape...")
    
    # Load preferences and packs
    preferences = load_preferences()
    packs = load_packs()
    
    events_found, inserted, updated, notifications, error, diagnostics = scrape_source(
        source, preferences, packs
    )
    
    print(f"\n=== Results ===")
    if error:
        print(f"Error: {error}")
    
    # Show extraction stats if available
    if diagnostics and 'extraction_stats' in diagnostics:
        stats = diagnostics['extraction_stats']
        raw = stats.get('raw', events_found)
        kept = stats.get('kept', events_found)
        print(f"Raw items matched: {raw}")
        print(f"Kept after filtering: {kept}")
        if stats.get('rejected'):
            print(f"Rejection reasons:")
            for reason, count in sorted(stats['rejected'].items(), key=lambda x: -x[1]):
                print(f"  - {reason}: {count}")
    else:
        print(f"Events found: {events_found}")
    
    print(f"Inserted: {inserted}")
    print(f"Updated: {updated}")
    print(f"Notifications: {notifications}")
    
    # Show diagnostics if 0 events
    if events_found == 0 and diagnostics:
        print(f"\n=== Diagnostics ===")
        print(f"Adapter: {diagnostics.get('adapter_type')}")
        if 'status_code' in diagnostics:
            print(f"Status Code: {diagnostics.get('status_code')}")
        print(f"Has item_selector: {diagnostics.get('has_item_selector')}")
        print(f"Has title_selector: {diagnostics.get('has_title_selector')}")
        if diagnostics.get('item_selector'):
            print(f"Item selector: {diagnostics.get('item_selector')}")
        print(f"HTML length: {diagnostics.get('html_length')} bytes")
        if diagnostics.get('is_js_rendered'):
            print("⚠️  Likely JS-rendered page")
        print(f"\nTip: Run with --print-selectors-hints to analyze the page structure")
        print(f"Tip: Run with --dump-snippet to see HTML of first matched item")
    
    # Note: Extracted events are not returned from scrape_source, only counts
    # To see extracted events, check the database output below
    
    # Fetch and display first N events from DB
    if inserted > 0 or updated > 0:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT firm_name, event_name, date_time, link 
            FROM events 
            WHERE source_id = ? 
            ORDER BY last_seen DESC 
            LIMIT ?
        """, (args.source, args.n_items))
        
        rows = cursor.fetchall()
        if rows:
            print(f"\n=== First {args.n_items} Events from Database ===")
            for row in rows:
                print(f"  - {row['firm_name']}: {row['event_name']}")
                if row['date_time']:
                    print(f"    Date: {row['date_time']}")
                print(f"    Link: {row['link']}")
        
        conn.close()


if __name__ == '__main__':
    main()
