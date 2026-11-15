"""
Event-likeness filter to exclude news/press releases from the feed.
Conservative: better to miss some events than to include non-events.
"""

import re


def normalize_text(s):
    """Lowercase and collapse whitespace."""
    if not s:
        return ""
    return re.sub(r'\s+', ' ', str(s).lower().strip())


def is_event_like(title, link, date_text=None):
    """
    Determine if an item looks like an event/webinar rather than news/press release.
    
    Returns True if the item is likely an event, False otherwise.
    Conservative: returns False if uncertain.
    """
    if not title:
        return False
    
    title_norm = normalize_text(title)
    link_norm = normalize_text(link or "")
    date_norm = normalize_text(date_text or "")
    
    # Skip nav-like / generic titles
    nav_phrases = [
        'read more', 'learn more', 'register now', 'sign up', 'view all',
        'see more', 'click here', 'more info', 'details', 'privacy',
        'accessibility', 'español', 'contact', 'home', 'about us',
        'terms of use', 'cookie', 'legal', 'sitemap', 'subscribe',
        'follow us', 'share this', 'print', 'email this'
    ]
    if any(phrase in title_norm for phrase in nav_phrases):
        return False
    
    # Skip very short titles (likely navigation)
    if len(title_norm) < 8:
        return False
    
    # Event keywords in title - strong signal
    event_keywords = [
        'webinar', 'webcast', 'event', 'conference', 'seminar', 
        'workshop', 'briefing', 'symposium', 'roundtable', 'summit',
        'talk', 'lecture', 'forum', 'meeting', 'session', 'training',
        'course', 'masterclass', 'presentation', 'panel', 'discussion',
        'q&a', 'q and a', 'live', 'virtual', 'in-person', 'hybrid',
        'registration', 'register', 'rsvp', 'attend', 'join us',
        'upcoming', 'schedule', 'calendar', 'agenda'
    ]
    if any(kw in title_norm for kw in event_keywords):
        return True
    
    # Event-ish paths in URL - strong signal
    event_paths = [
        '/event', '/events', '/webinar', '/webinars', '/seminar', '/seminars',
        '/calendar', '/conference', '/conferences', '/workshop', '/workshops',
        '/training', '/education', '/learn', '/schedule', '/agenda',
        '/registration', '/register', '/rsvp'
    ]
    if any(path in link_norm for path in event_paths):
        return True
    
    # Date text present with reasonable title length - moderate signal
    # (Events usually have dates, news may not show date prominently)
    if date_norm and len(title_norm) > 15:
        # Check if date_text looks like a date (has numbers/month names)
        date_indicators = [
            'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
            'january', 'february', 'march', 'april', 'june', 'july', 'august', 
            'september', 'october', 'november', 'december',
            '2024', '2025', '2026', '2027',
            'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
        ]
        # Also check for numeric patterns like 01/15 or 15-01
        has_date_pattern = bool(re.search(r'\d{1,2}[/\-\.]\d{1,2}', date_norm))
        has_date_word = any(ind in date_norm for ind in date_indicators)
        
        if has_date_pattern or has_date_word:
            return True
    
    # If none of the above, default to False (conservative)
    return False


def filter_events(events):
    """
    Filter a list of event dicts, keeping only event-like items.
    
    Args:
        events: list of dicts with keys: event_name, link, date_time (optional)
    
    Returns:
        Filtered list of events
    """
    filtered = []
    for event in events:
        title = event.get('event_name', '')
        link = event.get('link', '')
        date_text = event.get('raw_date_text', '') or (event.get('date_time') or '')
        
        if is_event_like(title, link, date_text):
            filtered.append(event)
    
    return filtered
