#!/usr/bin/env python3
"""
Discover feeds and validate HTML for bulge bracket firms.
Runs discover_feeds + validate_html_events and updates bulge_brackets.json.

Usage:
    python bb_discover.py <firm_name> <homepage_url>
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

BULGE_BRACKETS_FILE = backend_dir / "bulge_brackets.json"


def load_bulge_brackets():
    """Load bulge_brackets.json."""
    if not BULGE_BRACKETS_FILE.exists():
        return []
    
    try:
        with open(BULGE_BRACKETS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading bulge_brackets.json: {e}")
        return []


def save_bulge_brackets(entries):
    """Save bulge_brackets.json."""
    try:
        with open(BULGE_BRACKETS_FILE, 'w') as f:
            json.dump(entries, f, indent=2)
        print(f"✓ Updated {BULGE_BRACKETS_FILE}")
    except IOError as e:
        print(f"Error saving bulge_brackets.json: {e}")
        sys.exit(1)


def run_discover_feeds(url):
    """Run discover_feeds.py and capture output."""
    try:
        result = subprocess.run(
            [sys.executable, str(backend_dir / "scripts" / "discover_feeds.py"), url],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Timeout"
    except Exception as e:
        return False, "", str(e)


def run_validate_html(url):
    """Run validate_html_events.py and capture output."""
    try:
        result = subprocess.run(
            [sys.executable, str(backend_dir / "scripts" / "validate_html_events.py"), url],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Timeout"
    except Exception as e:
        return False, "", str(e)


def discover_bulge_bracket(firm_name, homepage_url):
    """Discover feeds and validate HTML for a bulge bracket firm."""
    print(f"\n=== Discovering: {firm_name} ===\n")
    print(f"Homepage: {homepage_url}\n")
    
    # Run discover_feeds
    print("Running discover_feeds.py...")
    feeds_success, feeds_stdout, feeds_stderr = run_discover_feeds(homepage_url)
    
    feeds_found = []
    if feeds_success:
        # Parse output for discovered feeds
        lines = feeds_stdout.split('\n')
        for line in lines:
            if 'Found' in line and ('RSS' in line or 'ICS' in line or 'feed' in line):
                # Extract feed URL
                if 'http' in line:
                    parts = line.split('http')
                    if len(parts) > 1:
                        feed_url = 'http' + parts[1].strip()
                        feeds_found.append(feed_url)
    
    print(f"Feeds found: {len(feeds_found)}")
    if feeds_found:
        for feed in feeds_found:
            print(f"  - {feed}")
    
    # Run validate_html_events
    print("\nRunning validate_html_events.py...")
    html_success, html_stdout, html_stderr = run_validate_html(homepage_url)
    
    # Parse HTML validation results
    html_feasible = False
    js_rendered = False
    tier = "C"
    
    if html_success:
        html_lower = html_stdout.lower()
        if 'tier: a' in html_lower or 'tier: b' in html_lower:
            html_feasible = True
            if 'tier: a' in html_lower:
                tier = "A"
            else:
                tier = "B"
        if 'js-rendered' in html_lower or 'js rendered' in html_lower:
            js_rendered = True
            tier = "C"
    
    # Determine lane
    if feeds_found:
        lane_candidate = 'rss' if any('rss' in f.lower() for f in feeds_found) else 'ics'
    elif html_feasible and not js_rendered:
        lane_candidate = 'html_simple'
    elif js_rendered:
        lane_candidate = 'js_rendered'
    else:
        lane_candidate = 'js_rendered'  # Default to deferred
    
    # Determine acquisition status
    if lane_candidate in ['rss', 'ics', 'html_simple']:
        acquisition_status = 'active'
    else:
        acquisition_status = 'deferred'
    
    # Build discovery results
    discovery_results = {
        'feeds_found': feeds_found,
        'html_feasible': html_feasible,
        'js_rendered': js_rendered,
        'gated': False,  # Would need manual check
        'tier': tier
    }
    
    # Update or create entry
    entries = load_bulge_brackets()
    entry = None
    for e in entries:
        if e.get('firm_name', '').lower() == firm_name.lower():
            entry = e
            break
    
    if entry:
        # Update existing
        entry['discovery_results'] = discovery_results
        entry['lane_candidate'] = lane_candidate
        entry['acquisition_status'] = acquisition_status
        entry['last_discovered'] = datetime.utcnow().isoformat()
        print(f"\n✓ Updated entry for {firm_name}")
    else:
        # Create new
        entry = {
            'firm_name': firm_name,
            'region': '',  # Would need manual input
            'known_entry_points': [homepage_url],
            'discovery_results': discovery_results,
            'lane_candidate': lane_candidate,
            'acquisition_status': acquisition_status,
            'notes': f"Discovered via bb_discover.py on {datetime.utcnow().isoformat()}",
            'last_discovered': datetime.utcnow().isoformat()
        }
        entries.append(entry)
        print(f"\n✓ Created new entry for {firm_name}")
    
    save_bulge_brackets(entries)
    
    # Print summary
    print(f"\n=== Summary ===")
    print(f"Firm: {firm_name}")
    print(f"Feeds found: {len(feeds_found)}")
    print(f"HTML feasible: {html_feasible}")
    print(f"JS-rendered: {js_rendered}")
    print(f"Tier: {tier}")
    print(f"Lane: {lane_candidate}")
    print(f"Status: {acquisition_status}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python bb_discover.py <firm_name> <homepage_url>")
        sys.exit(1)
    
    firm_name = sys.argv[1]
    homepage_url = sys.argv[2]
    
    discover_bulge_bracket(firm_name, homepage_url)


if __name__ == '__main__':
    main()
