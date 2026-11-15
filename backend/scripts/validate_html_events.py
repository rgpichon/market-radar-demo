#!/usr/bin/env python3
"""
Validate HTML page for event scraping potential.
Detects JS-rendered patterns and estimates scrape-friendliness.

Usage:
    python validate_html_events.py <url>
"""
import sys
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from collections import Counter

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


def validate_html_events(url):
    """Validate HTML page for event scraping."""
    print(f"\n=== Validating HTML page: {url} ===\n")
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        print(f"HTTP Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        print(f"Content Length: {len(response.text)} bytes")
        print(f"Final URL: {response.url}\n")
        
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code}")
            sys.exit(1)
        
        html = response.text
        html_lower = html.lower()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Check for JS-rendered patterns
        js_indicators = [
            'enable javascript',
            'javascript required',
            'please enable javascript',
            'react-root',
            'ng-app',
            'data-reactroot',
            '__next',
            'vue-app',
            'angular'
        ]
        
        js_detected = []
        for indicator in js_indicators:
            if indicator in html_lower:
                js_detected.append(indicator)
        
        # Check HTML length (very short = likely JS-rendered)
        html_length = len(html)
        is_very_short = html_length < 5000
        
        # Count script tags
        script_tags = soup.find_all('script')
        script_count = len(script_tags)
        
        # Count links
        links = soup.find_all('a', href=True)
        link_count = len(links)
        
        # Count potential event containers
        event_keywords = ['event', 'webinar', 'card', 'item', 'article', 'listing', 'entry']
        event_containers = []
        
        for keyword in event_keywords:
            # Find elements with class containing keyword
            for tag in soup.find_all(class_=lambda c: c and keyword in ' '.join(c).lower()):
                classes = ' '.join(tag.get('class', []))
                if keyword in classes.lower():
                    event_containers.append((tag.name, classes))
        
        # Count unique event-like classes
        class_counter = Counter()
        for tag in soup.find_all(class_=True):
            for cls in tag.get('class', []):
                if any(kw in cls.lower() for kw in event_keywords):
                    class_counter[cls] += 1
        
        # Print results
        print("=== JS Rendering Check ===")
        if js_detected:
            print(f"⚠️  JS indicators found: {', '.join(js_detected)}")
            print("   Likely Tier C (JS-rendered)")
        else:
            print("✓ No obvious JS-rendering indicators")
        
        print(f"\n=== Page Structure ===")
        print(f"HTML length: {html_length:,} bytes")
        if is_very_short:
            print("⚠️  Very short HTML (likely JS-rendered app shell)")
        print(f"Script tags: {script_count}")
        print(f"Links: {link_count}")
        print(f"Potential event containers: {len(event_containers)}")
        print(f"Event-like CSS classes: {len(class_counter)}")
        
        if class_counter:
            print(f"\nTop 10 event-like classes:")
            for cls, count in class_counter.most_common(10):
                print(f"  .{cls}: {count} occurrences")
        
        # Tier assessment
        print(f"\n=== Tier Assessment ===")
        if js_detected or is_very_short:
            tier = "C"
            reason = "JS-rendered or app shell detected"
        elif len(event_containers) >= 5 and link_count >= 10:
            tier = "A"
            reason = "Good structure, many event-like containers"
        elif len(event_containers) >= 2:
            tier = "B"
            reason = "Some event-like structure found"
        else:
            tier = "C"
            reason = "No clear event structure"
        
        print(f"Tier: {tier}")
        print(f"Reason: {reason}")
        
        if tier == "A":
            print("✓ Good candidate for HTML scraping")
        elif tier == "B":
            print("⚠️  May require careful selector tuning")
        else:
            print("⚠️  Likely requires Playwright/Selenium or different approach")
        
    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_html_events.py <url>")
        sys.exit(1)
    
    url = sys.argv[1]
    validate_html_events(url)


if __name__ == '__main__':
    main()
