#!/usr/bin/env python3
"""
Bulk discovery script for source expansion.

Discovers RSS/ICS/HTML event sources from firm_universe.json.

Usage:
    python discover_sources_bulk.py --universe backend/firm_universe.json --priority p0 --dry-run
    python discover_sources_bulk.py --universe backend/firm_universe.json --priority p0 --apply
"""
import sys
import json
import argparse
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import Counter

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.lanes import is_lane_supported


# Evidence directory
EVIDENCE_DIR = backend_dir / "_evidence" / "source_discovery"
CANDIDATES_FILE = backend_dir / "source_candidates.json"


def load_firm_universe(universe_file: Path) -> List[Dict]:
    """Load firm universe from JSON file."""
    try:
        with open(universe_file, 'r') as f:
            data = json.load(f)
            return data.get('firms', [])
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading firm universe: {e}")
        sys.exit(1)


def discover_feeds_from_url(url: str) -> List[Dict]:
    """Discover RSS/Atom/ICS feeds from a URL."""
    feeds = []
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            return feeds
        
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        base_url = response.url
        
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
                feeds.append({
                    'url': feed_url,
                    'type': feed_type,
                    'found_from': url
                })
        
        # Look for .ics links
        ics_links = soup.find_all('a', href=lambda h: h and (
            h.endswith('.ics') or 
            '/calendar' in h.lower() or 
            'text/calendar' in h.lower() or
            'webcal://' in h.lower()
        ))
        
        for link in ics_links:
            href = link.get('href')
            if href:
                if href.startswith('webcal://'):
                    ics_url = href.replace('webcal://', 'https://')
                else:
                    ics_url = urljoin(base_url, href)
                
                # Check if already found
                if not any(f['url'] == ics_url for f in feeds):
                    feeds.append({
                        'url': ics_url,
                        'type': 'ics',
                        'found_from': url
                    })
        
        # Also check for text/calendar content-type links
        calendar_links = soup.find_all('link', {
            'type': lambda t: t and 'calendar' in t.lower()
        })
        
        for link in calendar_links:
            href = link.get('href')
            if href:
                ics_url = urljoin(base_url, href)
                if not any(f['url'] == ics_url for f in feeds):
                    feeds.append({
                        'url': ics_url,
                        'type': 'ics',
                        'found_from': url
                    })
    
    except requests.RequestException:
        pass  # Skip on network errors
    except Exception:
        pass  # Skip on parsing errors
    
    return feeds


def find_events_hubs(url: str, max_depth: int = 2, max_pages: int = 20) -> List[str]:
    """Find event hub URLs by crawling from seed URL."""
    events_urls = []
    visited = set()
    to_visit = [(url, 0)]  # (url, depth)
    
    event_paths = [
        '/events', '/event', '/webinars', '/webinar',
        '/conferences', '/conference', '/calendar',
        '/insights/events', '/research/events',
        '/events-calendar', '/event-calendar'
    ]
    
    while to_visit and len(events_urls) < max_pages:
        current_url, depth = to_visit.pop(0)
        
        if current_url in visited or depth > max_depth:
            continue
        
        visited.add(current_url)
        
        try:
            response = requests.get(current_url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }, allow_redirects=True)
            
            if response.status_code != 200:
                continue
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            base_url = response.url
            
            # Check if current URL is an events page
            url_lower = current_url.lower()
            if any(path in url_lower for path in event_paths):
                events_urls.append(current_url)
            
            # Find links to event pages
            if depth < max_depth:
                for link in soup.find_all('a', href=True):
                    href = link.get('href')
                    if not href:
                        continue
                    
                    href_lower = href.lower()
                    # Check if link points to events
                    if any(path in href_lower for path in event_paths):
                        full_url = urljoin(base_url, href)
                        if full_url not in visited and full_url not in [u for u, _ in to_visit]:
                            to_visit.append((full_url, depth + 1))
        
        except requests.RequestException:
            continue
        except Exception:
            continue
    
    return events_urls[:max_pages]


def classify_candidate_url(url: str, feed_type: Optional[str] = None) -> Dict:
    """Classify a candidate URL into a lane and score it."""
    url_lower = url.lower()
    
    # Determine lane
    lane = None
    if feed_type:
        if feed_type == 'ics':
            lane = 'ics'
        elif feed_type in ['rss', 'atom']:
            lane = 'rss'
    else:
        # HTML candidate
        if any(x in url_lower for x in ['/events', '/event', '/webinar', '/conference', '/calendar']):
            lane = 'html_list'
        else:
            lane = 'html_list'  # Default for HTML
    
    # Score candidate
    score = 0
    
    # Boost event/webinar/registration patterns
    event_patterns = ['/event', '/events', '/webinar', '/webinars', '/conference', '/calendar']
    for pattern in event_patterns:
        if pattern in url_lower:
            score += 20
    
    # Boost feed types (RSS/ICS are preferred)
    if feed_type == 'ics':
        score += 30
    elif feed_type in ['rss', 'atom']:
        score += 25
    
    # Penalize generic newsletter/subscribe pages
    if any(x in url_lower for x in ['/newsletter', '/subscribe', '/signup', '/register']):
        if not any(x in url_lower for x in event_patterns):
            score -= 15
    
    # Penalize generic pages
    if url_lower.endswith('/') or url_lower.endswith('/index.html'):
        score -= 5
    
    # Check if lane is supported
    supported = is_lane_supported(lane) if lane else False
    if not supported:
        score -= 10
    
    return {
        'lane': lane,
        'score': score,
        'supported': supported
    }


def discover_firm(firm: Dict, max_per_firm: int = 20) -> Dict:
    """Discover candidates for a single firm."""
    firm_name = firm.get('firm_name', '')
    home_url = firm.get('home_url', '')
    seed_urls = firm.get('seed_urls', [])
    
    print(f"\n=== Discovering: {firm_name} ===")
    print(f"Home URL: {home_url}")
    
    candidates = []
    
    # Start from home_url and seed_urls
    urls_to_check = [home_url] + seed_urls
    
    # Discover feeds
    feeds_found = []
    for url in urls_to_check:
        feeds = discover_feeds_from_url(url)
        feeds_found.extend(feeds)
        print(f"  Found {len(feeds)} feeds from {url}")
    
    # Convert feeds to candidates
    for feed in feeds_found:
        classification = classify_candidate_url(feed['url'], feed['type'])
        candidates.append({
            'url': feed['url'],
            'lane': classification['lane'],
            'score': classification['score'],
            'supported': classification['supported'],
            'type': 'feed',
            'feed_type': feed['type'],
            'found_from': feed['found_from']
        })
    
    # Find events hubs (HTML candidates)
    events_hubs = []
    for url in urls_to_check:
        hubs = find_events_hubs(url, max_depth=1, max_pages=5)
        events_hubs.extend(hubs)
        print(f"  Found {len(hubs)} event hubs from {url}")
    
    # Convert events hubs to candidates
    for hub_url in events_hubs:
        classification = classify_candidate_url(hub_url)
        candidates.append({
            'url': hub_url,
            'lane': classification['lane'],
            'score': classification['score'],
            'supported': classification['supported'],
            'type': 'html_list',
            'found_from': home_url
        })
    
    # Sort by score (highest first)
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    # Limit per firm
    candidates = candidates[:max_per_firm]
    
    print(f"  Total candidates: {len(candidates)}")
    if candidates:
        print(f"  Top candidate: {candidates[0]['url']} (score: {candidates[0]['score']}, lane: {candidates[0]['lane']})")
    
    # Save evidence
    evidence_path = EVIDENCE_DIR / firm_name.lower().replace(' ', '_') / datetime.now(timezone.utc).isoformat()
    evidence_path.mkdir(parents=True, exist_ok=True)
    
    evidence_file = evidence_path / "discovery.json"
    with open(evidence_file, 'w') as f:
        json.dump({
            'firm_name': firm_name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'candidates': candidates,
            'feeds_found': feeds_found,
            'events_hubs': events_hubs
        }, f, indent=2)
    
    return {
        'firm_name': firm_name,
        'firm_type': firm.get('firm_type', ''),
        'candidates': candidates,
        'evidence_path': str(evidence_file)
    }


def main():
    parser = argparse.ArgumentParser(description='Bulk discovery of event sources')
    parser.add_argument('--universe', default='backend/firm_universe.json',
                       help='Path to firm_universe.json')
    parser.add_argument('--priority', choices=['p0', 'p1', 'p2', 'all'], default='p0',
                       help='Priority filter')
    parser.add_argument('--apply', action='store_true',
                       help='Write results to source_candidates.json (default: dry-run)')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Dry run mode (default)')
    parser.add_argument('--max-per-firm', type=int, default=20,
                       help='Max candidates per firm')
    
    args = parser.parse_args()
    
    # Override dry-run if --apply is set
    if args.apply:
        args.dry_run = False
    
    # Load firm universe
    universe_file = Path(args.universe)
    if not universe_file.is_absolute():
        universe_file = backend_dir.parent / universe_file
    
    firms = load_firm_universe(universe_file)
    
    # Filter by priority
    if args.priority != 'all':
        firms = [f for f in firms if f.get('priority') == args.priority]
    
    print(f"=== Bulk Discovery ===")
    print(f"Universe file: {universe_file}")
    print(f"Priority: {args.priority}")
    print(f"Firms to process: {len(firms)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()
    
    # Discover for each firm
    results = []
    for firm in firms:
        try:
            result = discover_firm(firm, max_per_firm=args.max_per_firm)
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Summary
    total_candidates = sum(len(r['candidates']) for r in results)
    firms_with_candidates = sum(1 for r in results if r['candidates'])
    
    print(f"\n=== Summary ===")
    print(f"Firms processed: {len(results)}")
    print(f"Firms with candidates: {firms_with_candidates} ({firms_with_candidates/len(results)*100:.1f}%)")
    print(f"Total candidates: {total_candidates}")
    
    # Group by lane
    lane_counts = Counter()
    for result in results:
        for candidate in result['candidates']:
            lane_counts[candidate['lane']] += 1
    
    print(f"\nCandidates by lane:")
    for lane, count in lane_counts.most_common():
        print(f"  {lane}: {count}")
    
    # Write results if --apply
    if not args.dry_run:
        output = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'priority': args.priority,
            'firms': results
        }
        
        with open(CANDIDATES_FILE, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"\nResults written to: {CANDIDATES_FILE}")
    else:
        print(f"\n[DRY RUN] Results would be written to: {CANDIDATES_FILE}")
        print(f"Use --apply to write results")
    
    # Acceptance criteria check
    if firms_with_candidates / len(results) >= 0.70:
        print(f"\n✓ Acceptance criteria met: {firms_with_candidates/len(results)*100:.1f}% of firms have candidates")
    else:
        print(f"\n⚠ Acceptance criteria not met: {firms_with_candidates/len(results)*100:.1f}% of firms have candidates (target: 70%)")


if __name__ == '__main__':
    main()
