#!/usr/bin/env python3
"""
Systematically discover and classify all bulge bracket firms.

Runs discovery using existing toolkit scripts and updates bulge_brackets.json
with structured, decision-grade documentation.
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

BULGE_BRACKETS_FILE = backend_dir / "bulge_brackets.json"


def load_bulge_brackets() -> List[Dict]:
    """Load bulge_brackets.json."""
    if not BULGE_BRACKETS_FILE.exists():
        return []
    
    try:
        with open(BULGE_BRACKETS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading bulge_brackets.json: {e}")
        return []


def save_bulge_brackets(entries: List[Dict]):
    """Save bulge_brackets.json."""
    try:
        with open(BULGE_BRACKETS_FILE, 'w') as f:
            json.dump(entries, f, indent=2)
        print(f"✓ Updated {BULGE_BRACKETS_FILE}")
    except IOError as e:
        print(f"Error saving bulge_brackets.json: {e}")
        sys.exit(1)


def run_discover_feeds(url: str) -> tuple[bool, List[str], str]:
    """Run discover_feeds.py and extract feed URLs."""
    try:
        result = subprocess.run(
            [sys.executable, str(backend_dir / "scripts" / "discover_feeds.py"), url],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        feeds = []
        if result.returncode == 0:
            # Parse output for feed URLs
            for line in result.stdout.split('\n'):
                if 'Found' in line and ('RSS' in line or 'ICS' in line or 'feed' in line):
                    # Extract URL
                    if 'http' in line:
                        parts = line.split('http')
                        if len(parts) > 1:
                            feed_url = 'http' + parts[1].strip()
                            # Clean up any trailing characters
                            feed_url = feed_url.split()[0] if ' ' in feed_url else feed_url
                            feeds.append(feed_url)
        
        return result.returncode == 0, feeds, result.stderr
    except subprocess.TimeoutExpired:
        return False, [], "Timeout"
    except Exception as e:
        return False, [], str(e)


def run_validate_html(url: str) -> tuple[bool, Dict, str]:
    """Run validate_html_events.py and parse results."""
    try:
        result = subprocess.run(
            [sys.executable, str(backend_dir / "scripts" / "validate_html_events.py"), url],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        html_info = {
            'html_feasible': False,
            'js_rendered': False,
            'tier': 'C',
            'status_code': None
        }
        
        if result.returncode == 0:
            output_lower = result.stdout.lower()
            
            # Check for tier
            if 'tier: a' in output_lower:
                html_info['tier'] = 'A'
                html_info['html_feasible'] = True
            elif 'tier: b' in output_lower:
                html_info['tier'] = 'B'
                html_info['html_feasible'] = True
            elif 'tier: c' in output_lower:
                html_info['tier'] = 'C'
            
            # Check for JS-rendered
            if 'js-rendered' in output_lower or 'js rendered' in output_lower:
                html_info['js_rendered'] = True
            
            # Check status code
            if 'http status:' in output_lower:
                for line in result.stdout.split('\n'):
                    if 'http status:' in line.lower():
                        try:
                            status = int(line.split(':')[1].strip().split()[0])
                            html_info['status_code'] = status
                        except:
                            pass
        
        return result.returncode == 0, html_info, result.stderr
    except subprocess.TimeoutExpired:
        return False, {}, "Timeout"
    except Exception as e:
        return False, {}, str(e)


def discover_firm(firm_name: str, entry_points: List[str]) -> Dict:
    """Discover and classify a single firm."""
    print(f"\n{'='*60}")
    print(f"Discovering: {firm_name}")
    print(f"{'='*60}\n")
    
    discovery_results = {
        'feeds_found': [],
        'html_feasible': False,
        'js_rendered': False,
        'gated': False,
        'entry_points_tested': [],
        'errors': []
    }
    
    # Test each entry point
    for url in entry_points:
        print(f"Testing: {url}")
        discovery_results['entry_points_tested'].append(url)
        
        # Discover feeds
        feeds_success, feeds, feeds_error = run_discover_feeds(url)
        if feeds_success and feeds:
            for feed_url in feeds:
                feed_type = 'rss' if 'rss' in feed_url.lower() else 'ics' if 'ics' in feed_url.lower() else 'unknown'
                discovery_results['feeds_found'].append({
                    'url': feed_url,
                    'type': feed_type,
                    'found_from': url
                })
                print(f"  ✓ Found {feed_type.upper()} feed: {feed_url}")
        elif not feeds_success:
            discovery_results['errors'].append(f"Feed discovery failed for {url}: {feeds_error}")
        
        # Validate HTML (only if no feeds found)
        if not discovery_results['feeds_found']:
            html_success, html_info, html_error = run_validate_html(url)
            if html_success:
                if html_info.get('html_feasible'):
                    discovery_results['html_feasible'] = True
                    print(f"  ✓ HTML feasible (Tier {html_info['tier']})")
                if html_info.get('js_rendered'):
                    discovery_results['js_rendered'] = True
                    print(f"  ⚠️  JS-rendered detected")
                
                # Check for gated (403/401 status codes)
                status = html_info.get('status_code')
                if status in [401, 403]:
                    discovery_results['gated'] = True
                    print(f"  ⚠️  Gated content (HTTP {status})")
            elif not html_success:
                discovery_results['errors'].append(f"HTML validation failed for {url}: {html_error}")
    
    # Determine lane and status
    from utils.lanes import is_lane_supported
    
    lane_candidate = None
    acquisition_status = None
    notes = []
    
    if discovery_results['feeds_found']:
        feed_types = [f.get('type', '') for f in discovery_results['feeds_found']]
        if 'ics' in feed_types:
            lane_candidate = 'ics'
        elif 'rss' in feed_types:
            lane_candidate = 'rss'
        
        if lane_candidate and is_lane_supported(lane_candidate):
            acquisition_status = 'ready'
            notes.append(f"Feed discovered: {lane_candidate}")
        else:
            acquisition_status = 'deferred'
            notes.append(f"Feed found but lane '{lane_candidate}' not supported")
    
    elif discovery_results['html_feasible'] and not discovery_results['js_rendered']:
        lane_candidate = 'html_simple'
        if is_lane_supported(lane_candidate):
            acquisition_status = 'ready'
            notes.append("HTML page is scrape-friendly")
        else:
            acquisition_status = 'deferred'
            notes.append("HTML feasible but not supported")
    
    elif discovery_results['js_rendered']:
        lane_candidate = 'js_rendered'
        acquisition_status = 'deferred_js'
        notes.append("JS-rendered page, requires Playwright")
    
    elif discovery_results['gated']:
        lane_candidate = 'gated'
        acquisition_status = 'deferred_gated'
        notes.append("Content is gated/requires authentication")
    
    else:
        lane_candidate = 'js_rendered'  # Conservative default
        acquisition_status = 'dead_end'
        notes.append("Unable to determine feasible acquisition method")
        if discovery_results['errors']:
            notes.append(f"Errors: {len(discovery_results['errors'])}")
    
    result = {
        'firm_name': firm_name,
        'discovery_results': discovery_results,
        'lane_candidate': lane_candidate,
        'acquisition_status': acquisition_status,
        'notes': '; '.join(notes),
        'last_discovered': datetime.now(timezone.utc).isoformat()
    }
    
    print(f"\nResult: {acquisition_status} ({lane_candidate})")
    print(f"Notes: {result['notes']}")
    
    return result


def main():
    """Discover all bulge bracket firms."""
    print("="*60)
    print("BULGE BRACKET DISCOVERY")
    print("="*60)
    
    # Load existing entries
    entries = load_bulge_brackets()
    
    # Define firms to discover
    firms = [
        {
            'firm_name': 'Goldman Sachs',
            'entry_points': [
                'https://www.goldmansachs.com',
                'https://www.goldmansachs.com/insights/events',
                'https://www.goldmansachs.com/insights'
            ]
        },
        {
            'firm_name': 'JPMorgan',
            'entry_points': [
                'https://www.jpmorgan.com',
                'https://www.jpmorgan.com/insights/events',
                'https://www.jpmorgan.com/insights'
            ]
        },
        {
            'firm_name': 'Morgan Stanley',
            'entry_points': [
                'https://www.morganstanley.com',
                'https://www.morganstanley.com/ideas/events',
                'https://www.morganstanley.com/ideas'
            ]
        },
        {
            'firm_name': 'Citigroup',
            'entry_points': [
                'https://www.citigroup.com',
                'https://www.citigroup.com/citi/news',
                'https://www.citigroup.com/citi'
            ]
        },
        {
            'firm_name': 'Bank of America',
            'entry_points': [
                'https://about.bankofamerica.com',
                'https://newsroom.bankofamerica.com',
                'https://about.bankofamerica.com/en/newsroom'
            ]
        },
        {
            'firm_name': 'Barclays',
            'entry_points': [
                'https://www.barclays.com',
                'https://www.barclays.com/insights',
                'https://www.barclays.com/about-barclays/news-and-events'
            ]
        },
        {
            'firm_name': 'Deutsche Bank',
            'entry_points': [
                'https://www.db.com',
                'https://www.db.com/news',
                'https://www.db.com/news/events'
            ]
        },
        {
            'firm_name': 'UBS',
            'entry_points': [
                'https://www.ubs.com',
                'https://www.ubs.com/global/en/about_ubs/news_center.html',
                'https://www.ubs.com/global/en/about_ubs'
            ]
        },
        {
            'firm_name': 'BNP Paribas',
            'entry_points': [
                'https://group.bnpparibas',
                'https://group.bnpparibas/en/news',
                'https://group.bnpparibas/en'
            ]
        },
        {
            'firm_name': 'Société Générale',
            'entry_points': [
                'https://www.societegenerale.com',
                'https://www.societegenerale.com/en/news',
                'https://www.societegenerale.com/en'
            ]
        }
    ]
    
    # Discover each firm
    for firm_info in firms:
        firm_name = firm_info['firm_name']
        entry_points = firm_info['entry_points']
        
        # Find existing entry or create new
        existing_entry = None
        for i, entry in enumerate(entries):
            if entry.get('firm_name') == firm_name:
                existing_entry = entry
                break
        
        # Run discovery
        discovery_result = discover_firm(firm_name, entry_points)
        
        # Merge with existing entry (preserve region if exists)
        if existing_entry:
            existing_entry.update(discovery_result)
            # Preserve region if it exists
            if 'region' in existing_entry:
                discovery_result['region'] = existing_entry['region']
            # Update entry points (merge, deduplicate)
            existing_points = set(existing_entry.get('known_entry_points', []))
            new_points = set(entry_points)
            discovery_result['known_entry_points'] = sorted(list(existing_points | new_points))
        else:
            # New entry
            discovery_result['region'] = ''  # Would need manual input
            discovery_result['known_entry_points'] = entry_points
        
        # Update or add entry
        if existing_entry:
            entries[entries.index(existing_entry)] = discovery_result
        else:
            entries.append(discovery_result)
    
    # Save
    save_bulge_brackets(entries)
    
    # Print summary
    print(f"\n{'='*60}")
    print("DISCOVERY SUMMARY")
    print(f"{'='*60}\n")
    
    status_counts = {}
    lane_counts = {}
    
    for entry in entries:
        status = entry.get('acquisition_status', 'unknown')
        lane = entry.get('lane_candidate', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
    
    print("Status breakdown:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    
    print("\nLane breakdown:")
    for lane, count in sorted(lane_counts.items()):
        print(f"  {lane}: {count}")
    
    print(f"\n✓ Discovery complete. Updated {BULGE_BRACKETS_FILE}")


if __name__ == '__main__':
    main()
