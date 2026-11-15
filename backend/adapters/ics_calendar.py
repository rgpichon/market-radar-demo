"""
iCalendar (ICS) adapter for event extraction.
"""
import requests
from icalendar import Calendar
from datetime import datetime, timezone
import sys
from pathlib import Path

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.json_utils import ensure_list
from utils.enrich import enrich_event
from utils.events_only import should_reject_as_article


def extract_events(ics_url, source_config, return_stats=False):
    """
    Extract events from iCalendar feed.
    
    Args:
        ics_url: URL of the ICS calendar file
        source_config: Source configuration dict with:
            - firm_name: Firm name
            - default_tags_json: List of default tags
            - enforce_events_only: bool (default True)
        return_stats: If True, return extraction stats
    
    Returns:
        list: List of event dicts, or (events, stats) if return_stats=True
    """
    try:
        response = requests.get(ics_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        
        # Check content type (should be calendar/ics or text/calendar)
        content_type = response.headers.get('Content-Type', '').lower()
        if 'calendar' not in content_type and 'ics' not in content_type:
            # Not a hard failure, but log it
            pass
        
        ics_data = response.text
    except requests.RequestException as e:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'feed_http_error': 1}}
        return []
    except Exception as e:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'feed_http_error': 1}}
        return []
    
    try:
        cal = Calendar.from_ical(ics_data)
    except Exception as e:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'feed_parse_error': 1}}
        return []
    
    events = []
    rejected = {}
    raw_count = 0
    
    firm_name = source_config.get('firm_name', '')
    default_tags = ensure_list(source_config.get('default_tags_json', []))
    enforce_events_only = source_config.get('enforce_events_only', True)
    
    for component in cal.walk():
        if component.name == 'VEVENT':
            raw_count += 1
            
            # Extract SUMMARY (title)
            summary = component.get('SUMMARY')
            if not summary:
                rejected['no_summary'] = rejected.get('no_summary', 0) + 1
                continue
            
            title = str(summary).strip()
            if not title:
                rejected['empty_summary'] = rejected.get('empty_summary', 0) + 1
                continue
            
            # Extract URL (link)
            link = None
            url_comp = component.get('URL')
            if url_comp:
                link = str(url_comp).strip()
            
            # Extract DTSTART (date)
            dtstart = component.get('DTSTART')
            date_time = None
            if dtstart:
                dt = dtstart.dt
                # Handle both date and datetime
                if isinstance(dt, datetime):
                    # Already a datetime
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    date_time = dt.isoformat()
                else:
                    # Date-only, convert to midnight UTC
                    dt = datetime.combine(dt, datetime.min.time())
                    dt = dt.replace(tzinfo=timezone.utc)
                    date_time = dt.isoformat()
            
            # Use URL as link if available, otherwise None
            if not link:
                link = ''
            
            # Check events-only policy
            if should_reject_as_article(title, link, enforce_events_only):
                rejected['article_like'] = rejected.get('article_like', 0) + 1
                continue
            
            # Extract DESCRIPTION for enrichment
            description = ''
            desc_comp = component.get('DESCRIPTION')
            if desc_comp:
                description = str(desc_comp)
            
            # Build event dict
            event = {
                'firm_name': firm_name,
                'event_name': title,
                'link': link if link else None,
                'date_time': date_time,
                'tags': list(default_tags),
                'raw_date_text': ''
            }
            
            # Enrich with format and tags
            if description:
                event = enrich_event(event, extra_text=description)
            else:
                event = enrich_event(event)
            
            events.append(event)
    
    if return_stats:
        stats = {
            'raw': raw_count,
            'kept': len(events),
            'rejected': rejected
        }
        return events, stats
    
    return events
