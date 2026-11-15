"""
Calendar generation for events (iCal format).

Generates iCal files for event export and subscription.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from icalendar import Calendar, Event as ICalEvent
    ICALENDAR_AVAILABLE = True
except ImportError:
    ICALENDAR_AVAILABLE = False
    Calendar = None
    ICalEvent = None


def create_ical_event(event: Dict) -> ICalEvent:
    """
    Create iCal Event from event dict.
    
    Args:
        event: Event dict with event details
    
    Returns:
        ICalEvent object
    """
    if not ICALENDAR_AVAILABLE:
        raise ImportError("icalendar package not available")
    
    ical_event = ICalEvent()
    
    # Required fields
    ical_event.add('summary', event.get('event_name', 'Event'))
    ical_event.add('uid', event.get('id', f"event-{hash(str(event))}"))
    
    # Description
    description_parts = []
    if event.get('firm_name'):
        description_parts.append(f"Organizer: {event.get('firm_name')}")
    if event.get('description'):
        description_parts.append(event.get('description'))
    if event.get('link'):
        description_parts.append(f"Link: {event.get('link')}")
    
    if description_parts:
        ical_event.add('description', '\n\n'.join(description_parts))
    
    # Date/time
    date_time_str = event.get('date_time')
    if date_time_str:
        try:
            # Parse ISO date
            if date_time_str.endswith('Z'):
                date_time_str = date_time_str[:-1] + '+00:00'
            dt = datetime.fromisoformat(date_time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            ical_event.add('dtstart', dt)
            # Assume 1-hour duration if not specified
            ical_event.add('dtend', dt + timedelta(hours=1))
        except (ValueError, TypeError):
            pass
    
    # Location
    location_parts = []
    if event.get('location_city'):
        location_parts.append(event.get('location_city'))
    if event.get('location_country'):
        location_parts.append(event.get('location_country'))
    if event.get('format'):
        location_parts.append(f"({event.get('format')})")
    
    if location_parts:
        ical_event.add('location', ', '.join(location_parts))
    
    # URL
    if event.get('link'):
        ical_event.add('url', event.get('link'))
    
    # Tags as categories
    tags = event.get('tags', [])
    if isinstance(tags, str):
        import json
        try:
            tags = json.loads(tags)
        except:
            tags = []
    if tags:
        ical_event.add('categories', tags)
    
    return ical_event


def create_ical_calendar(events: List[Dict], calendar_name: str = "Market Radar Events") -> Calendar:
    """
    Create iCal Calendar from list of events.
    
    Args:
        events: List of event dicts
        calendar_name: Calendar name
    
    Returns:
        Calendar object
    """
    if not ICALENDAR_AVAILABLE:
        raise ImportError("icalendar package not available")
    
    cal = Calendar()
    cal.add('prodid', '-//Market Radar//Event Calendar//EN')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('x-wr-calname', calendar_name)
    
    for event in events:
        try:
            ical_event = create_ical_event(event)
            cal.add_component(ical_event)
        except Exception as e:
            print(f"Error creating iCal event: {e}")
            continue
    
    return cal


def export_ical_file(events: List[Dict], filepath: str, calendar_name: str = "Market Radar Events"):
    """
    Export events to iCal file.
    
    Args:
        events: List of event dicts
        filepath: Path to save .ics file
        calendar_name: Calendar name
    """
    cal = create_ical_calendar(events, calendar_name)
    
    with open(filepath, 'wb') as f:
        f.write(cal.to_ical())
