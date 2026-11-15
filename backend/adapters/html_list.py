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
from utils.structured_date_extraction import extract_date_from_detail_page
from utils.ics_harvester import harvest_ics_from_detail_page
from utils.structured_metadata_extractor import extract_structured_events


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
    
    # Reject common navigation patterns
    nav_patterns = ['home', 'back', 'menu', 'skip to', 'jump to', 'go to']
    title_lower = title.lower().strip()
    if any(pattern in title_lower for pattern in nav_patterns):
        return False
    
    return True


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
    base_selectors = ensure_dict(source_config.get('selectors_json'))
    # Apply selector_overrides if present (source-specific patching)
    selector_overrides = ensure_dict(source_config.get('selector_overrides'))
    selectors = {**base_selectors, **selector_overrides} if selector_overrides else base_selectors
    
    firm_name = source_config.get('firm_name', '')
    default_tags = ensure_list(source_config.get('default_tags_json'))
    base_url = source_config.get('url', '')
    
    item_selector = selectors.get('item_selector')
    if not item_selector:
        return ([], {'raw': 0, 'kept': 0, 'rejected': {}}) if return_stats else []
    
    # Phase 5: Try fallback selectors if primary fails (Priority 5, Phase 5)
    items = soup.select(item_selector)
    if not items:
        fallback_selectors = selectors.get('fallback_selectors', [])
        if fallback_selectors:
            try:
                from utils.selector_adaptation import try_fallback_selectors
                items = try_fallback_selectors(html, item_selector, fallback_selectors) or []
            except Exception:
                items = []
    
    if not items:
        return ([], {'raw': 0, 'kept': 0, 'rejected': {'no_items_found': 1}}) if return_stats else []
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
            
            # Extract title using configurable strategy (Phase 4: Graceful Degradation)
            try:
                event_name = extract_title_from_element(item, title_elem, link_elem, source_config)
            except Exception as e:
                # Field-level error handling: log but continue
                event_name = None
            
            # Validate title (required field)
            if not event_name:
                reject('no_title')
                continue
                
            try:
                if not is_valid_event_title(event_name):
                    reject('invalid_title')
                    continue
            except Exception:
                pass
            
            # Extract link
            link = None
            try:
                if link_elem:
                    href = link_elem.get('href')
                    if href and not is_navigation_link(href):
                        link = normalize_url(href, base_url)
                
                # Try 2: Use title element if it's a link
                if not link and title_elem and title_elem.name == 'a':
                    href = title_elem.get('href')
                    if href and not is_navigation_link(href):
                        link = normalize_url(href, base_url)
                
                # Try 3: Find link in item using link_selector
                if not link and link_selector:
                    link_candidates = item.select(link_selector)
                    for lnk in link_candidates:
                        href = lnk.get('href')
                        if href and not is_navigation_link(href):
                            link = normalize_url(href, base_url)
                            break
                
                # Try 4: Find first valid <a href> in item (skip nav links)
                if not link:
                    all_links = item.find_all('a', href=True)
                    for lnk in all_links:
                        href = lnk.get('href')
                        if not is_navigation_link(href):
                            link = normalize_url(href, base_url)
                            break
            except Exception as e:
                # Field-level error handling: link extraction failed
                link = None
            
            # Skip if no link found (link is required)
            if not link:
                reject('no_link')
                continue
            
            # Extract date (optional) with fallbacks (Phase 4: Graceful Degradation)
            date_time = None
            raw_date_text = ""  # Keep raw text for event filtering
            try:
                date_selector = selectors.get('date_selector')
                
                if date_selector:
                    date_elem = item.select_one(date_selector)
                    if date_elem:
                        # Check for configurable date attribute (e.g., 'date', 'data-date')
                        date_attr_name = selectors.get('date_attr', 'datetime')
                        
                        # Try specified attribute first
                        datetime_attr = date_elem.get(date_attr_name)
                        if datetime_attr:
                            raw_date_text = datetime_attr
                            date_time = parse_date(datetime_attr)
                        # Fallback to 'datetime' if different attr was specified but empty
                        elif date_attr_name != 'datetime':
                            datetime_attr = date_elem.get('datetime')
                            if datetime_attr:
                                raw_date_text = datetime_attr
                                date_time = parse_date(datetime_attr)
                        
                        # If no attribute worked, try text content
                        if not date_time:
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
            except Exception as e:
                # Field-level error handling: date extraction failed, but continue with None
                date_time = None
                raw_date_text = ""
            
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


def extract_events_with_detail_fetch(html, source_config):
    """
    Extract events and optionally fetch detail pages for dates.
    Uses structured date extraction (JSON-LD, time[datetime], meta tags) with priority order.
    
    Returns:
        (events, stats) where stats includes detail_date_hit_rate
    """
    detail_fetch = ensure_dict(source_config.get('detail_fetch'))
    
    # First do normal extraction
    events, stats = extract_events(html, source_config, return_stats=True)
    
    # If detail_fetch is enabled, fetch dates from detail pages
    if detail_fetch.get('enabled', False):
        max_fetch = detail_fetch.get('max', 10)
        stop_after_first_valid = detail_fetch.get('stop_after_first_valid', False)
        
        detail_fetched = 0
        detail_dates_found = 0
        
        for event in events[:max_fetch]:
            if not event.get('link'):
                continue
            
            # Skip if already has date
            if event.get('date_time'):
                continue
            
            try:
                response = requests.get(event['link'], timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }, allow_redirects=True)
                
                if response.status_code == 200:
                    html = response.text
                    
                    # Priority 1: Try ICS harvesting (most reliable)
                    if detail_fetch.get('harvest_ics', False):
                        ics_result = harvest_ics_from_detail_page(html, event['link'])
                        if ics_result and ics_result['count'] > 0:
                            ics_event = ics_result['events'][0]
                            if ics_event.get('date_iso'):
                                event['date_time'] = ics_event['date_iso']
                                detail_dates_found += 1
                                detail_fetched += 1
                                continue  # ICS found, skip other methods
                    
                    # Priority 2: Try structured metadata on detail page
                    structured = extract_structured_events(html, event['link'])
                    if structured['count'] > 0:
                        structured_event = structured['events'][0]
                        if structured_event.get('date_iso'):
                            event['date_time'] = structured_event['date_iso']
                            detail_dates_found += 1
                            detail_fetched += 1
                            continue  # Structured metadata found
                    
                    # Priority 3: Use structured date extraction (CSS-based)
                    date_result = extract_date_from_detail_page(html, event['link'])
                    
                    if date_result.get('date_iso'):
                        event['date_time'] = date_result['date_iso']
                        detail_dates_found += 1
                        detail_fetched += 1
                        
                        if stop_after_first_valid and detail_dates_found >= 1:
                            # If we found at least one date, continue with others
                            pass
                    else:
                        detail_fetched += 1  # Count attempts even if no date found
            except Exception:
                # Fetch failed - continue
                pass
        
        # Add metrics to stats
        stats['detail_fetched'] = detail_fetched
        stats['detail_dates_found'] = detail_dates_found
        stats['detail_date_hit_rate'] = detail_dates_found / detail_fetched if detail_fetched > 0 else 0.0
    
    return events, stats


def extract_title_from_element(item, title_elem, link_elem, source_config):
    """Extract title from element with configurable strategy."""
    title_extraction = ensure_dict(source_config.get('title_extraction'))
    
    # Strategy 1: Use title_selector result directly
    if title_elem:
        # Check if title_extraction specifies attribute
        title_attr = title_extraction.get('title_attr')
        if title_attr:
            title = title_elem.get(title_attr)
            if title:
                return normalize_string(title)
        
        # Default: use text content
        title = title_elem.get_text()
        if title:
            return normalize_string(title)
    
    # Strategy 2: Use link text
    if link_elem:
        link_text = link_elem.get_text()
        if link_text:
            return normalize_string(link_text)
    
    # Strategy 3: Find first heading in item
    for heading in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        heading_elem = item.find(heading)
        if heading_elem:
            title = heading_elem.get_text()
            if title:
                return normalize_string(title)
    
    return None


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


def fetch_detail_description(url, description_selector=".description, .event-description, .summary, .content, article p", timeout=10):
    """
    Fetch a detail page and extract the description.
    Used for sources where the listing page doesn't have full descriptions.
    
    Args:
        url: Event detail page URL
        description_selector: CSS selector for description element
        timeout: Request timeout
    
    Returns:
        str: Description text (normalized) or None
    """
    try:
        response = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try provided selector (can match multiple elements)
        desc_elems = soup.select(description_selector)
        if desc_elems:
            # Combine text from all matching elements
            description_parts = []
            for elem in desc_elems:
                text = elem.get_text(strip=True)
                if text and len(text) > 20:  # Filter out very short snippets
                    description_parts.append(text)
            
            if description_parts:
                # Join and normalize
                full_description = ' '.join(description_parts)
                # Limit length (first 500 chars typically sufficient)
                if len(full_description) > 500:
                    full_description = full_description[:500] + '...'
                return normalize_string(full_description)
        
        # Fallback: look for <meta name="description"> tag
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc_text = meta_desc.get('content')
            if len(desc_text) > 20:
                return normalize_string(desc_text)
        
        # Fallback: look for first <p> in <article> or <main>
        article = soup.find('article') or soup.find('main')
        if article:
            first_p = article.find('p')
            if first_p:
                text = first_p.get_text(strip=True)
                if text and len(text) > 20:
                    if len(text) > 500:
                        text = text[:500] + '...'
                    return normalize_string(text)
        
        return None
    except Exception:
        return None


def fetch_detail_location(url, location_selectors=None, timeout=10):
    """
    Fetch a detail page and extract the location.
    Used for sources where the listing page doesn't show location.
    
    Args:
        url: Event detail page URL
        location_selectors: List of CSS selectors to try (default: common patterns)
        timeout: Request timeout
    
    Returns:
        str: Location text (normalized) or None
    """
    if location_selectors is None:
        location_selectors = [
            '.location', '.event-location', '.venue', '.event-venue',
            '[itemprop="location"]', '[itemprop="address"]'
        ]
    
    try:
        response = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for selector in location_selectors:
            location_elem = soup.select_one(selector)
            if location_elem:
                location_text = location_elem.get_text(strip=True)
                if location_text and len(location_text) > 3:
                    return normalize_string(location_text)
        
        return None
    except Exception:
        return None
