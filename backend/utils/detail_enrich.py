"""
Detail Enrichment Validator

Enriches event sources by fetching detail pages and extracting dates using:
1. ICS harvesting (highest priority)
2. JSON-LD / microdata Event schema extraction
3. Robust HTML date/time parsing fallback

This turns "partial_needs_detail" sources into "working" sources.
"""
import json
import hashlib
import time
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:
    from requests.packages.urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import re

# Host budget integration (optional)
try:
    from utils.host_budget import get_budget, HostBudgetExceeded
    HOST_BUDGET_AVAILABLE = True
except ImportError:
    HOST_BUDGET_AVAILABLE = False
    HostBudgetExceeded = Exception

from .structured_metadata_extractor import extract_structured_events, is_future_event, _parse_iso_date
from .ics_harvester import find_ics_links, harvest_ics_from_detail_page, parse_ics_file
from .structured_date_extraction import extract_date_from_detail_page
from .host_throttle import get_throttle
from dateutil import parser as date_parser


# Cache configuration
CACHE_DIR = Path(__file__).parent.parent / "_cache" / "detail"
CACHE_TTL = 12 * 3600  # 12 hours in seconds

# HTTP configuration
DEFAULT_TIMEOUT = (10, 20)  # (connect, read) in seconds
DEFAULT_RETRIES = 3
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}


def get_cache_path(url: str, parser_mode: str = "default") -> Path:
    """Get cache file path for a URL and parser mode."""
    cache_key = hashlib.sha256(f"{url}:{parser_mode}".encode()).hexdigest()
    return CACHE_DIR / f"{cache_key}.json"


def classify_accessibility_error(response: Optional[requests.Response], exception: Optional[Exception]) -> str:
    """
    Classify HTTP fetch error into structured outcomes.
    
    Returns:
        'ok': Success
        'deferred_transient_network': Timeouts, DNS, connection reset, 429, 503
        'blocked_hard': 403 repeatedly, bot wall
        'dead_link': 404 consistently
        'gated_login': Login required
    """
    if response is None:
        if exception is None:
            return 'ok'
        
        # Check exception type
        exc_str = str(exception).lower()
        if any(x in exc_str for x in ['timeout', 'timed out', 'connection timeout']):
            return 'deferred_transient_network'
        if any(x in exc_str for x in ['dns', 'name resolution', 'nodename']):
            return 'deferred_transient_network'
        if any(x in exc_str for x in ['connection reset', 'connection refused', 'connection aborted']):
            return 'deferred_transient_network'
        if 'ssl' in exc_str or 'certificate' in exc_str:
            return 'deferred_transient_network'
        
        return 'deferred_transient_network'  # Default for unknown exceptions
    
    status = response.status_code
    
    if status == 200:
        return 'ok'
    elif status == 404:
        return 'dead_link'
    elif status == 403:
        # Check if it's a bot wall (common patterns)
        content = response.text.lower()
        if any(x in content for x in ['bot', 'captcha', 'cloudflare', 'access denied', 'forbidden']):
            return 'blocked_hard'
        return 'blocked_hard'
    elif status == 401:
        return 'gated_login'
    elif status in [429, 503, 502, 504]:
        return 'deferred_transient_network'
    elif status >= 500:
        return 'deferred_transient_network'
    elif status >= 400:
        return 'dead_link'
    
    return 'ok'


def fetch_with_retries(
    url: str,
    timeout: Tuple[int, int] = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_RETRIES,
    headers: Optional[Dict] = None,
    use_cache_only: bool = False,
    host_budget=None
) -> Tuple[Optional[Dict], str]:
    """
    Fetch URL with retries, exponential backoff, and proper error classification.
    
    Returns:
        (result_dict, accessibility_status)
        result_dict: {'html': str, 'headers': dict, 'final_url': str, 'fetched_at': str} or None
        accessibility_status: 'ok' | 'deferred_transient_network' | 'blocked_hard' | 'dead_link' | 'gated_login'
    """
    # Check cache first
    cache_path = get_cache_path(url)
    if cache_path.exists():
        try:
            with open(cache_path, 'r') as f:
                cached = json.load(f)
            
            # Check TTL
            fetched_at = datetime.fromisoformat(cached['fetched_at'])
            age = (datetime.now(timezone.utc) - fetched_at.replace(tzinfo=timezone.utc)).total_seconds()
            
            if age < CACHE_TTL:
                cached['from_cache'] = True
                return cached, 'ok'
        except Exception:
            pass  # Cache invalid, fetch fresh
    
    if use_cache_only:
        return None, 'deferred_transient_network'  # No cache hit, but cache-only mode
    
    # Check host budget (if provided)
    if host_budget and HOST_BUDGET_AVAILABLE:
        try:
            sleep_seconds = host_budget.acquire(url)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        except HostBudgetExceeded as e:
            return None, 'deferred_transient_network'  # Budget exceeded
    
    # Check throttle
    throttle = get_throttle()
    if throttle.is_throttled(url):
        wait_time = throttle.get_wait_time(url)
        if wait_time > 0:
            time.sleep(min(wait_time, 60))  # Max 60s wait
    
    # Setup session with retries
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        respect_retry_after_header=True
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    request_headers = DEFAULT_HEADERS.copy()
    if headers:
        request_headers.update(headers)
    
    last_exception = None
    last_response = None
    
    for attempt in range(max_retries + 1):
        try:
            # Check throttle before each attempt
            if throttle.is_throttled(url):
                wait_time = throttle.get_wait_time(url)
                if wait_time > 0:
                    time.sleep(min(wait_time, 60))
            
            # Exponential backoff with jitter
            if attempt > 0:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait_time)
            
            response = session.get(
                url,
                timeout=timeout,
                headers=request_headers,
                allow_redirects=True
            )
            
            last_response = response
            
            if response.status_code == 200:
                result = {
                    'html': response.text,
                    'headers': dict(response.headers),
                    'final_url': response.url,
                    'fetched_at': datetime.now(timezone.utc).isoformat(),
                    'from_cache': False
                }
                
                # Save to cache
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with open(cache_path, 'w') as f:
                    json.dump(result, f)
                
                # Record success in host budget
                if host_budget and HOST_BUDGET_AVAILABLE:
                    host_budget.record_result(url, status_code=200)
                
                return result, 'ok'
            
            # Handle retryable status codes
            if response.status_code in [429, 503]:
                # Record in host budget
                if host_budget and HOST_BUDGET_AVAILABLE:
                    host_budget.record_result(url, status_code=response.status_code)
                
                # Record rate limit
                retry_after = response.headers.get('Retry-After')
                retry_after_int = None
                if retry_after:
                    try:
                        retry_after_int = int(retry_after)
                    except ValueError:
                        pass
                throttle.record_rate_limit(url, response.status_code, retry_after_int)
                
                if retry_after_int and attempt < max_retries:
                    time.sleep(min(retry_after_int, 60))
                    continue
                
                if attempt < max_retries:
                    continue
            elif response.status_code == 200:
                # Record success (restores concurrency gradually)
                throttle.record_success(url)
            
        except requests.exceptions.Timeout as e:
            last_exception = e
            if attempt < max_retries:
                continue
        except requests.exceptions.ConnectionError as e:
            last_exception = e
            if attempt < max_retries:
                continue
        except requests.exceptions.RequestException as e:
            last_exception = e
            if attempt < max_retries:
                continue
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                continue
    
    # All retries exhausted
    accessibility = classify_accessibility_error(last_response, last_exception)
    
    # Record failure in host budget
    if host_budget and HOST_BUDGET_AVAILABLE:
        status_code = last_response.status_code if last_response else None
        host_budget.record_result(url, status_code=status_code, error_class=accessibility)
    
    return None, accessibility


def fetch_with_cache(
    url: str,
    dry_run: bool = False,
    ttl: int = CACHE_TTL,
    use_cache_only: bool = False,
    host_budget=None
) -> Tuple[Optional[Dict], str]:
    """
    Fetch URL with caching (wrapper around fetch_with_retries).
    
    Returns:
        (result_dict, accessibility_status)
    """
    if dry_run or use_cache_only:
        result, status = fetch_with_retries(url, use_cache_only=True, host_budget=host_budget)
        return result, status
    
    return fetch_with_retries(url, use_cache_only=False, host_budget=host_budget)


def find_ics_links_enhanced(html: str, base_url: str) -> List[str]:
    """
    Enhanced ICS link discovery.
    
    Looks for:
    - .ics file extensions
    - Calendar-related anchor/button text
    - Common query params and paths
    - Follows redirects
    """
    soup = BeautifulSoup(html, 'html.parser')
    ics_links = []
    seen = set()
    
    # Calendar-related keywords
    calendar_keywords = [
        'add to calendar', 'add to outlook', 'ical', 'ics', 'add to iphone',
        'google calendar', 'download calendar', 'calendar download', 'export calendar'
    ]
    
    # Find all links and buttons
    for elem in soup.find_all(['a', 'button'], href=True):
        href = elem.get('href', '')
        if not href:
            continue
        
        text = elem.get_text(strip=True).lower()
        href_lower = href.lower()
        
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
        
        # Check for common query params
        if any(param in href_lower for param in ['?ical=', '?download=ics', '?format=ics', '/ical/', '/ics/', '/calendar/', '/add-to-calendar/']):
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                ics_links.append(full_url)
    
    # Also check for webcal:// URLs
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if href.lower().startswith('webcal://'):
            https_url = href.replace('webcal://', 'https://')
            if https_url not in seen:
                seen.add(https_url)
                ics_links.append(https_url)
    
    return ics_links


def extract_date_from_html_robust(html: str, base_url: str) -> Optional[Dict]:
    """
    Robust HTML date/time parsing fallback with expanded heuristics.
    
    Looks for:
    - <time> tags with datetime
    - Label proximity ("Date/Time/When" near date text)
    - Header blocks with dates
    - Timezone indicators (GMT/UTC/BST/EST)
    - Month names
    - Range dates (e.g., "Jan 15-17, 2026")
    - Time-only cases (assumes today's date)
    - Multiple date format variants
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Priority 1: <time> tags
    time_elem = soup.find('time', datetime=True)
    if time_elem:
        dt_str = time_elem.get('datetime')
        if dt_str:
            from .structured_metadata_extractor import _parse_iso_date
            parsed = _parse_iso_date(dt_str)
            if parsed:
                return {
                    'date_iso': parsed,
                    'date_text': dt_str,
                    'method': 'html_time_tag'
                }
    
    # Priority 2: Look for date labels with expanded patterns
    date_labels = [
        'date', 'time', 'when', 'event date', 'start date', 'event time',
        'scheduled', 'occurs', 'takes place', 'happens on', 'on'
    ]
    
    for label in date_labels:
        # Find elements containing the label (more flexible matching)
        label_pattern = rf'\b{re.escape(label)}\s*[:=]?\s*'
        label_elem = soup.find(string=re.compile(label_pattern, re.IGNORECASE))
        if label_elem:
            parent = label_elem.parent
            if parent:
                # Look in parent and siblings
                text = parent.get_text()
                # Also check next sibling
                next_sibling = parent.find_next_sibling()
                if next_sibling:
                    text += " " + next_sibling.get_text()
                
                parsed = _parse_date_text_robust(text)
                if parsed:
                    return {
                        'date_iso': parsed,
                        'date_text': text[:200],
                        'method': 'html_label_proximity'
                    }
    
    # Priority 3: Look for date patterns with expanded variants
    date_patterns = [
        # Full month name variants
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
        # Abbreviated month
        r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}',
        # ISO format
        r'\b\d{4}-\d{2}-\d{2}',
        # US format (MM/DD/YYYY or MM-DD-YYYY)
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{4}',
        # European format (DD/MM/YYYY or DD-MM-YYYY)
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',
        # Range dates (e.g., "Jan 15-17, 2026")
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\s*[-–—]\s*\d{1,2},?\s+\d{4}',
        # Day month year (e.g., "15 January 2026")
        r'\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}',
    ]
    
    for pattern in date_patterns:
        matches = re.finditer(pattern, html, re.IGNORECASE)
        for match in matches:
            date_str = match.group(0)
            parsed = _parse_date_text_robust(date_str)
            if parsed:
                return {
                    'date_iso': parsed,
                    'date_text': date_str,
                    'method': 'html_pattern_match'
                }
    
    # Priority 4: Look for time-only patterns (assume today's date)
    time_patterns = [
        r'\b\d{1,2}:\d{2}\s*(AM|PM|am|pm)',
        r'\b\d{1,2}:\d{2}:\d{2}\s*(AM|PM|am|pm)?',
        r'\b\d{1,2}:\d{2}\s*(GMT|UTC|BST|EST|PST|CET)',
    ]
    
    for pattern in time_patterns:
        matches = re.finditer(pattern, html, re.IGNORECASE)
        for match in matches:
            time_str = match.group(0)
            # Try to parse as time and combine with today
            try:
                # Extract timezone if present
                tz_str = None
                if any(tz in time_str.upper() for tz in ['GMT', 'UTC', 'BST', 'EST', 'PST', 'CET']):
                    for tz in ['GMT', 'UTC', 'BST', 'EST', 'PST', 'CET']:
                        if tz in time_str.upper():
                            tz_str = tz
                            break
                
                # Parse time
                time_part = re.search(r'\d{1,2}:\d{2}', time_str)
                if time_part:
                    today = datetime.now(timezone.utc)
                    hour, minute = map(int, time_part.group(0).split(':'))
                    
                    # Handle AM/PM
                    if 'PM' in time_str.upper() and hour < 12:
                        hour += 12
                    elif 'AM' in time_str.upper() and hour == 12:
                        hour = 0
                    
                    # Default to Europe/London if no timezone specified
                    if not tz_str:
                        tz_str = 'Europe/London'
                    
                    # Create datetime (simplified - assumes today)
                    dt = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    
                    # Convert timezone if specified
                    if tz_str == 'BST':
                        # BST is UTC+1
                        dt = dt.replace(tzinfo=timezone.utc) - timedelta(hours=1)
                    elif tz_str == 'EST':
                        # EST is UTC-5
                        dt = dt.replace(tzinfo=timezone.utc) + timedelta(hours=5)
                    elif tz_str == 'PST':
                        # PST is UTC-8
                        dt = dt.replace(tzinfo=timezone.utc) + timedelta(hours=8)
                    elif tz_str == 'CET':
                        # CET is UTC+1
                        dt = dt.replace(tzinfo=timezone.utc) - timedelta(hours=1)
                    else:
                        dt = dt.replace(tzinfo=timezone.utc)
                    
                    return {
                        'date_iso': dt.isoformat(),
                        'date_text': time_str,
                        'method': 'html_time_only'
                    }
            except Exception:
                pass
    
    return None


def _parse_date_text_robust(text: str) -> Optional[str]:
    """
    Parse date text with robust handling of variants and timezones.
    
    Handles:
    - Range dates (takes start date)
    - Multiple format variants
    - Timezone normalization (defaults to Europe/London)
    """
    from datetime import timedelta
    
    # Clean text
    text = text.strip()
    
    # Handle range dates (e.g., "Jan 15-17, 2026" -> "Jan 15, 2026")
    range_match = re.search(r'(\w+)\s+(\d{1,2})\s*[-–—]\s*(\d{1,2}),?\s+(\d{4})', text, re.IGNORECASE)
    if range_match:
        month, start_day, end_day, year = range_match.groups()
        text = f"{month} {start_day}, {year}"
    
    try:
        # Try parsing with dateutil
        dt = date_parser.parse(text, fuzzy=True, default=datetime.now(timezone.utc))
        
        # Validate year
        if dt.year < 2000 or dt.year > 2100:
            return None
        
        # Normalize timezone
        if dt.tzinfo is None:
            # Default to Europe/London (UTC+0/+1 depending on DST)
            # For simplicity, use UTC
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        
        return dt.isoformat()
    except Exception:
        return None


def sample_detail_urls(
    events: List[Dict],
    max_detail: int,
    mode: str = 'stratified'
) -> List[Dict]:
    """
    Sample detail URLs with smart strategies.
    
    Deliverable D: Adaptive sampling - always includes first 3, middle 3, last 3,
    plus date-hint items.
    
    Modes:
    - 'top_n': First N events (existing behavior)
    - 'stratified': Evenly spaced across the list (default)
    - 'date_hint_priority': Boost URLs with date hints in title/snippet
    - 'adaptive': First 3, middle 3, last 3, plus date-hint items (Deliverable D)
    """
    if len(events) <= max_detail:
        return events
    
    if mode == 'top_n':
        return events[:max_detail]
    
    elif mode == 'stratified':
        # Evenly spaced sampling
        step = len(events) / max_detail
        indices = [int(i * step) for i in range(max_detail)]
        return [events[i] for i in indices]
    
    elif mode == 'date_hint_priority':
        # Score events by date hints
        date_hints = [
            'jan', 'feb', 'mar', 'apr', 'may', 'jun',
            'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
            '2024', '2025', '2026', '2027',
            'when', 'date', 'time', 'calendar', 'ical', 'ics',
            'add to calendar', 'add to outlook'
        ]
        
        scored_events = []
        for event in events:
            score = 0
            title = (event.get('title', '') or event.get('event_name', '') or '').lower()
            link = (event.get('link', '') or '').lower()
            text = f"{title} {link}"
            
            for hint in date_hints:
                if hint in text:
                    score += 1
            
            scored_events.append((score, event))
        
        # Sort by score (descending), take top N
        scored_events.sort(key=lambda x: -x[0])
        return [event for _, event in scored_events[:max_detail]]
    
    elif mode == 'adaptive':
        # Deliverable D: Adaptive sampling
        # Always include: first 3, middle 3, last 3
        selected = set()
        selected_indices = []
        
        # First 3
        for i in range(min(3, len(events))):
            selected.add(i)
            selected_indices.append(i)
        
        # Middle 3
        mid_start = len(events) // 2 - 1
        for i in range(mid_start, min(mid_start + 3, len(events))):
            if i not in selected:
                selected.add(i)
                selected_indices.append(i)
        
        # Last 3
        for i in range(max(0, len(events) - 3), len(events)):
            if i not in selected:
                selected.add(i)
                selected_indices.append(i)
        
        # Plus date-hint items
        date_hints = [
            'jan', 'feb', 'mar', 'apr', 'may', 'jun',
            'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
            '2024', '2025', '2026', '2027',
            'when', 'date', 'time', 'calendar', 'ical', 'ics',
            'add to calendar', 'add to outlook', 'am', 'pm', 'gmt'
        ]
        
        scored_events = []
        for i, event in enumerate(events):
            if i in selected:
                continue
            
            score = 0
            title = (event.get('title', '') or event.get('event_name', '') or '').lower()
            link = (event.get('link', '') or '').lower()
            text = f"{title} {link}"
            
            for hint in date_hints:
                if hint in text:
                    score += 1
            
            if score > 0:
                scored_events.append((score, i, event))
        
        # Sort by score, add top date-hint items until we reach max_detail
        scored_events.sort(key=lambda x: -x[0])
        for score, i, event in scored_events:
            if len(selected) >= max_detail:
                break
            if i not in selected:
                selected.add(i)
                selected_indices.append(i)
        
        # Fill remaining slots with stratified sampling if needed
        if len(selected) < max_detail:
            remaining = max_detail - len(selected)
            step = len(events) / (remaining + 1)
            for j in range(remaining):
                idx = int((j + 1) * step)
                if idx not in selected and idx < len(events):
                    selected.add(idx)
                    selected_indices.append(idx)
        
        # Return in order
        selected_indices.sort()
        return [events[i] for i in selected_indices]
    
    else:
        # Default to stratified
        return sample_detail_urls(events, max_detail, mode='stratified')


def enrich_event_detail(
    detail_url: str,
    base_url: str,
    dry_run: bool = False,
    use_cache_only: bool = False
) -> Dict:
    """
    Enrich a single event detail page.
    
    Returns:
        {
            'url': str,
            'has_date': bool,
            'start_dt': str or None,
            'end_dt': str or None,
            'extraction_method': 'ics'|'jsonld'|'html'|None,
            'evidence_paths': List[str]
        }
    """
    result = {
        'url': detail_url,
        'has_date': False,
        'start_dt': None,
        'end_dt': None,
        'extraction_method': None,
        'evidence_paths': []
    }
    
    # Fetch with cache (host_budget not needed for individual detail pages in this function)
    fetched, accessibility = fetch_with_cache(detail_url, dry_run=dry_run, use_cache_only=use_cache_only)
    if not fetched:
        result['accessibility'] = accessibility
        return result
    
    html = fetched['html']
    final_url = fetched['final_url']
    
    # Try ICS first (highest priority)
    ics_links = find_ics_links_enhanced(html, final_url)
    for ics_url in ics_links[:3]:  # Try first 3 ICS links
        ics_result = parse_ics_file(ics_url, timeout=10)
        if ics_result and ics_result['count'] > 0:
            event = ics_result['events'][0]
            if event.get('date_iso'):
                result['has_date'] = True
                result['start_dt'] = event['date_iso']
                result['end_dt'] = event.get('end_date_iso')
                result['extraction_method'] = 'ics'
                result['evidence_paths'].append(f'ics:{ics_url}')
                return result
    
    # Try structured metadata on detail page
    structured = extract_structured_events(html, final_url)
    if structured['count'] > 0:
        event = structured['events'][0]
        if event.get('date_iso'):
            result['has_date'] = True
            result['start_dt'] = event['date_iso']
            result['end_dt'] = event.get('end_date_iso')
            result['extraction_method'] = 'jsonld' if structured['source_type'] == 'jsonld' else 'microdata'
            result['evidence_paths'].append(f'{structured["source_type"]}:detail_page')
            return result
    
    # Try structured date extraction (CSS-based)
    date_result = extract_date_from_detail_page(html, final_url)
    if date_result.get('date_iso'):
        result['has_date'] = True
        result['start_dt'] = date_result['date_iso']
        result['extraction_method'] = date_result.get('source', 'html')
        result['evidence_paths'].append(f'structured_date:{date_result.get("source", "unknown")}')
        return result
    
    # Try robust HTML parsing
    html_date = extract_date_from_html_robust(html, final_url)
    if html_date:
        result['has_date'] = True
        result['start_dt'] = html_date['date_iso']
        result['extraction_method'] = html_date['method']
        result['evidence_paths'].append(f'html_robust:{html_date["method"]}')
        return result
    
    return result


def validate_detail_enrichment(
    list_url: str,
    selectors_json: Dict,
    firm_name: str = "Unknown",
    max_detail: int = 25,
    dry_run: bool = False,
    use_cache_only: bool = False,
    max_new_fetches: Optional[int] = None,
    sampling_mode: str = 'stratified',
    min_sample_ok: int = 8,
    host_budget=None
) -> Dict:
    """
    Validate source with detail enrichment.
    
    Args:
        list_url: URL of the list page
        selectors_json: CSS selectors for extracting event items
        firm_name: Firm name for logging
        max_detail: Maximum number of detail pages to fetch
        dry_run: If True, use cache only, don't fetch new pages
    
    Returns:
        {
            'classification': str,
            'metrics': Dict,
            'events': List[Dict],
            'failure_reasons': List[str],
            'recommended_action': str
        }
    """
    # Step 1: Extract event items from list page
    try:
        fetched, list_accessibility = fetch_with_cache(list_url, dry_run=dry_run, use_cache_only=use_cache_only, host_budget=host_budget)
        if not fetched:
            # Classify based on accessibility
            if list_accessibility == 'deferred_transient_network':
                classification = 'deferred_transient_network'
                action = 'retry_later_network_issue'
            elif list_accessibility in ['blocked_hard', 'dead_link', 'gated_login']:
                classification = 'failed'
                action = f'check_url_accessibility_{list_accessibility}'
            else:
                classification = 'failed'
                action = 'check_url_accessibility'
            
            return {
                'classification': classification,
                'metrics': {},
                'events': [],
                'failure_reasons': [f'list_page_fetch_{list_accessibility}'],
                'recommended_action': action,
                'accessibility': list_accessibility
            }
        
        html = fetched['html']
        base_url = fetched['final_url']
        
        # Extract events using selectors
        from adapters.html_list import extract_events
        source_config = {
            'id': 'enrichment_test',
            'firm_name': firm_name,
            'url': list_url,
            'adapter_type': 'html_list',
            'selectors_json': selectors_json,
            'default_tags_json': []
        }
        
        events, stats = extract_events(html, source_config, return_stats=True)
        
        if len(events) == 0:
            return {
                'classification': 'no_events',
                'metrics': {'kept_count': 0},
                'events': [],
                'failure_reasons': ['no_events_on_list_page'],
                'recommended_action': 'check_selectors_or_page_structure'
            }
        
        # Step 2: Sample detail URLs intelligently
        sampled_events = sample_detail_urls(events, max_detail, mode=sampling_mode)
        
        # Step 3: Enrich detail pages
        enriched_events = []
        detail_pages_attempted = 0
        detail_pages_succeeded = 0
        detail_successes = 0
        ics_successes = 0
        metadata_successes = 0
        failure_reasons = []
        accessibility_counts = {}
        new_fetch_count = 0
        
        for event in sampled_events:
            detail_url = event.get('link')
            if not detail_url:
                failure_reasons.append('no_detail_url')
                continue
            
            detail_pages_attempted += 1
            
            # Check if we should limit new fetches
            if max_new_fetches is not None and new_fetch_count >= max_new_fetches:
                # Use cache only for remaining
                current_use_cache_only = True
            else:
                current_use_cache_only = use_cache_only
            
            enrichment = enrich_event_detail(
                detail_url, base_url, dry_run=dry_run, use_cache_only=current_use_cache_only
            )
            
            # Track accessibility
            acc = enrichment.get('accessibility', 'ok')
            accessibility_counts[acc] = accessibility_counts.get(acc, 0) + 1
            
            if not enrichment.get('accessibility') or enrichment.get('accessibility') == 'ok':
                detail_pages_succeeded += 1
                if not enrichment.get('from_cache', False):
                    new_fetch_count += 1
            
            # Update event with enriched data
            enriched_event = event.copy()
            if enrichment.get('has_date'):
                enriched_event['date_time'] = enrichment['start_dt']
                detail_successes += 1
                
                if enrichment.get('extraction_method') == 'ics':
                    ics_successes += 1
                elif enrichment.get('extraction_method') in ['jsonld', 'microdata']:
                    metadata_successes += 1
            
            enriched_event['enrichment'] = enrichment
            enriched_events.append(enriched_event)
            
            # Deliverable D: Stop early if we've exceeded threshold after min_sample_ok
            if detail_pages_succeeded >= min_sample_ok:
                current_dated_count = sum(1 for e in enriched_events if e.get('date_time'))
                current_dated_ratio = current_dated_count / len(enriched_events) if enriched_events else 0.0
                target_ratio = 0.5  # Threshold from acceptance criteria
                
                if current_dated_ratio >= target_ratio:
                    # Early success - stop fetching more
                    break
        
        # Step 4: Compute metrics
        kept_count = len(enriched_events)
        dated_count = sum(1 for e in enriched_events if e.get('date_time'))
        undated_count = kept_count - dated_count
        dated_ratio = dated_count / kept_count if kept_count > 0 else 0.0
        
        # Count future events
        future_count = 0
        for event in enriched_events:
            if event.get('date_time'):
                try:
                    dt = datetime.fromisoformat(event['date_time'].replace('Z', '+00:00'))
                    if dt > datetime.now(timezone.utc):
                        future_count += 1
                except Exception:
                    pass
        
        detail_success_ratio = detail_successes / detail_pages_succeeded if detail_pages_succeeded > 0 else 0.0
        ics_found_ratio = ics_successes / detail_pages_succeeded if detail_pages_succeeded > 0 else 0.0
        metadata_found_ratio = metadata_successes / detail_pages_succeeded if detail_pages_succeeded > 0 else 0.0
        
        metrics = {
            'kept_count': kept_count,
            'dated_count': dated_count,
            'undated_count': undated_count,
            'dated_ratio': dated_ratio,
            'future_count': future_count,
            'detail_pages_attempted': detail_pages_attempted,
            'detail_pages_succeeded': detail_pages_succeeded,
            'detail_success_ratio': detail_success_ratio,
            'ics_found_ratio': ics_found_ratio,
            'metadata_found_on_detail_ratio': metadata_found_ratio,
            'accessibility_counts': accessibility_counts,
            'new_fetch_count': new_fetch_count
        }
        
        # Step 5: Classify with minimum sample requirement
        min_events = 5
        min_dated_ratio = 0.60
        min_future_events = 1
        
        # Check if we have enough successful samples
        if detail_pages_succeeded < min_sample_ok:
            # Not enough data - check if it's due to transient network issues
            transient_count = accessibility_counts.get('deferred_transient_network', 0)
            if transient_count > 0:
                classification = 'deferred_transient_network'
                recommended_action = f'retry_later_insufficient_samples (succeeded: {detail_pages_succeeded}/{min_sample_ok}, transient: {transient_count})'
            else:
                classification = 'partial_needs_detail'
                recommended_action = f'insufficient_samples (succeeded: {detail_pages_succeeded}/{min_sample_ok})'
        elif kept_count >= min_events and dated_ratio >= min_dated_ratio and future_count >= min_future_events:
            classification = 'ready_to_onboard'
            recommended_action = 'enable_detail_fetch_and_activate'
        elif kept_count >= min_events and dated_ratio >= 0.40:
            classification = 'partial_needs_detail'
            recommended_action = f'improve_date_extraction (current: {dated_ratio:.1%}, target: 60%)'
        elif kept_count >= min_events and dated_ratio > 0:
            classification = 'partial_needs_detail'
            recommended_action = f'low_dated_ratio (current: {dated_ratio:.1%})'
        elif kept_count < min_events:
            classification = 'no_events'
            recommended_action = 'check_selectors_or_page_structure'
        else:
            classification = 'partial_needs_detail'
            recommended_action = 'manual_review_required'
        
        # Generate recommended detail_fetch config for partial sources
        recommended_detail_fetch = None
        if classification == 'partial_needs_detail' and dated_ratio > 0:
            # Generate actionable config even if imperfect
            recommended_detail_fetch = {
                'enabled': True,
                'max': max_detail,
                'stop_after_first_valid': True,
                'harvest_ics': True,
                'date_selector': 'script[type="application/ld+json"], time[datetime], meta[itemprop="startDate"], meta[property*="date"], .date, .event-date, [class*="date"]',
                'date_attr': 'datetime',
                'priority_order': ['ics', 'jsonld', 'time_datetime', 'meta_itemprop', 'meta_property', 'class_date']
            }
        
        result = {
            'classification': classification,
            'metrics': metrics,
            'events': enriched_events[:10],  # Sample for evidence
            'failure_reasons': list(set(failure_reasons)),
            'recommended_action': recommended_action
        }
        
        if recommended_detail_fetch:
            result['recommended_detail_fetch'] = recommended_detail_fetch
        
        return result
        
    except Exception as e:
        return {
            'classification': 'failed',
            'metrics': {},
            'events': [],
            'failure_reasons': [f'enrichment_error: {str(e)}'],
            'recommended_action': 'check_error_logs'
        }
