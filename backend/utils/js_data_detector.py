"""
JS Data Detector - Phase 3

Detects hidden JSON/API data embedded in HTML pages.
Many "JS-rendered" pages actually contain clean data in script tags.
"""
import json
import re
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def detect_js_data(html: str, base_url: str) -> Dict:
    """
    Detect embedded JSON data in HTML.
    
    Looks for:
    - __NEXT_DATA__ (Next.js)
    - application/json script tags
    - JSON blobs in script tags
    - API endpoint hints
    
    Returns:
        {
            'found': bool,
            'source_type': 'nextjs'|'json_script'|'api_endpoint'|'none',
            'events': List[Dict],
            'evidence': Dict
        }
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Strategy 1: Next.js __NEXT_DATA__
    next_data = _extract_nextjs_data(soup)
    if next_data:
        events = _parse_json_for_events(next_data, base_url)
        if events:
            return {
                'found': True,
                'source_type': 'nextjs',
                'events': events,
                'evidence': {'nextjs_data_size': len(str(next_data))}
            }
    
    # Strategy 2: application/json script tags
    json_scripts = soup.find_all('script', type='application/json')
    for script in json_scripts:
        try:
            data = json.loads(script.string)
            events = _parse_json_for_events(data, base_url)
            if events:
                return {
                    'found': True,
                    'source_type': 'json_script',
                    'events': events,
                    'evidence': {'script_id': script.get('id', 'unknown')}
                }
        except (json.JSONDecodeError, AttributeError):
            continue
    
    # Strategy 3: Generic JSON in script tags (not application/ld+json)
    scripts = soup.find_all('script')
    for script in scripts:
        if script.get('type') == 'application/ld+json':
            continue  # Skip, handled by structured metadata extractor
        
        text = script.string
        if not text:
            continue
        
        # Look for JSON-like patterns
        json_match = re.search(r'\{[^{}]*"events?[^{}]*\{', text, re.IGNORECASE)
        if json_match:
            try:
                # Try to extract JSON object
                start = text.find('{')
                if start >= 0:
                    # Try to find matching closing brace (simplified)
                    brace_count = 0
                    end = start
                    for i, char in enumerate(text[start:], start):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end = i + 1
                                break
                    
                    if end > start:
                        json_str = text[start:end]
                        data = json.loads(json_str)
                        events = _parse_json_for_events(data, base_url)
                        if events:
                            return {
                                'found': True,
                                'source_type': 'json_script',
                                'events': events,
                                'evidence': {'extracted_from_script': True}
                            }
            except (json.JSONDecodeError, ValueError):
                continue
    
    # Strategy 4: API endpoint hints
    api_endpoints = _detect_api_endpoints(soup, base_url)
    if api_endpoints:
        return {
            'found': True,
            'source_type': 'api_endpoint',
            'events': [],
            'evidence': {'api_endpoints': api_endpoints}
        }
    
    return {
        'found': False,
        'source_type': 'none',
        'events': [],
        'evidence': {}
    }


def _extract_nextjs_data(soup: BeautifulSoup) -> Optional[Dict]:
    """Extract __NEXT_DATA__ from Next.js pages."""
    script = soup.find('script', id='__NEXT_DATA__')
    if script and script.string:
        try:
            return json.loads(script.string)
        except json.JSONDecodeError:
            return None
    return None


def _parse_json_for_events(data: any, base_url: str) -> List[Dict]:
    """
    Recursively search JSON for event-like structures.
    
    Looks for arrays of objects with:
    - title/name/headline
    - date/startDate/start/dateTime
    - url/link/href
    """
    events = []
    
    if isinstance(data, dict):
        # Check if this dict itself is an event
        if _looks_like_event(data):
            event = _extract_event_from_dict(data, base_url)
            if event:
                events.append(event)
        
        # Recursively search values
        for value in data.values():
            events.extend(_parse_json_for_events(value, base_url))
    
    elif isinstance(data, list):
        for item in data:
            events.extend(_parse_json_for_events(item, base_url))
    
    return events


def _looks_like_event(obj: Dict) -> bool:
    """Check if a dict looks like an event object."""
    if not isinstance(obj, dict):
        return False
    
    # Must have title/name (and it should be meaningful)
    title_keys = ['title', 'name', 'headline', 'eventName', 'event_name']
    title_value = None
    for key in title_keys:
        if key in obj:
            title_value = str(obj[key]).strip()
            if title_value and len(title_value) > 5:  # Must be meaningful
                break
    
    if not title_value or len(title_value) < 5:
        return False
    
    # Reject common false positives
    false_positives = ['text', 'true', 'false', 'null', 'undefined', 'none']
    if title_value.lower() in false_positives:
        return False
    
    # Should have date or URL (and URL should look valid)
    has_date = any(key in obj for key in ['date', 'startDate', 'start', 'dateTime', 'datetime', 'when'])
    has_url = False
    url_keys = ['url', 'link', 'href', 'permalink', 'eventUrl', 'event_url']
    for key in url_keys:
        if key in obj:
            url_val = str(obj[key])
            # URL should look valid (not just "True" or boolean)
            if url_val and url_val.lower() not in ['true', 'false', 'null'] and ('http' in url_val.lower() or url_val.startswith('/')):
                has_url = True
                break
    
    return (title_value is not None) and (has_date or has_url)


def _extract_event_from_dict(obj: Dict, base_url: str) -> Optional[Dict]:
    """Extract event fields from a dict."""
    event = {}
    
    # Title
    for key in ['title', 'name', 'headline', 'eventName', 'event_name']:
        if key in obj:
            event['title'] = str(obj[key])
            break
    
    # URL
    for key in ['url', 'link', 'href', 'permalink', 'eventUrl', 'event_url']:
        if key in obj:
            url = str(obj[key])
            if not url.startswith('http'):
                url = urljoin(base_url, url)
            event['url'] = url
            break
    
    # Date
    for key in ['date', 'startDate', 'start', 'dateTime', 'datetime', 'when', 'eventDate']:
        if key in obj:
            date_val = obj[key]
            if date_val:
                # Try to parse
                from .structured_metadata_extractor import _parse_iso_date
                parsed = _parse_iso_date(str(date_val))
                if parsed:
                    event['date_iso'] = parsed
                    event['date_text'] = str(date_val)
            break
    
    # Location
    if 'location' in obj:
        location = obj['location']
        if isinstance(location, dict):
            event['location'] = location.get('name') or location.get('address', '')
        else:
            event['location'] = str(location)
    
    # Only return if we have title and (URL or date)
    if event.get('title') and (event.get('url') or event.get('date_iso')):
        return event
    
    return None


def _detect_api_endpoints(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Detect potential API endpoints from page."""
    endpoints = []
    
    # Look for common API patterns in script tags
    api_patterns = [
        r'/api/events',
        r'/api/calendar',
        r'/events\.json',
        r'/calendar\.json',
        r'/api/v\d+/events'
    ]
    
    for script in soup.find_all('script'):
        text = script.string or ''
        for pattern in api_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                full_url = urljoin(base_url, match)
                if full_url not in endpoints:
                    endpoints.append(full_url)
    
    return endpoints
