"""
ICS Harvester - Phase 2

Detects and parses ICS calendar files from detail pages.
ICS files often contain clean, accurate event dates.
"""
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests
from icalendar import Calendar
from datetime import datetime, timezone


def find_ics_links(html: str, base_url: str) -> List[str]:
    """
    Find ICS calendar links in HTML (enhanced version).
    
    Looks for:
    - Links ending in .ics
    - Links with 'calendar', 'ical', 'add-to-calendar' in href/text
    - webcal:// URLs
    - Common query params: ?ical=1, ?download=ics, /ical/, /ics/, /calendar/
    - Button text: "Add to calendar", "Add to Outlook", "iCal", "ICS", etc.
    """
    soup = BeautifulSoup(html, 'html.parser')
    ics_links = []
    seen = set()
    
    # Calendar-related keywords (expanded)
    calendar_keywords = [
        'add to calendar', 'add to outlook', 'ical', 'ics', 'add to iphone',
        'google calendar', 'download calendar', 'calendar download', 'export calendar',
        'add-to-calendar', 'download-calendar'
    ]
    
    # Find all links and buttons
    for elem in soup.find_all(['a', 'button'], href=True):
        href = elem.get('href', '')
        if not href:
            continue
        
        href_lower = href.lower()
        text = elem.get_text(strip=True).lower()
        
        # Check for .ics extension
        if href_lower.endswith('.ics'):
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                ics_links.append(full_url)
            continue
        
        # Check for calendar keywords in text or href
        if any(kw in text for kw in calendar_keywords) or any(kw in href_lower for kw in calendar_keywords):
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                ics_links.append(full_url)
            continue
        
        # Check for common query params and paths
        ics_params = ['?ical=', '?download=ics', '?format=ics', '/ical/', '/ics/', '/calendar/', '/add-to-calendar/']
        if any(param in href_lower for param in ics_params):
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                ics_links.append(full_url)
    
    # Check for webcal:// URLs
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if href.lower().startswith('webcal://'):
            https_url = href.replace('webcal://', 'https://')
            if https_url not in seen:
                seen.add(https_url)
                ics_links.append(https_url)
    
    return ics_links


def parse_ics_file(ics_url: str, timeout: int = 10) -> Optional[Dict]:
    """
    Fetch and parse an ICS file.
    
    Returns:
        {
            'url': str,
            'events': List[Dict],  # Parsed events
            'count': int
        }
    """
    try:
        response = requests.get(ics_url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            return None
        
        # Check content type (but be lenient - some servers don't set it correctly)
        content_type = response.headers.get('Content-Type', '').lower()
        content_starts_with_ics = response.text.strip().startswith('BEGIN:VCALENDAR')
        
        # Accept if content-type indicates calendar OR content looks like ICS
        if 'calendar' not in content_type and 'text/calendar' not in content_type:
            if not content_starts_with_ics:
                return None
        
        # Parse ICS
        cal = Calendar.from_ical(response.text)
        events = []
        
        for component in cal.walk():
            if component.name == 'VEVENT':
                event = {}
                
                # Title/Summary
                summary = component.get('summary')
                if summary:
                    event['title'] = str(summary)
                
                # URL
                url = component.get('url')
                if url:
                    event['url'] = str(url)
                
                # Start date
                dtstart = component.get('dtstart')
                if dtstart:
                    dt = dtstart.dt
                    if isinstance(dt, datetime):
                        # Normalize to UTC
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        else:
                            dt = dt.astimezone(timezone.utc)
                        event['date_iso'] = dt.isoformat()
                
                # End date
                dtend = component.get('dtend')
                if dtend:
                    dt = dtend.dt
                    if isinstance(dt, datetime):
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        else:
                            dt = dt.astimezone(timezone.utc)
                        event['end_date_iso'] = dt.isoformat()
                
                # Location
                location = component.get('location')
                if location:
                    event['location'] = str(location)
                
                # Description
                description = component.get('description')
                if description:
                    event['description'] = str(description)[:500]
                
                # Only add if we have title and date
                if event.get('title') and event.get('date_iso'):
                    events.append(event)
        
        return {
            'url': ics_url,
            'events': events,
            'count': len(events)
        }
    except Exception:
        return None


def harvest_ics_from_detail_page(html: str, detail_url: str) -> Optional[Dict]:
    """
    Find and parse ICS files from a detail page.
    
    Returns the first valid ICS file found, or None.
    """
    ics_links = find_ics_links(html, detail_url)
    
    for ics_url in ics_links:
        parsed = parse_ics_file(ics_url)
        if parsed and parsed['count'] > 0:
            return parsed
    
    return None
