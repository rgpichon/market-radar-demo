import json
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.normalize import normalize_string, normalize_url
from utils.dates import parse_date
from utils.json_utils import ensure_list


def extract_events(html, source_config):
    """
    Extract events from JSON-LD structured data.
    
    Args:
        html: HTML content as string
        source_config: dict with url and firm_name
    
    Returns:
        List of dicts with keys: firm_name, event_name, date_time, link, tags
    """
    soup = BeautifulSoup(html, 'html.parser')
    firm_name = source_config.get('firm_name', '')
    default_tags = ensure_list(source_config.get('default_tags_json'))
    base_url = source_config.get('url', '')
    
    # Find all script tags with type="application/ld+json"
    script_tags = soup.find_all('script', type='application/ld+json')
    events = []
    
    for script in script_tags:
        try:
            data = json.loads(script.string)
            
            # Handle both single objects and arrays
            if isinstance(data, dict):
                data = [data]
            elif not isinstance(data, list):
                continue
            
            for item in data:
                # Check if it's an Event (handle both @type formats)
                event_type = item.get('@type', '')
                if isinstance(event_type, list):
                    event_type = event_type[0] if event_type else ''
                
                is_event = (
                    event_type == 'Event' or 
                    event_type == 'http://schema.org/Event' or
                    event_type == 'https://schema.org/Event'
                )
                
                if not is_event:
                    # Check nested events (e.g., in ItemList)
                    if '@type' in item and 'itemListElement' in item:
                        for list_item in item.get('itemListElement', []):
                            if isinstance(list_item, dict) and 'item' in list_item:
                                nested_item = list_item.get('item', {})
                                nested_type = nested_item.get('@type', '')
                                if nested_type == 'Event' or 'Event' in str(nested_type):
                                    # Recursively process nested event
                                    events.extend(extract_events_from_item(nested_item, firm_name, default_tags, base_url))
                    continue
                
                # Extract event data
                event_data = extract_events_from_item(item, firm_name, default_tags, base_url)
                events.extend(event_data)
                
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            # Skip invalid JSON-LD
            continue
    
    return events


def extract_events_from_item(item, firm_name, default_tags, base_url):
    """Extract event data from a single JSON-LD item."""
    events = []
    
    try:
        # Extract name/title
        event_name = None
        if 'name' in item:
            event_name = normalize_string(str(item['name']))
        elif 'headline' in item:
            event_name = normalize_string(str(item['headline']))
        elif 'title' in item:
            event_name = normalize_string(str(item['title']))
        
        if not event_name:
            return []
        
        # Extract link
        link = None
        if 'url' in item:
            link = normalize_url(str(item['url']), base_url)
        elif 'sameAs' in item:
            if isinstance(item['sameAs'], list):
                link = normalize_url(str(item['sameAs'][0]), base_url) if item['sameAs'] else None
            else:
                link = normalize_url(str(item['sameAs']), base_url)
        elif 'mainEntityOfPage' in item:
            if isinstance(item['mainEntityOfPage'], dict) and '@id' in item['mainEntityOfPage']:
                link = normalize_url(str(item['mainEntityOfPage']['@id']), base_url)
            elif isinstance(item['mainEntityOfPage'], str):
                link = normalize_url(item['mainEntityOfPage'], base_url)
        
        if not link:
            return []
        
        # Extract date
        date_time = None
        if 'startDate' in item:
            date_time = parse_date(str(item['startDate']))
        elif 'datePublished' in item:
            date_time = parse_date(str(item['datePublished']))
        elif 'date' in item:
            date_time = parse_date(str(item['date']))
        
        events.append({
            'firm_name': firm_name,
            'event_name': event_name,
            'date_time': date_time,
            'link': link,
            'tags': default_tags
        })
    except (KeyError, TypeError, AttributeError):
        pass
    
    return events
