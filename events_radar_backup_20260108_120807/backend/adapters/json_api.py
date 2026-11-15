"""
JSON API adapter for extracting events from JSON endpoints.
Used when a source provides a JSON API instead of HTML.
"""

import requests
import sys
from pathlib import Path

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.normalize import normalize_string, normalize_url
from utils.dates import parse_date
from utils.json_utils import ensure_dict, ensure_list
from utils.json_path import get_path, extract_list
from utils.event_filter import is_event_like
from utils.postprocess import apply_postprocess


def extract_events(json_data, source_config, return_stats=False):
    """
    Extract events from JSON data using configured paths.
    
    Args:
        json_data: parsed JSON (dict or list)
        source_config: source configuration with api_config
    
    Returns:
        List of event dicts or (list, stats) if return_stats=True
    
    api_config format:
    {
        "items_path": "results",           # path to array of items
        "title_path": "title",             # path within each item to title
        "link_path": "url",                # path to link/URL
        "date_path": "displaydate",        # path to date string (optional)
        "base_url": "https://example.com"  # base URL for relative links (optional)
    }
    """
    api_config = ensure_dict(source_config.get('api_config'))
    firm_name = source_config.get('firm_name', '')
    default_tags = ensure_list(source_config.get('default_tags_json'))
    base_url = api_config.get('base_url', source_config.get('url', ''))
    
    # Get configuration paths
    items_path = api_config.get('items_path', 'results')
    title_path = api_config.get('title_path', 'title')
    link_path = api_config.get('link_path', 'url')
    date_path = api_config.get('date_path')
    
    # Extract items list
    items = extract_list(json_data, items_path)
    
    events = []
    stats = {
        'raw': len(items),
        'kept': 0,
        'rejected': {}
    }
    
    def reject(reason):
        stats['rejected'][reason] = stats['rejected'].get(reason, 0) + 1
    
    for item in items:
        try:
            # Extract title
            title = get_path(item, title_path)
            if not title:
                reject('no_title')
                continue
            
            event_name = normalize_string(str(title))
            if not event_name or len(event_name) < 5:
                reject('invalid_title')
                continue
            
            # Extract link
            link = get_path(item, link_path)
            if not link:
                reject('no_link')
                continue
            
            link = normalize_url(str(link), base_url)
            if not link:
                reject('invalid_link')
                continue
            
            # Extract date (optional)
            date_time = None
            raw_date_text = ""
            if date_path:
                date_str = get_path(item, date_path)
                if date_str:
                    raw_date_text = str(date_str)
                    date_time = parse_date(raw_date_text)
            
            # Build event dict
            event = {
                'firm_name': firm_name,
                'event_name': event_name,
                'date_time': date_time,
                'link': link,
                'tags': default_tags
            }
            
            # Apply event-likeness filter
            if not is_event_like(event_name, link, raw_date_text):
                reject('not_event_like')
                continue
            
            # Apply per-source post-processing
            event = apply_postprocess(event, source_config)
            if event is None:
                reject('postprocess_rejected')
                continue
            
            events.append(event)
            stats['kept'] += 1
            
        except Exception as e:
            reject('parse_error')
            continue
    
    if return_stats:
        return (events, stats)
    return events


def fetch_and_extract(source_config, return_stats=False):
    """
    Fetch JSON from API endpoint and extract events.
    
    Args:
        source_config: source configuration with url and api_config
    
    Returns:
        (events_list, stats_dict) if return_stats else events_list
    """
    api_config = ensure_dict(source_config.get('api_config'))
    url = api_config.get('endpoint') or source_config.get('url', '')
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        })
        response.raise_for_status()
        
        json_data = response.json()
        return extract_events(json_data, source_config, return_stats=return_stats)
        
    except requests.RequestException as e:
        if return_stats:
            return ([], {'raw': 0, 'kept': 0, 'rejected': {'request_error': 1}})
        return []
    except Exception as e:
        if return_stats:
            return ([], {'raw': 0, 'kept': 0, 'rejected': {'parse_error': 1}})
        return []
