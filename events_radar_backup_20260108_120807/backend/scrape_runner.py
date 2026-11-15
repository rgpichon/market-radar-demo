import json
import requests
from pathlib import Path
import sys

# Add backend directory to path for imports
backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_sources, upsert_event, create_notification, get_event_by_id
from adapters.html_list import extract_events as extract_html_list, extract_events_with_detail_fetch
from adapters.json_ld import extract_events as extract_json_ld
from adapters.json_api import fetch_and_extract as extract_json_api
from utils.json_utils import ensure_list, ensure_dict
from bs4 import BeautifulSoup


def load_preferences():
    """Load preferences.json."""
    prefs_path = Path(__file__).parent / "preferences.json"
    with open(prefs_path, 'r') as f:
        return json.load(f)


def load_packs():
    """Load packs.json."""
    packs_path = Path(__file__).parent / "packs.json"
    with open(packs_path, 'r') as f:
        return json.load(f)


def normalize_for_comparison(s):
    """Normalize a string for case-insensitive comparison."""
    if not s:
        return ""
    return str(s).lower().strip()


def should_notify(event, preferences, packs):
    """
    Determine if a new event should trigger a notification.
    Returns True if notification should be created.
    Uses normalized (lowercase, stripped) comparisons for robustness.
    """
    # Check if event is confirmed
    confirmed = bool(event.get('date_time') and event.get('link'))
    
    if preferences.get('require_confirmed_for_notifications') and not confirmed:
        return False
    
    # Normalize event firm name for comparison
    firm_name = normalize_for_comparison(event.get('firm_name', ''))
    
    # Ensure tags is a list and normalize
    event_tags = ensure_list(event.get('tags'))
    event_tags_normalized = {normalize_for_comparison(t) for t in event_tags if t}
    
    # Normalize follow_firms for comparison
    follow_firms = ensure_list(preferences.get('follow_firms'))
    follow_firms_normalized = {normalize_for_comparison(f) for f in follow_firms if f}
    
    # Check firm match (normalized)
    if firm_name and firm_name in follow_firms_normalized:
        return True
    
    # Check pack match (normalized)
    follow_packs = ensure_list(preferences.get('follow_packs'))
    for pack_id in follow_packs:
        pack = packs.get(pack_id, {})
        pack_firms = ensure_list(pack.get('firms'))
        pack_firms_normalized = {normalize_for_comparison(f) for f in pack_firms if f}
        if firm_name and firm_name in pack_firms_normalized:
            return True
    
    # Check tag match (normalized)
    follow_tags = ensure_list(preferences.get('follow_tags'))
    follow_tags_normalized = {normalize_for_comparison(t) for t in follow_tags if t}
    
    if event_tags_normalized.intersection(follow_tags_normalized):
        return True
    
    return False


def scrape_source(source, preferences, packs):
    """
    Scrape a single source.
    Returns (events_found, inserted_count, updated_count, notifications_created, error, diagnostics).
    """
    diagnostics = None
    status_code = None
    extraction_stats = None
    
    try:
        # Fetch HTML
        response = requests.get(source['url'], timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }, allow_redirects=True)
        status_code = response.status_code
        response.raise_for_status()
        html = response.text
        final_url = response.url
        
        # Extract events using appropriate adapter
        adapter_type = source.get('adapter_type')
        events = []
        
        if adapter_type == 'json_api':
            # JSON API adapter doesn't need to fetch HTML first - it fetches its own endpoint
            # But we already fetched it, so check if api_config has different endpoint
            api_config = ensure_dict(source.get('api_config'))
            api_endpoint = api_config.get('endpoint')
            
            if api_endpoint and api_endpoint != source['url']:
                # Fetch from API endpoint separately
                events, extraction_stats = extract_json_api(source, return_stats=True)
            else:
                # Try to parse the HTML response as JSON (if source URL is the API)
                try:
                    import json as json_module
                    json_data = json_module.loads(html)
                    from adapters.json_api import extract_events as extract_json_events
                    events, extraction_stats = extract_json_events(json_data, source, return_stats=True)
                except:
                    # Fall back to fetching from endpoint
                    events, extraction_stats = extract_json_api(source, return_stats=True)
        elif adapter_type == 'json_ld':
            events = extract_json_ld(html, source)
            extraction_stats = {'raw': len(events), 'kept': len(events), 'rejected': {}}
        elif adapter_type == 'html_list':
            # Check if detail_fetch is enabled for this source
            detail_fetch = ensure_dict(source.get('detail_fetch'))
            if detail_fetch.get('enabled', False):
                events, extraction_stats = extract_events_with_detail_fetch(html, source)
            else:
                events, extraction_stats = extract_html_list(html, source, return_stats=True)
        else:
            return (0, 0, 0, 0, f"Unknown adapter type: {adapter_type}", None)
        
        # If no events found, prepare diagnostic info
        if len(events) == 0:
            selectors = ensure_dict(source.get('selectors_json'))
            has_item_selector = bool(selectors.get('item_selector'))
            has_title_selector = bool(selectors.get('title_selector'))
            
            # Check for JS-rendered page heuristics
            is_js_rendered = False
            if len(html) > 10000:  # Large HTML
                # Check for common JS-rendered indicators
                html_lower = html.lower()
                js_indicators = [
                    'enable javascript', 'javascript required', 'please enable javascript',
                    'noscript', 'react-root', 'ng-app', 'data-reactroot'
                ]
                if any(indicator in html_lower for indicator in js_indicators):
                    # But also check if there are any cards/items
                    soup = BeautifulSoup(html, 'html.parser')
                    potential_items = soup.select(selectors.get('item_selector', 'article, .card, .item'))
                    if len(potential_items) == 0:
                        is_js_rendered = True
            
            diagnostics = {
                'adapter_type': adapter_type,
                'url': final_url,
                'status_code': status_code,
                'has_item_selector': has_item_selector,
                'has_title_selector': has_title_selector,
                'item_selector': selectors.get('item_selector') if has_item_selector else None,
                'html_length': len(html),
                'is_js_rendered': is_js_rendered
            }
        
        # Include extraction stats in diagnostics
        if extraction_stats:
            if diagnostics is None:
                diagnostics = {}
            diagnostics['extraction_stats'] = extraction_stats
        
        inserted_count = 0
        updated_count = 0
        notifications_created = 0
        
        # Upsert events
        for event in events:
            # Ensure tags is a list
            tags = ensure_list(event.get('tags'))
            tags_json = json.dumps(tags) if tags else None
            
            is_new, event_id = upsert_event(
                firm_name=event['firm_name'],
                event_name=event['event_name'],
                date_time=event.get('date_time'),
                link=event['link'],
                source_id=source['id'],
                tags_json=tags_json
            )
            
            if is_new:
                inserted_count += 1
                # Check if should notify (new matches only)
                if should_notify(event, preferences, packs):
                    if create_notification(event_id, reason="new_match"):
                        notifications_created += 1
            else:
                updated_count += 1
        
        return (len(events), inserted_count, updated_count, notifications_created, None, diagnostics)
        
    except requests.RequestException as e:
        status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        diagnostics = {
            'adapter_type': source.get('adapter_type'),
            'url': source.get('url'),
            'status_code': status_code,
            'error_type': type(e).__name__
        }
        return (0, 0, 0, 0, f"Request error: {str(e)}", diagnostics)
    except Exception as e:
        diagnostics = {
            'adapter_type': source.get('adapter_type'),
            'url': source.get('url'),
            'error_type': type(e).__name__
        }
        return (0, 0, 0, 0, f"Error: {str(e)}", diagnostics)


def run_scrape():
    """
    Run scraping for all active sources.
    Returns summary dict with detailed statistics.
    """
    sources = get_sources(active_only=True)
    
    # Load preferences and packs once for all sources
    preferences = load_preferences()
    packs = load_packs()
    
    total_inserted = 0
    total_updated = 0
    total_notifications = 0
    total_extracted = 0
    total_raw = 0
    sources_ok = 0
    sources_zero = 0
    sources_failed = 0
    source_results = []
    
    for source in sources:
        events_found, inserted, updated, notifications, error, diagnostics = scrape_source(
            source, preferences, packs
        )
        
        # Get raw count from extraction stats if available
        raw_count = events_found
        if diagnostics and 'extraction_stats' in diagnostics:
            raw_count = diagnostics['extraction_stats'].get('raw', events_found)
        
        total_raw += raw_count
        total_extracted += events_found
        total_inserted += inserted
        total_updated += updated
        total_notifications += notifications
        
        if error:
            sources_failed += 1
        elif events_found == 0:
            sources_zero += 1
        else:
            sources_ok += 1
        
        result = {
            'source_id': source['id'],
            'firm_name': source['firm_name'],
            'raw_items': raw_count,
            'events_found': events_found,
            'inserted': inserted,
            'updated': updated,
            'notifications': notifications,
            'error': error
        }
        
        # Add rejection reasons if available
        if diagnostics and 'extraction_stats' in diagnostics:
            stats = diagnostics['extraction_stats']
            if stats.get('rejected'):
                result['rejected_reasons'] = stats['rejected']
        
        # Add diagnostics if 0 events found or error
        if (events_found == 0 or error) and diagnostics:
            result['diagnostics'] = diagnostics
        
        source_results.append(result)
    
    return {
        'total_sources': len(sources),
        'sources_ok': sources_ok,
        'sources_zero': sources_zero,
        'sources_failed': sources_failed,
        'total_raw': total_raw,
        'total_extracted': total_extracted,
        'total_inserted': total_inserted,
        'total_updated': total_updated,
        'total_notifications': total_notifications,
        'source_results': source_results
    }
