from bs4 import BeautifulSoup
import requests
import sys
import re
from pathlib import Path
from urllib.parse import urlparse

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.normalize import normalize_string, normalize_url
from utils.dates import parse_date
from utils.json_utils import ensure_dict, ensure_list
from utils.event_filter import is_event_like
from utils.postprocess import apply_postprocess, get_rejection_reason


def is_navigation_link(href):
    """Check if a link looks like navigation/social/share, not an event link."""
    if not href:
        return True
    
    href_lower = href.lower()
    
    # Skip anchors, javascript, mailto, tel
    if href_lower.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
        return True
    
    # Skip common social/tracking patterns
    social_domains = ['facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com', 
                     'youtube.com', 'share', 'print', 'email']
    if any(domain in href_lower for domain in social_domains):
        return True
    
    # Skip common navigation/policy pages
    nav_paths = ['/accessibility', '/privacy', '/terms', '/policy', '/about', '/contact',
                 '/sitemap', '/cookie', '/legal', '/policies', '/website', '/linking']
    if any(path in href_lower for path in nav_paths):
        return True
    
    return False


def is_valid_event_title(title):
    """Check if title looks like a real event, not navigation text."""
    if not title or len(title) < 10:
        return False
    
    title_lower = title.lower().strip()
    
    # Skip common navigation phrases
    nav_phrases = ['read more', 'learn more', 'register', 'sign up', 'view all', 
                   'see more', 'click here', 'more info', 'details', 'privacy notice',
                   'privacy policy', 'accessibility', 'website policies', 'español',
                   'no fear act', 'budget & performance', 'cookie policy', 'terms of use']
    if any(phrase in title_lower for phrase in nav_phrases):
        return False
    
    # Skip very short titles that are likely navigation
    if len(title.strip()) < 15 and title_lower in ['upcoming events', 'past events', 'event recordings']:
        return False
    
    return True


def extract_title_from_element(item, title_elem, link_elem, source_config):
    """
    Extract title using configurable strategy.
    Supports: text content, title attribute, aria-label.
    """
    title_extraction = ensure_dict(source_config.get('title_extraction'))
    mode = title_extraction.get('mode', 'selector')
    title_attr = title_extraction.get('title_attr', 'text')
    
    event_name = None
    
    # Try to get title from specified attribute on link element first
    if title_attr != 'text' and link_elem:
        attr_value = link_elem.get(title_attr)
        if attr_value and len(attr_value.strip()) > 5:
            event_name = normalize_string(attr_value)
    
    # If no title from attribute, try title element text
    if not event_name and title_elem:
        event_name = normalize_string(title_elem.get_text())
    
    # Fallback: try link's title attribute if we haven't already
    if not event_name and link_elem and title_attr == 'text':
        title_attr_val = link_elem.get('title')
        if title_attr_val and len(title_attr_val.strip()) > 5:
            event_name = normalize_string(title_attr_val)
    
    # Fallback: try aria-label
    if not event_name and link_elem:
        aria_label = link_elem.get('aria-label')
        if aria_label and len(aria_label.strip()) > 5:
            event_name = normalize_string(aria_label)
    
    return event_name


def extract_events(html, source_config, return_stats=False):
    """
    Extract events from HTML using CSS selectors.
    
    Args:
        html: HTML content as string
        source_config: dict with selectors_json and url
        return_stats: if True, return (events, stats_dict) instead of just events
    
    Returns:
        List of dicts with keys: firm_name, event_name, date_time, link, tags
        OR (events_list, stats_dict) if return_stats=True
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Use ensure_dict/ensure_list to handle JSON stored as strings
    selectors = ensure_dict(source_config.get('selectors_json'))
    firm_name = source_config.get('firm_name', '')
    default_tags = ensure_list(source_config.get('default_tags_json'))
    base_url = source_config.get('url', '')
    
    item_selector = selectors.get('item_selector')
    if not item_selector:
        return ([], {'raw': 0, 'kept': 0, 'rejected': {}}) if return_stats else []
    
    items = soup.select(item_selector)
    events = []
    
    # Stats tracking
    stats = {
        'raw': len(items),
        'kept': 0,
        'rejected': {}  # reason -> count
    }
    
    def reject(reason):
        stats['rejected'][reason] = stats['rejected'].get(reason, 0) + 1
    
    for item in items:
        try:
            # Extract title with fallbacks
            title_selector = selectors.get('title_selector')
            title_elem = None
            link_elem = None
            event_name = None
            
            if title_selector:
                title_elem = item.select_one(title_selector)
            
            # Find primary link element early (needed for title extraction)
            link_selector = selectors.get('link_selector')
            if link_selector:
                link_elem = item.select_one(link_selector)
            if not link_elem and title_elem:
                link_elem = title_elem.find('a', href=True) or title_elem if title_elem.name == 'a' else None
            if not link_elem:
                link_elem = item.select_one('a[href]')
            
            # Fallback for title_elem: find first heading if title_selector didn't work
            if not title_elem:
                for heading in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    title_elem = item.find(heading)
                    if title_elem:
                        break
            
            # Extract title using configurable strategy
            event_name = extract_title_from_element(item, title_elem, link_elem, source_config)
            
            # Validate title
            if not event_name:
                reject('no_title')
                continue
                
            if not is_valid_event_title(event_name):
                reject('invalid_title')
                continue
            
            # Extract link with multiple fallbacks
            link = None
            
            # Try 1: Use link_selector if provided
            if link_selector:
                link_elem_sel = item.select_one(link_selector)
                if link_elem_sel and link_elem_sel.get('href'):
                    href = link_elem_sel.get('href')
                    if not is_navigation_link(href):
                        link = normalize_url(href, base_url)
            
            # Try 2: Find link in title element
            if not link and title_elem:
                link_in_title = title_elem.find('a', href=True)
                if link_in_title:
                    href = link_in_title.get('href')
                    if not is_navigation_link(href):
                        link = normalize_url(href, base_url)
            
            # Try 3: Use link_elem found earlier
            if not link and link_elem and link_elem.get('href'):
                href = link_elem.get('href')
                if not is_navigation_link(href):
                    link = normalize_url(href, base_url)
            
            # Try 4: Find first valid <a href> in item (skip nav links)
            if not link:
                all_links = item.find_all('a', href=True)
                for lnk in all_links:
                    href = lnk.get('href')
                    if not is_navigation_link(href):
                        link = normalize_url(href, base_url)
                        break
            
            # Skip if no link found (link is required)
            if not link:
                reject('no_link')
                continue
            
            # Extract date (optional) with fallbacks
            date_time = None
            raw_date_text = ""  # Keep raw text for event filtering
            date_selector = selectors.get('date_selector')
            
            if date_selector:
                date_elem = item.select_one(date_selector)
                if date_elem:
                    # Try datetime attribute first
                    datetime_attr = date_elem.get('datetime')
                    if datetime_attr:
                        raw_date_text = datetime_attr
                        date_time = parse_date(datetime_attr)
                    else:
                        # Parse text content
                        date_str = date_elem.get_text()
                        raw_date_text = date_str
                        date_time = parse_date(date_str)
            
            # Fallback: look for <time> element
            if not date_time:
                time_elem = item.find('time')
                if time_elem:
                    datetime_attr = time_elem.get('datetime')
                    if datetime_attr:
                        raw_date_text = raw_date_text or datetime_attr
                        date_time = parse_date(datetime_attr)
                    else:
                        date_str = time_elem.get_text()
                        raw_date_text = raw_date_text or date_str
                        date_time = parse_date(date_str)
            
            # Build event dict
            event = {
                'firm_name': firm_name,
                'event_name': event_name,
                'date_time': date_time,
                'link': link,
                'tags': default_tags
            }
            
            # Apply event-likeness filter (skip news/press releases)
            if not is_event_like(event_name, link, raw_date_text):
                reject('not_event_like')
                continue
            
            # Apply per-source post-processing rules
            event = apply_postprocess(event, source_config)
            if event is None:
                # Get specific rejection reason for logging
                reason = get_rejection_reason({
                    'event_name': event_name,
                    'link': link,
                    'date_time': date_time
                }, source_config)
                reject(reason or 'postprocess_rejected')
                continue
            
            events.append(event)
            stats['kept'] += 1
            
        except Exception as e:
            reject('parse_error')
            continue
    
    if return_stats:
        return (events, stats)
    return events


def fetch_detail_title(url, title_selector="h1", timeout=10):
    """
    Fetch a detail page and extract the title.
    Used for sources where the listing page only shows dates.
    """
    try:
        response = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title_elem = soup.select_one(title_selector)
        if title_elem:
            return normalize_string(title_elem.get_text())
        
        # Fallback to page title
        page_title = soup.find('title')
        if page_title:
            return normalize_string(page_title.get_text())
        
        return None
    except Exception:
        return None


def extract_events_with_detail_fetch(html, source_config):
    """
    Extract events and optionally fetch detail pages for titles.
    Used for sources like CEPR where listing shows only dates.
    """
    detail_fetch = ensure_dict(source_config.get('detail_fetch'))
    
    # First do normal extraction
    events, stats = extract_events(html, source_config, return_stats=True)
    
    # If detail_fetch is enabled, fetch titles from detail pages
    if detail_fetch.get('enabled', False):
        limit = detail_fetch.get('limit', 20)
        title_selector = detail_fetch.get('title_selector', 'h1')
        
        detail_fetched = 0
        for event in events[:limit]:
            if event.get('link'):
                detail_title = fetch_detail_title(
                    event['link'], 
                    title_selector=title_selector
                )
                if detail_title and len(detail_title) > len(event.get('event_name', '')):
                    event['event_name'] = detail_title
                    detail_fetched += 1
        
        stats['detail_fetched'] = detail_fetched
    
    return events, stats
