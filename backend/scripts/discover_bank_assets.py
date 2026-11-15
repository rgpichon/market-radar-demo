#!/usr/bin/env python3
"""
Bank Asset Discovery: Exhaustive discovery of bank event acquisition methods.

For each bank, systematically tests:
- RSS feed discovery
- ICS calendar discovery
- HTML events page detection
- Investor Relations calendar detection
- Records HTTP status, JS usage, auth walls

Results persisted to backend/bank_assets.json
"""
import sys
import json
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import re

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from scripts.discover_feeds import discover_feeds
from scripts.validate_html_events import validate_html_events


BANK_ASSETS_FILE = backend_dir / "bank_assets.json"
BULGE_BRACKETS_FILE = backend_dir / "bulge_brackets.json"


def load_banks() -> List[Dict]:
    """Load banks from bulge_brackets.json."""
    if not BULGE_BRACKETS_FILE.exists():
        return []
    
    with open(BULGE_BRACKETS_FILE, 'r') as f:
        return json.load(f)


def test_rss_discovery(url: str) -> Dict:
    """Test RSS feed discovery for a URL."""
    result = {
        'method': 'rss_discovery',
        'url': url,
        'status': 'not_found',
        'feeds_found': [],
        'evidence': ''
    }
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        result['http_status'] = response.status_code
        
        if response.status_code != 200:
            result['evidence'] = f"HTTP {response.status_code}"
            return result
        
        # Look for RSS discovery tags
        soup = BeautifulSoup(response.text, 'html.parser')
        feeds = []
        
        # Check for RSS/Atom link tags
        for link in soup.find_all('link', rel='alternate'):
            link_type = link.get('type', '')
            if 'rss' in link_type or 'atom' in link_type:
                href = link.get('href', '')
                if href:
                    # Make absolute URL
                    if href.startswith('/'):
                        from urllib.parse import urljoin
                        href = urljoin(url, href)
                    feeds.append({
                        'url': href,
                        'type': 'rss' if 'rss' in link_type else 'atom'
                    })
        
        if feeds:
            result['status'] = 'found'
            result['feeds_found'] = feeds
            result['evidence'] = f"Found {len(feeds)} feed(s) via discovery tags"
        else:
            result['evidence'] = "No RSS/Atom discovery tags found"
        
    except requests.exceptions.RequestException as e:
        result['status'] = 'error'
        result['evidence'] = f"Request error: {str(e)}"
    except Exception as e:
        result['status'] = 'error'
        result['evidence'] = f"Error: {str(e)}"
    
    return result


def test_ics_discovery(url: str) -> Dict:
    """Test ICS calendar discovery for a URL."""
    result = {
        'method': 'ics_discovery',
        'url': url,
        'status': 'not_found',
        'feeds_found': [],
        'evidence': ''
    }
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        result['http_status'] = response.status_code
        
        if response.status_code != 200:
            result['evidence'] = f"HTTP {response.status_code}"
            return result
        
        # Look for .ics links
        soup = BeautifulSoup(response.text, 'html.parser')
        ics_links = []
        
        # Check for .ics links
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if href.endswith('.ics') or 'calendar' in href.lower():
                # Make absolute URL
                if href.startswith('/'):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                ics_links.append(href)
        
        # Also check for text/calendar content type
        content_type = response.headers.get('Content-Type', '')
        if 'text/calendar' in content_type or 'application/ics' in content_type:
            ics_links.append(url)
        
        if ics_links:
            result['status'] = 'found'
            result['feeds_found'] = [{'url': link, 'type': 'ics'} for link in set(ics_links)]
            result['evidence'] = f"Found {len(ics_links)} ICS link(s)"
        else:
            result['evidence'] = "No ICS links found"
        
    except requests.exceptions.RequestException as e:
        result['status'] = 'error'
        result['evidence'] = f"Request error: {str(e)}"
    except Exception as e:
        result['status'] = 'error'
        result['evidence'] = f"Error: {str(e)}"
    
    return result


def test_html_events_page(url: str) -> Dict:
    """Test HTML events page accessibility and structure."""
    result = {
        'method': 'html_events',
        'url': url,
        'status': 'not_found',
        'html_length': 0,
        'js_rendered': False,
        'auth_required': False,
        'evidence': ''
    }
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        result['http_status'] = response.status_code
        
        if response.status_code == 401 or response.status_code == 403:
            result['status'] = 'blocked'
            result['auth_required'] = True
            result['evidence'] = f"HTTP {response.status_code} - Authentication required"
            return result
        
        if response.status_code != 200:
            result['evidence'] = f"HTTP {response.status_code}"
            return result
        
        html = response.text
        result['html_length'] = len(html)
        
        # Check for JS rendering
        soup = BeautifulSoup(html, 'html.parser')
        
        # Check for app shell patterns
        scripts = soup.find_all('script')
        script_count = len(scripts)
        
        # Check for common JS framework indicators
        js_frameworks = ['react', 'angular', 'vue', 'next.js', 'nuxt']
        has_js_framework = any(fw in html.lower() for fw in js_frameworks)
        
        # Check for minimal HTML (app shell)
        if len(html) < 5000 or (script_count > 5 and has_js_framework):
            result['js_rendered'] = True
            result['status'] = 'js_rendered'
            result['evidence'] = f"JS-rendered: HTML {len(html)} bytes, {script_count} scripts"
        else:
            # Check for event-like content
            event_keywords = ['event', 'webinar', 'conference', 'seminar', 'calendar']
            html_lower = html.lower()
            has_event_keywords = any(kw in html_lower for kw in event_keywords)
            
            if has_event_keywords:
                result['status'] = 'accessible'
                result['evidence'] = f"HTML accessible: {len(html)} bytes, event keywords found"
            else:
                result['status'] = 'no_events'
                result['evidence'] = f"HTML accessible but no event keywords found"
        
    except requests.exceptions.RequestException as e:
        result['status'] = 'error'
        result['evidence'] = f"Request error: {str(e)}"
    except Exception as e:
        result['status'] = 'error'
        result['evidence'] = f"Error: {str(e)}"
    
    return result


def test_ir_calendar(url: str) -> Dict:
    """Test Investor Relations calendar page."""
    # Try common IR calendar URLs
    ir_patterns = [
        '/investor-relations/events',
        '/investor-relations/calendar',
        '/investor-relations/upcoming-events',
        '/ir/events',
        '/ir/calendar'
    ]
    
    result = {
        'method': 'ir_calendar',
        'base_url': url,
        'status': 'not_found',
        'urls_tested': [],
        'evidence': ''
    }
    
    from urllib.parse import urljoin
    
    for pattern in ir_patterns:
        test_url = urljoin(url, pattern)
        result['urls_tested'].append(test_url)
        
        try:
            response = requests.get(test_url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }, allow_redirects=False)
            
            if response.status_code == 200:
                result['status'] = 'found'
                result['evidence'] = f"Found IR calendar at {test_url}"
                result['found_url'] = test_url
                return result
            elif response.status_code in [301, 302, 303, 307, 308]:
                # Follow redirect
                redirect_url = response.headers.get('Location', '')
                if redirect_url:
                    result['status'] = 'redirect'
                    result['evidence'] = f"Redirect to {redirect_url}"
                    result['redirect_url'] = redirect_url
                    return result
        
        except:
            continue
    
    result['evidence'] = f"Tested {len(ir_patterns)} IR patterns, none found"
    return result


def test_earnings_calendar(firm_name: str, entry_point: str) -> Dict:
    """Test earnings calendar discovery."""
    result = {
        'method': 'earnings_calendar',
        'firm_name': firm_name,
        'base_url': entry_point,
        'status': 'not_found',
        'calendars_tested': [],
        'evidence': ''
    }
    
    # Common earnings calendar URLs
    earnings_patterns = [
        'https://www.nasdaq.com/market-activity/stocks/{}/earnings',
        'https://finance.yahoo.com/quote/{}/events',
        'https://www.marketwatch.com/investing/stock/{}/events',
        'https://seekingalpha.com/symbol/{}/earnings/calendar'
    ]
    
    # Try to extract ticker from firm name (simplified)
    ticker = None
    # This is a stub - real implementation would need ticker lookup
    # For now, just document the attempt
    
    for pattern in earnings_patterns:
        if '{' in pattern:
            # Skip patterns requiring ticker for now
            continue
        result['calendars_tested'].append(pattern)
    
    result['evidence'] = 'Earnings calendar discovery requires ticker symbol lookup - not yet implemented'
    return result


def test_ir_aggregator(firm_name: str, entry_point: str) -> Dict:
    """Test IR aggregator platform detection."""
    result = {
        'method': 'ir_aggregator',
        'firm_name': firm_name,
        'base_url': entry_point,
        'status': 'not_found',
        'platforms_tested': [],
        'evidence': ''
    }
    
    # Common IR platform patterns
    ir_platforms = [
        'https://ir.nasdaq.com/',
        'https://www.q4inc.com/',
        'https://www.notified.com/'
    ]
    
    # Check if bank uses known IR platform
    # This requires checking the bank's IR page for platform indicators
    try:
        response = requests.get(entry_point, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        if response.status_code == 200:
            html = response.text.lower()
            # Look for IR platform indicators
            if 'nasdaq ir' in html or 'ir.nasdaq' in html:
                result['status'] = 'detected'
                result['platform'] = 'nasdaq_ir'
                result['evidence'] = 'Nasdaq IR platform detected'
                return result
            elif 'q4' in html or 'q4inc' in html:
                result['status'] = 'detected'
                result['platform'] = 'q4'
                result['evidence'] = 'Q4 platform detected'
                return result
            elif 'notified' in html:
                result['status'] = 'detected'
                result['platform'] = 'notified'
                result['evidence'] = 'Notified platform detected'
                return result
        
        result['evidence'] = 'No known IR platform detected'
    except Exception as e:
        result['status'] = 'error'
        result['evidence'] = f"Error checking IR platform: {str(e)}"
    
    return result


def test_third_party_finance_calendar(firm_name: str) -> Dict:
    """Test third-party finance calendar discovery."""
    result = {
        'method': 'third_party_finance_calendar',
        'firm_name': firm_name,
        'status': 'not_found',
        'calendars_tested': [],
        'evidence': ''
    }
    
    # Common third-party finance calendars
    third_party_calendars = [
        'https://www.nasdaq.com/earnings',
        'https://finance.yahoo.com/calendar/earnings',
        'https://www.marketwatch.com/tools/calendars/earnings',
        'https://www.investing.com/earnings-calendar/'
    ]
    
    result['calendars_tested'] = third_party_calendars
    result['evidence'] = 'Third-party calendar discovery requires bank ticker lookup and calendar parsing - not yet implemented'
    return result


def discover_bank_assets(bank: Dict) -> Dict:
    """Discover all acquisition methods for a bank."""
    firm_name = bank.get('firm_name', '')
    entry_points = bank.get('known_entry_points', [])
    
    print(f"\n=== Discovering assets for {firm_name} ===")
    
    results = {
        'firm_name': firm_name,
        'discovered_at': datetime.now(timezone.utc).isoformat(),
        'entry_points_tested': entry_points,
        'methods': [],
        'attempted_lanes': []
    }
    
    # Define all lanes to test
    lanes_to_test = [
        'rss',
        'ics',
        'html_simple',
        'html_complex',
        'earnings_calendar',
        'ir_aggregator',
        'third_party_finance_calendar'
    ]
    
    # Test each entry point
    for entry_point in entry_points:
        print(f"  Testing: {entry_point}")
        
        # Test RSS discovery
        rss_result = test_rss_discovery(entry_point)
        rss_result['attempted_lane'] = 'rss'
        results['methods'].append(rss_result)
        results['attempted_lanes'].append('rss')
        if rss_result['status'] == 'found':
            print(f"    ✓ RSS found: {len(rss_result['feeds_found'])} feed(s)")
        
        # Test ICS discovery
        ics_result = test_ics_discovery(entry_point)
        ics_result['attempted_lane'] = 'ics'
        results['methods'].append(ics_result)
        results['attempted_lanes'].append('ics')
        if ics_result['status'] == 'found':
            print(f"    ✓ ICS found: {len(ics_result['feeds_found'])} feed(s)")
        
        # Test HTML events page
        html_result = test_html_events_page(entry_point)
        html_result['attempted_lane'] = 'html_simple'
        results['methods'].append(html_result)
        results['attempted_lanes'].append('html_simple')
        if html_result['status'] == 'accessible':
            print(f"    ✓ HTML accessible")
        elif html_result['status'] == 'js_rendered':
            print(f"    ✗ JS-rendered")
        elif html_result['status'] == 'blocked':
            print(f"    ✗ Blocked (HTTP {html_result.get('http_status')})")
        
        # Test IR calendar (only on homepage)
        if entry_point == bank.get('known_entry_points', [])[0] if bank.get('known_entry_points') else None:
            ir_result = test_ir_calendar(entry_point)
            ir_result['attempted_lane'] = 'ir_aggregator'
            results['methods'].append(ir_result)
            results['attempted_lanes'].append('ir_aggregator')
            if ir_result['status'] == 'found':
                print(f"    ✓ IR calendar found")
    
    # Test bank-specific lanes (once per bank, not per entry point)
    print(f"  Testing bank-specific lanes:")
    
    # Earnings calendar
    earnings_result = test_earnings_calendar(firm_name, entry_points[0] if entry_points else '')
    earnings_result['attempted_lane'] = 'earnings_calendar'
    results['methods'].append(earnings_result)
    results['attempted_lanes'].append('earnings_calendar')
    print(f"    → Earnings calendar: {earnings_result['status']}")
    
    # IR aggregator
    ir_agg_result = test_ir_aggregator(firm_name, entry_points[0] if entry_points else '')
    ir_agg_result['attempted_lane'] = 'ir_aggregator'
    results['methods'].append(ir_agg_result)
    if 'ir_aggregator' not in results['attempted_lanes']:
        results['attempted_lanes'].append('ir_aggregator')
    if ir_agg_result['status'] == 'detected':
        print(f"    ✓ IR platform detected: {ir_agg_result.get('platform')}")
    
    # Third-party finance calendar
    third_party_result = test_third_party_finance_calendar(firm_name)
    third_party_result['attempted_lane'] = 'third_party_finance_calendar'
    results['methods'].append(third_party_result)
    results['attempted_lanes'].append('third_party_finance_calendar')
    print(f"    → Third-party calendar: {third_party_result['status']}")
    
    # Deduplicate attempted_lanes
    results['attempted_lanes'] = list(set(results['attempted_lanes']))
    
    return results


def classify_failure(methods: List[Dict]) -> Dict:
    """Classify failure based on discovery results."""
    # Check for truly successful methods (feeds found, not just accessible HTML)
    # HTML "accessible" doesn't mean success if no events are found
    successful = [m for m in methods if m.get('status') in ['found', 'detected'] and 
                  m.get('method') in ['rss_discovery', 'ics_discovery', 'ir_calendar', 'ir_aggregator']]
    
    # HTML accessible is NOT success if no events found
    html_accessible = [m for m in methods if m.get('status') == 'accessible' and m.get('method') == 'html_events']
    
    # If we have feeds or IR platforms, that's success
    if successful:
        return {
            'failure_class': None,
            'recommended_next_action': None,
            'evidence': f"Found {len(successful)} successful method(s): {[m.get('method') for m in successful]}"
        }
    
    # Check for IR platform detection
    ir_platform = [m for m in methods if m.get('method') == 'ir_aggregator' and m.get('status') == 'detected']
    if ir_platform:
        platform = ir_platform[0].get('platform', 'unknown')
        return {
            'failure_class': 'ir_platform_detected',
            'recommended_next_action': 'ir_platform_integration',
            'evidence': f"IR platform detected: {platform} - requires platform-specific integration"
        }
    
    # Check for earnings calendar availability (external)
    earnings_cal = [m for m in methods if m.get('method') == 'earnings_calendar']
    if earnings_cal:
        return {
            'failure_class': 'earnings_only_external',
            'recommended_next_action': 'third_party_calendar',
            'evidence': 'Earnings events available via external calendars, not bank website'
        }
    
    # Check for third-party calendar requirement
    third_party = [m for m in methods if m.get('method') == 'third_party_finance_calendar']
    if third_party:
        return {
            'failure_class': 'third_party_required',
            'recommended_next_action': 'third_party_calendar',
            'evidence': 'Bank events require third-party calendar access'
        }
    
    # Check for JS rendering
    js_rendered = [m for m in methods if m.get('js_rendered') or m.get('status') == 'js_rendered']
    if js_rendered:
        return {
            'failure_class': 'js_rendered',
            'recommended_next_action': 'playwright',
            'evidence': js_rendered[0].get('evidence', 'JS-rendered page detected')
        }
    
    # Check for auth/gating
    blocked = [m for m in methods if m.get('auth_required') or m.get('status') == 'blocked']
    if blocked:
        return {
            'failure_class': 'gated_login',
            'recommended_next_action': 'rss_search',
            'evidence': blocked[0].get('evidence', 'Authentication required')
        }
    
    # Check for inaccessible primary source
    # HTML accessible but no events found = inaccessible for our purposes
    primary_methods = [m for m in methods if m.get('method') in ['rss_discovery', 'ics_discovery', 'html_events']]
    all_primary_failed = all(m.get('status') in ['not_found', 'error', 'no_events', 'accessible'] for m in primary_methods)
    
    # If HTML is accessible but no events, that's still inaccessible_primary_source
    if all_primary_failed and html_accessible:
        return {
            'failure_class': 'inaccessible_primary_source',
            'recommended_next_action': 'third_party_calendar',
            'evidence': 'Primary source (bank website) accessible but no events found - events not exposed via standard methods'
        }
    
    # If all primary methods failed (including HTML not accessible)
    if all_primary_failed and not html_accessible:
        return {
            'failure_class': 'inaccessible_primary_source',
            'recommended_next_action': 'third_party_calendar',
            'evidence': 'Primary source (bank website) does not expose events via standard methods'
        }
    
    # Check for HTTP errors
    http_errors = [m for m in methods if m.get('http_status') and m.get('http_status') >= 400]
    if http_errors:
        status = http_errors[0].get('http_status')
        if status == 403:
            return {
                'failure_class': 'blocked',
                'recommended_next_action': 'third_party_proxy',
                'evidence': f"HTTP {status} - Access blocked"
            }
        elif status == 404:
            return {
                'failure_class': 'no_events',
                'recommended_next_action': 'abandon',
                'evidence': f"HTTP {status} - Page not found"
            }
    
    # Default: dead end
    return {
        'failure_class': 'dead_end',
        'recommended_next_action': 'abandon',
        'evidence': 'No feasible acquisition method found'
    }


def main():
    """Run discovery for all banks."""
    banks = load_banks()
    
    if not banks:
        print("No banks found in bulge_brackets.json")
        return
    
    # Load existing assets
    if BANK_ASSETS_FILE.exists():
        with open(BANK_ASSETS_FILE, 'r') as f:
            assets = json.load(f)
    else:
        assets = {}
    
    # Discover assets for each bank
    for bank in banks:
        firm_name = bank.get('firm_name', '')
        if not firm_name:
            continue
        
        print(f"\n{'='*60}")
        print(f"Bank: {firm_name}")
        print(f"{'='*60}")
        
        # Discover assets
        bank_result = discover_bank_assets(bank)
        
        # Classify failure
        classification = classify_failure(bank_result['methods'])
        bank_result['failure_class'] = classification['failure_class']
        bank_result['recommended_next_action'] = classification['recommended_next_action']
        bank_result['failure_evidence'] = classification['evidence']
        
        # Store result
        assets[firm_name] = bank_result
        
        # Print summary
        print(f"\nSummary:")
        print(f"  Failure class: {classification['failure_class'] or 'None (success)'}")
        print(f"  Recommended action: {classification['recommended_next_action'] or 'None'}")
        print(f"  Evidence: {classification['evidence']}")
    
    # Save results
    with open(BANK_ASSETS_FILE, 'w') as f:
        json.dump(assets, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Discovery complete. Results saved to {BANK_ASSETS_FILE}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
