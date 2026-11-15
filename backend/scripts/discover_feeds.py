#!/usr/bin/env python3
"""
Discover RSS/Atom/ICS feeds from a URL.
Looks for feed discovery tags and .ics links in HTML.

Usage:
    python discover_feeds.py <url>
"""
import sys
import json
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

CANDIDATES_FILE = backend_dir / "feed_candidates.json"


def load_candidates():
    """Load existing candidates from JSON file."""
    if CANDIDATES_FILE.exists():
        try:
            with open(CANDIDATES_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_candidate(found_from_url, feed_url, type_guess):
    """Save a discovered feed candidate to JSON file."""
    candidates = load_candidates()
    
    # Check if already exists
    for cand in candidates:
        if cand.get('feed_url') == feed_url:
            return  # Already exists
    
    candidate = {
        'found_from_url': found_from_url,
        'feed_url': feed_url,
        'type_guess': type_guess,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    candidates.append(candidate)
    
    try:
        with open(CANDIDATES_FILE, 'w') as f:
            json.dump(candidates, f, indent=2)
    except IOError as e:
        print(f"Warning: Could not save candidate: {e}")


def discover_feeds(url):
    """Discover feeds from a URL."""
    print(f"\n=== Discovering feeds from: {url} ===\n")
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        print(f"HTTP Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        print(f"Final URL: {response.url}\n")
        
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code}")
            return
        
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        base_url = response.url
        
        feeds_found = []
        
        # Look for RSS/Atom discovery tags
        feed_links = soup.find_all('link', {
            'rel': lambda r: r and ('alternate' in r or 'feed' in r),
            'type': lambda t: t and ('rss' in t.lower() or 'atom' in t.lower() or 'xml' in t.lower())
        })
        
        for link in feed_links:
            href = link.get('href')
            if href:
                feed_url = urljoin(base_url, href)
                feed_type = 'rss' if 'rss' in link.get('type', '').lower() else 'atom'
                feeds_found.append((feed_url, feed_type))
                print(f"Found {feed_type.upper()} feed: {feed_url}")
        
        # Look for .ics links
        ics_links = soup.find_all('a', href=lambda h: h and (h.endswith('.ics') or '/calendar' in h.lower() or 'text/calendar' in h.lower()))
        
        for link in ics_links:
            href = link.get('href')
            if href:
                ics_url = urljoin(base_url, href)
                # Check if already found
                if not any(f[0] == ics_url for f in feeds_found):
                    feeds_found.append((ics_url, 'ics'))
                    print(f"Found ICS calendar: {ics_url}")
        
        # Also check for text/calendar content-type links
        calendar_links = soup.find_all('link', {
            'type': lambda t: t and 'calendar' in t.lower()
        })
        
        for link in calendar_links:
            href = link.get('href')
            if href:
                ics_url = urljoin(base_url, href)
                if not any(f[0] == ics_url for f in feeds_found):
                    feeds_found.append((ics_url, 'ics'))
                    print(f"Found ICS calendar (via link type): {ics_url}")
        
        if not feeds_found:
            print("No feeds discovered.")
        else:
            print(f"\n=== Summary: {len(feeds_found)} feed(s) discovered ===")
            for feed_url, feed_type in feeds_found:
                save_candidate(url, feed_url, feed_type)
                print(f"  Saved: {feed_type} -> {feed_url}")
        
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
        print("Usage: python discover_feeds.py <url>")
        sys.exit(1)
    
    url = sys.argv[1]
    discover_feeds(url)


if __name__ == '__main__':
    main()
