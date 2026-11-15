"""
Events-only policy enforcement.
Rejects items that look like articles, press releases, or blog posts.
"""


def should_reject_as_article(title, link, enforce_events_only=True):
    """
    Check if an item should be rejected as an article (not an event).
    Uses URL-based allowlists to prefer event-like URLs.
    
    Args:
        title: Event title string
        link: Event URL string
        enforce_events_only: If False, skip automatic rejection (default: True)
    
    Returns:
        bool: True if should be rejected, False if should be kept
    """
    if not enforce_events_only:
        return False
    
    if not title:
        return False
    
    title_lower = title.lower()
    link_lower = (link or '').lower()
    
    # URL-based allowlist: if URL contains event-like patterns, allow it
    event_url_patterns = [
        '/events/',
        '/event/',
        '/webinar',
        '/seminar',
        '/conference',
        '/calendar',
        '/registration',
        '/event-',
        '/events-',
        '/upcoming-events',
        '/event-calendar'
    ]
    
    # Check allowlist first - if URL looks like an event, allow it
    for pattern in event_url_patterns:
        if pattern in link_lower:
            return False  # Allow event-like URLs even if title might look article-like
    
    # Article-like URL patterns (reject unless overridden by allowlist above)
    article_url_patterns = [
        '/news/',
        '/blog/',
        '/press/',
        '/articles/',
        '/announcements/',
        '/statements/',
        '/commentary/',
        '/insights/',
        '/publication',
        '/publications/',
        '/press-release',
        '/press-releases/'
    ]
    
    for pattern in article_url_patterns:
        if pattern in link_lower:
            return True  # Reject article-like URLs
    
    # Strong article indicators in title (only if URL doesn't indicate event)
    article_indicators = [
        'press release',
        'blog',
        'op-ed',
        'podcast',
        'article',
        'news:',
        'announcement:',
        'statement on',
        'remarks on',
        'commentary',
        'editorial',
        'publication',
        'insight:',
        'analysis:'
    ]
    
    # Check if title indicates event (allow if so)
    event_title_indicators = [
        'event',
        'webinar',
        'seminar',
        'conference',
        'workshop',
        'meeting',
        'session',
        'calendar'
    ]
    
    has_event_indicator = any(indicator in title_lower for indicator in event_title_indicators)
    
    for indicator in article_indicators:
        if indicator in title_lower:
            # If title has both article and event indicators, prefer event
            if has_event_indicator:
                continue
            return True
    
    return False
