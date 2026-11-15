"""
Structured date extraction from detail pages.

Prioritizes structured formats (JSON-LD, time[datetime], meta tags) before fuzzy parsing.
"""
import json
import re
from typing import Optional, Dict
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from dateutil import parser as date_parser


def extract_date_from_detail_page(html: str, url: str = None) -> Optional[Dict]:
    """
    Extract date from a detail page using structured formats.
    
    Priority order:
    1. JSON-LD Event.startDate
    2. time[datetime]
    3. meta[itemprop="startDate"]
    4. meta[property*="date"]
    5. Common date classes (.date, .event-date)
    
    Returns:
        {
            'date_iso': ISO datetime string or None,
            'date_text': Raw date text or None,
            'source': 'jsonld'|'time_datetime'|'meta_itemprop'|'meta_property'|'class_date'|None
        }
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Priority 1: JSON-LD Event.startDate
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if not isinstance(data, list):
                data = [data]
            
            for item in data:
                if isinstance(item, dict):
                    # Handle @graph
                    if '@graph' in item:
                        item = item['@graph']
                        if not isinstance(item, list):
                            item = [item]
                    
                    for event_item in (item if isinstance(item, list) else [item]):
                        if not isinstance(event_item, dict):
                            continue
                        
                        # Check if it's an Event
                        event_type = event_item.get('@type', '')
                        if isinstance(event_type, list):
                            event_type = ' '.join(event_type)
                        
                        if 'Event' in event_type:
                            start_date = event_item.get('startDate') or event_item.get('datePublished')
                            if start_date:
                                parsed = _parse_iso_date(start_date)
                                if parsed:
                                    return {
                                        'date_iso': parsed,
                                        'date_text': start_date,
                                        'source': 'jsonld'
                                    }
        except (json.JSONDecodeError, KeyError, AttributeError):
            continue
    
    # Priority 2: time[datetime]
    time_elem = soup.find('time', datetime=True)
    if time_elem:
        datetime_attr = time_elem.get('datetime')
        if datetime_attr:
            parsed = _parse_iso_date(datetime_attr)
            if parsed:
                return {
                    'date_iso': parsed,
                    'date_text': datetime_attr,
                    'source': 'time_datetime'
                }
    
    # Priority 3: meta[itemprop="startDate"]
    meta_startdate = soup.find('meta', attrs={'itemprop': 'startDate'})
    if meta_startdate:
        content = meta_startdate.get('content') or meta_startdate.get('datetime')
        if content:
            parsed = _parse_iso_date(content)
            if parsed:
                return {
                    'date_iso': parsed,
                    'date_text': content,
                    'source': 'meta_itemprop'
                }
    
    # Priority 4: meta[property*="date"]
    for meta in soup.find_all('meta', attrs={'property': re.compile(r'.*date', re.I)}):
        content = meta.get('content')
        if content:
            parsed = _parse_iso_date(content)
            if parsed:
                return {
                    'date_iso': parsed,
                    'date_text': content,
                    'source': 'meta_property'
                }
    
    # Priority 5: Common date classes
    date_classes = ['.date', '.event-date', '.start-date', '.event-start-date', '[class*="date"]']
    for selector in date_classes:
        date_elem = soup.select_one(selector)
        if date_elem:
            # Try datetime attribute first
            datetime_attr = date_elem.get('datetime')
            if datetime_attr:
                parsed = _parse_iso_date(datetime_attr)
                if parsed:
                    return {
                        'date_iso': parsed,
                        'date_text': datetime_attr,
                        'source': 'class_date'
                    }
            
            # Fallback to text content
            date_text = date_elem.get_text(strip=True)
            if date_text and len(date_text) < 100:  # Reasonable date length
                parsed = _parse_fuzzy_date(date_text)
                if parsed:
                    return {
                        'date_iso': parsed,
                        'date_text': date_text,
                        'source': 'class_date'
                    }
    
    return {
        'date_iso': None,
        'date_text': None,
        'source': None
    }


def _parse_iso_date(date_str: str) -> Optional[str]:
    """Parse ISO date string to ISO format."""
    if not date_str:
        return None
    
    try:
        # Try ISO format first
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        
        # Guardrail: reject implausible years
        if dt.year < 2000 or dt.year > 2100:
            return None
        
        # Normalize to UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


def _parse_fuzzy_date(date_str: str) -> Optional[str]:
    """Parse fuzzy date string using dateutil."""
    if not date_str:
        return None
    
    try:
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
