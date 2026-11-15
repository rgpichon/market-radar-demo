"""
Structured Metadata Extractor - Phase 1

Extracts events from machine-readable metadata (JSON-LD, microdata, meta tags)
before falling back to CSS selectors.

Priority order:
1. JSON-LD (application/ld+json)
2. Microdata (itemtype="Event")
3. Meta tags (og:event, schema.org meta)
"""
import json
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from dateutil import parser as date_parser


def extract_structured_events(html: str, base_url: str) -> Dict:
    """
    Extract events from structured metadata in HTML.
    
    Returns:
        {
            'events': List[Dict],  # Extracted events
            'source_type': 'jsonld'|'microdata'|'meta'|'none',
            'evidence': Dict,  # Raw metadata for debugging
            'count': int
        }
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Priority 1: JSON-LD
    jsonld_events = _extract_jsonld_events(soup, base_url)
    if jsonld_events:
        return {
            'events': jsonld_events,
            'source_type': 'jsonld',
            'evidence': {'jsonld_count': len(jsonld_events)},
            'count': len(jsonld_events)
        }
    
    # Priority 2: Microdata
    microdata_events = _extract_microdata_events(soup, base_url)
    if microdata_events:
        return {
            'events': microdata_events,
            'source_type': 'microdata',
            'evidence': {'microdata_count': len(microdata_events)},
            'count': len(microdata_events)
        }
    
    # Priority 3: Meta tags (og:event, schema.org meta)
    meta_events = _extract_meta_events(soup, base_url)
    if meta_events:
        return {
            'events': meta_events,
            'source_type': 'meta',
            'evidence': {'meta_count': len(meta_events)},
            'count': len(meta_events)
        }
    
    return {
        'events': [],
        'source_type': 'none',
        'evidence': {},
        'count': 0
    }


def _extract_jsonld_events(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """Extract events from JSON-LD blocks."""
    events = []
    
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if not isinstance(data, list):
                data = [data]
            
            for item in data:
                # Handle @graph
                if isinstance(item, dict) and '@graph' in item:
                    graph = item['@graph']
                    if isinstance(graph, list):
                        data.extend(graph)
                    elif isinstance(graph, dict):
                        data.append(graph)
                    continue
                
                # Extract events
                extracted = _parse_jsonld_item(item, base_url)
                if extracted:
                    if isinstance(extracted, list):
                        events.extend(extracted)
                    else:
                        events.append(extracted)
        except (json.JSONDecodeError, KeyError, AttributeError, TypeError):
            continue
    
    # Deduplicate by URL
    seen_urls = set()
    unique_events = []
    for event in events:
        url = event.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_events.append(event)
    
    return unique_events


def _parse_jsonld_item(item: Dict, base_url: str) -> Optional[Dict | List[Dict]]:
    """Parse a JSON-LD item and extract event(s)."""
    if not isinstance(item, dict):
        return None
    
    # Check if it's an Event
    event_type = item.get('@type', '')
    if isinstance(event_type, list):
        event_type = ' '.join(event_type)
    
    if 'Event' not in event_type:
        # Check for EventCollection or ItemList containing events
        if 'ItemList' in event_type or 'Collection' in event_type:
            items = item.get('itemListElement', []) or item.get('hasPart', [])
            events = []
            for sub_item in items:
                if isinstance(sub_item, dict):
                    parsed = _parse_jsonld_item(sub_item, base_url)
                    if parsed:
                        if isinstance(parsed, list):
                            events.extend(parsed)
                        else:
                            events.append(parsed)
            return events if events else None
        return None
    
    # Extract event fields
    event = {}
    
    # Title/Name
    event['title'] = item.get('name') or item.get('title') or item.get('headline', '')
    
    # URL
    url = item.get('url') or item.get('sameAs') or item.get('@id', '')
    if url:
        if not url.startswith('http'):
            url = urljoin(base_url, url)
        event['url'] = url
    
    # Dates
    start_date = item.get('startDate') or item.get('datePublished') or item.get('date')
    if start_date:
        parsed_date = _parse_iso_date(start_date)
        if parsed_date:
            event['date_iso'] = parsed_date
            event['date_text'] = start_date
    
    end_date = item.get('endDate')
    if end_date:
        parsed_end = _parse_iso_date(end_date)
        if parsed_end:
            event['end_date_iso'] = parsed_end
    
    # Location
    location = item.get('location')
    if location:
        if isinstance(location, dict):
            location_name = location.get('name') or location.get('address', {}).get('addressLocality', '')
            if location_name:
                event['location'] = location_name
        elif isinstance(location, str):
            event['location'] = location
    
    # Organizer
    organizer = item.get('organizer')
    if organizer:
        if isinstance(organizer, dict):
            organizer_name = organizer.get('name') or organizer.get('legalName', '')
            if organizer_name:
                event['organizer'] = organizer_name
        elif isinstance(organizer, str):
            event['organizer'] = organizer
    
    # Description
    description = item.get('description') or item.get('about', '')
    if description:
        event['description'] = description[:500]  # Limit length
    
    # Only return if we have at least title and URL
    if event.get('title') and event.get('url'):
        return event
    
    return None


def _extract_microdata_events(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """Extract events from microdata (itemtype="Event")."""
    events = []
    
    # Find all elements with Event itemtype
    event_elements = soup.find_all(attrs={'itemtype': re.compile(r'.*Event', re.I)})
    
    for elem in event_elements:
        event = {}
        
        # Title
        name_elem = elem.find(attrs={'itemprop': 'name'})
        if name_elem:
            event['title'] = name_elem.get_text(strip=True) or name_elem.get('content', '')
        
        # URL
        url_elem = elem.find(attrs={'itemprop': 'url'})
        if url_elem:
            url = url_elem.get('href') or url_elem.get('content', '')
            if url:
                if not url.startswith('http'):
                    url = urljoin(base_url, url)
                event['url'] = url
        
        # Start date
        start_date_elem = elem.find(attrs={'itemprop': 'startDate'})
        if start_date_elem:
            start_date = start_date_elem.get('datetime') or start_date_elem.get('content') or start_date_elem.get_text(strip=True)
            if start_date:
                parsed = _parse_iso_date(start_date)
                if parsed:
                    event['date_iso'] = parsed
                    event['date_text'] = start_date
        
        # Location
        location_elem = elem.find(attrs={'itemprop': 'location'})
        if location_elem:
            location_name = location_elem.find(attrs={'itemprop': 'name'})
            if location_name:
                event['location'] = location_name.get_text(strip=True)
        
        # Only return if we have title and URL
        if event.get('title') and event.get('url'):
            events.append(event)
    
    return events


def _extract_meta_events(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """Extract events from meta tags (og:event, schema.org meta)."""
    events = []
    
    # Look for og:event meta tags
    og_type = soup.find('meta', attrs={'property': 'og:type'})
    if og_type and og_type.get('content', '').lower() == 'event':
        event = {}
        
        # Title
        og_title = soup.find('meta', attrs={'property': 'og:title'})
        if og_title:
            event['title'] = og_title.get('content', '')
        
        # URL
        og_url = soup.find('meta', attrs={'property': 'og:url'})
        if og_url:
            url = og_url.get('content', '')
            if not url.startswith('http'):
                url = urljoin(base_url, url)
            event['url'] = url
        
        # Date
        og_start = soup.find('meta', attrs={'property': 'og:event:start_time'})
        if og_start:
            start_date = og_start.get('content', '')
            parsed = _parse_iso_date(start_date)
            if parsed:
                event['date_iso'] = parsed
                event['date_text'] = start_date
        
        if event.get('title') and event.get('url'):
            events.append(event)
    
    return events


def _parse_iso_date(date_str: str) -> Optional[str]:
    """Parse ISO date string to UTC ISO format."""
    if not date_str:
        return None
    
    try:
        # Try ISO format first
        if 'T' in date_str or 'Z' in date_str or '+' in date_str:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        else:
            # Try dateutil parser
            dt = date_parser.parse(date_str, fuzzy=True)
        
        # Guardrail: reject implausible years
        if dt.year < 2000 or dt.year > 2100:
            return None
        
        # Normalize to UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        
        return dt.isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def is_future_event(event: Dict) -> bool:
    """Check if event is in the future."""
    date_iso = event.get('date_iso')
    if not date_iso:
        return False
    
    try:
        dt = datetime.fromisoformat(date_iso.replace('Z', '+00:00'))
        return dt > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False
