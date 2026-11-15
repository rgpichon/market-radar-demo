"""
Third-party calendar adapter for bank event extraction.

This adapter extracts events from third-party calendars (earnings calendars,
exchange calendars, finance aggregators) and normalizes them to EventRaw format.
"""
import sys
import re
import json
import hashlib
import requests
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.dates import parse_date
from utils.json_utils import ensure_list
from utils.events_only import should_reject_as_article


# Bank ticker mapping
BANK_TICKERS = {
    'Goldman Sachs': 'GS',
    'JPMorgan': 'JPM',
    'Morgan Stanley': 'MS',
    'Citigroup': 'C',
    'Bank of America': 'BAC',
    'Barclays': 'BCS',
    'Deutsche Bank': 'DB',
    'UBS': 'UBS',
    'BNP Paribas': 'BNPQY',  # ADR ticker
    'Société Générale': 'SCGLY'  # ADR ticker
}

# Cache directory
CACHE_DIR = backend_dir / "_cache"
EVIDENCE_DIR = backend_dir / "_evidence"
CACHE_TTL_HOURS = 6


def ensure_directories():
    """Ensure cache and evidence directories exist."""
    CACHE_DIR.mkdir(exist_ok=True)
    EVIDENCE_DIR.mkdir(exist_ok=True)
    # Add .gitignore to evidence dir
    gitignore = EVIDENCE_DIR / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n!.gitignore\n")


def get_cache_key(url: str) -> str:
    """Generate cache key from URL."""
    return hashlib.md5(url.encode()).hexdigest()


def get_cached_response(url: str) -> Optional[Tuple[str, Dict]]:
    """Get cached response if valid."""
    ensure_directories()
    cache_key = get_cache_key(url)
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        
        # Check TTL
        cached_at = datetime.fromisoformat(cache_data['cached_at'])
        if datetime.now(timezone.utc) - cached_at > timedelta(hours=CACHE_TTL_HOURS):
            return None
        
        return cache_data['content'], cache_data['headers']
    except:
        return None


def cache_response(url: str, content: str, headers: Dict):
    """Cache response."""
    ensure_directories()
    cache_key = get_cache_key(url)
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    cache_data = {
        'cached_at': datetime.now(timezone.utc).isoformat(),
        'url': url,
        'content': content,
        'headers': dict(headers)
    }
    
    with open(cache_file, 'w') as f:
        json.dump(cache_data, f)


def fetch_with_retry(url: str, max_retries: int = 3, backoff: float = 1.0) -> Tuple[Optional[requests.Response], Dict]:
    """
    Fetch URL with retry and backoff.
    
    Returns:
        (response, diagnostics) where diagnostics includes status_code, content_type, error
    """
    diagnostics = {
        'fetched_url': url,
        'status_code': None,
        'content_type': None,
        'error': None
    }
    
    # Check cache first
    cached = get_cached_response(url)
    if cached:
        # Return a mock response object
        class CachedResponse:
            def __init__(self, content, headers):
                self.text = content
                self.status_code = 200
                self.headers = headers
                self.url = url
        diagnostics['cached'] = True
        return CachedResponse(cached[0], cached[1]), diagnostics
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=15, headers=headers, allow_redirects=True)
            diagnostics['status_code'] = response.status_code
            diagnostics['content_type'] = response.headers.get('Content-Type', '')
            diagnostics['fetched_url'] = response.url
            
            # Cache successful responses
            if response.status_code == 200:
                cache_response(url, response.text, response.headers)
            
            # Handle rate limiting
            if response.status_code == 429:
                wait_time = backoff * (2 ** attempt)
                time.sleep(wait_time)
                continue
            
            # Handle blocking
            if response.status_code in [403, 401]:
                diagnostics['error'] = f'Blocked: HTTP {response.status_code}'
                return None, diagnostics
            
            response.raise_for_status()
            return response, diagnostics
            
        except requests.RequestException as e:
            diagnostics['error'] = str(e)
            if attempt < max_retries - 1:
                wait_time = backoff * (2 ** attempt)
                time.sleep(wait_time)
            else:
                return None, diagnostics
    
    return None, diagnostics


def save_evidence(ticker: str, provider: str, response_text: str, parsed_events: List[Dict], diagnostics: Dict):
    """Save evidence files for debugging."""
    ensure_directories()
    
    # Save response head
    evidence_file = EVIDENCE_DIR / f"{ticker}_{provider}_response_head.txt"
    with open(evidence_file, 'w') as f:
        f.write(f"URL: {diagnostics.get('fetched_url', 'N/A')}\n")
        f.write(f"Status: {diagnostics.get('status_code', 'N/A')}\n")
        f.write(f"Content-Type: {diagnostics.get('content_type', 'N/A')}\n")
        f.write(f"Cached: {diagnostics.get('cached', False)}\n")
        f.write(f"Error: {diagnostics.get('error', 'None')}\n")
        f.write("\n" + "="*60 + "\n")
        f.write("Response Head (first 500 chars):\n")
        f.write("="*60 + "\n")
        f.write(response_text[:500])
    
    # Save parsed events
    parsed_file = EVIDENCE_DIR / f"{ticker}_{provider}_parsed.json"
    with open(parsed_file, 'w') as f:
        json.dump({
            'ticker': ticker,
            'provider': provider,
            'events_count': len(parsed_events),
            'events': parsed_events,
            'diagnostics': diagnostics
        }, f, indent=2, default=str)


def infer_event_type(label: str) -> str:
    """Infer event type from calendar label."""
    label_lower = label.lower()
    
    if any(pattern in label_lower for pattern in ['earnings', 'q1', 'q2', 'q3', 'q4', 'quarterly', 'annual earnings']):
        return 'earnings_call'
    if any(pattern in label_lower for pattern in ['investor day', 'capital markets day', 'strategy day', 'analyst day']):
        return 'investor_day'
    if any(pattern in label_lower for pattern in ['conference', 'presentation', 'speaking', 'forum']):
        return 'conference'
    if any(pattern in label_lower for pattern in ['outlook', 'forecast', 'economic outlook']):
        return 'outlook'
    
    return 'earnings_call'  # Default to earnings_call for earnings calendars


def parse_nasdaq_earnings_api(ticker: str) -> Tuple[List[Dict], Dict]:
    """
    Parse NASDAQ earnings calendar using their public API.
    
    NASDAQ provides a public earnings calendar API endpoint.
    
    Args:
        ticker: Stock ticker symbol
    
    Returns:
        (events, diagnostics) where events is list of EventRaw dicts
    """
    events = []
    diagnostics = {
        'provider': 'nasdaq_earnings_api',
        'ticker': ticker,
        'fetched_url': None,
        'status_code': None,
        'content_type': None,
        'items_found': 0,
        'parse_errors': []
    }
    
    # NASDAQ earnings calendar API
    # Query multiple dates (today + next 7 days) to find future earnings
    now = datetime.now(timezone.utc)
    found_ticker = False
    
    # Query today and next 7 days (to avoid too many requests)
    for days_ahead in range(8):
        query_date = (now + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        url = f"https://api.nasdaq.com/api/calendar/earnings?date={query_date}"
        
        response, fetch_diagnostics = fetch_with_retry(url)
        if not response or response.status_code != 200:
            continue
        
        diagnostics['fetched_url'] = url  # Store last successful URL
        diagnostics.update({k: v for k, v in fetch_diagnostics.items() if k != 'fetched_url'})
        
        # Parse JSON response
        try:
            data = json.loads(response.text)
            
            # NASDAQ API structure: data.data.rows contains earnings data
            rows = data.get('data', {}).get('rows', [])
            
            # Find earnings for this ticker
            for row in rows:
                symbol = row.get('symbol', '').upper()
                if symbol == ticker.upper():
                    found_ticker = True
                    
                    # The API returns earnings for the query date
                    # Use query_date as the earnings date
                    date_time = parse_date(query_date)
                    if not date_time:
                        date_time = datetime.strptime(query_date, '%Y-%m-%d')
                    
                    if date_time.tzinfo is None:
                        date_time = date_time.replace(tzinfo=timezone.utc)
                    
                    # Only future events
                    if date_time >= now:
                        # Extract quarter info from fiscalQuarterEnding if available
                        fiscal_quarter = row.get('fiscalQuarterEnding', '')
                        if fiscal_quarter:
                            label = f"{fiscal_quarter} Earnings"
                        else:
                            quarter = ((date_time.month - 1) // 3) + 1
                            label = f"Q{quarter} {date_time.year} Earnings"
                        
                        event = {
                            'source_id': f'nasdaq_earnings_{ticker}',
                            'event_name': label,
                            'link': f"https://www.nasdaq.com/market-activity/stocks/{ticker}/earnings",
                            'date_time': date_time.isoformat(),
                            'date_text': query_date,
                            'ticker': ticker,
                            'event_type': 'earnings_call',
                            'calendar_source': 'nasdaq_earnings_api',
                            'evidence': f"NASDAQ API: {label} on {query_date}"
                        }
                        
                        events.append(event)
                        diagnostics['items_found'] += 1
                        break  # Found earnings for this ticker
            
            if found_ticker:
                break  # Stop searching once we found the ticker
                
        except json.JSONDecodeError as e:
            diagnostics['parse_errors'].append(f"JSON decode error for {query_date}: {str(e)}")
        except Exception as e:
            diagnostics['parse_errors'].append(f"Parse error for {query_date}: {str(e)}")
        
        # Small delay to avoid rate limiting
        if days_ahead < 7:
            time.sleep(0.5)
    
    # Save evidence (use last response if available)
    if 'fetched_url' in diagnostics:
        # Find the last response from the loop
        response_text = ''
        if 'response' in locals() and response:
            response_text = response.text[:1000]
        save_evidence(ticker, 'nasdaq_earnings_api', response_text, events, diagnostics)
    
    return events, diagnostics


def parse_marketwatch_earnings(ticker: str) -> Tuple[List[Dict], Dict]:
    """
    Parse MarketWatch earnings calendar for a ticker.
    
    MarketWatch has a more accessible earnings calendar page.
    
    Args:
        ticker: Stock ticker symbol
    
    Returns:
        (events, diagnostics) where events is list of EventRaw dicts
    """
    events = []
    diagnostics = {
        'provider': 'marketwatch',
        'ticker': ticker,
        'fetched_url': None,
        'status_code': None,
        'content_type': None,
        'items_found': 0,
        'parse_errors': []
    }
    
    # MarketWatch earnings URL - use quote page which has earnings info
    url = f"https://www.marketwatch.com/investing/stock/{ticker}"
    
    response, fetch_diagnostics = fetch_with_retry(url)
    diagnostics.update(fetch_diagnostics)
    
    if not response:
        diagnostics['parse_errors'].append(f"Failed to fetch: {diagnostics.get('error', 'Unknown error')}")
        return events, diagnostics
    
    if response.status_code != 200:
        diagnostics['parse_errors'].append(f"HTTP {response.status_code}")
        return events, diagnostics
    
    # Check for blocking/consent redirects
    if 'consent' in response.url.lower() or 'privacy' in response.url.lower():
        diagnostics['parse_errors'].append(f"Redirected to consent page: {response.url}")
        diagnostics['status_code'] = 403  # Treat as blocked
        return events, diagnostics
    
    # Parse HTML - use comprehensive text search
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text()
        
        # Comprehensive search for earnings dates in page text
        # Look for patterns like "Earnings Date: Jan 15, 2024" or "Next Earnings: 2024-01-15"
        earnings_date = None
        
        # Pattern 1: "Earnings" followed by date patterns
        earnings_patterns = [
            r'earnings\s+(?:date|call|announcement)[:\s]+([A-Z][a-z]{2,3}\s+\d{1,2},?\s+\d{4})',
            r'earnings\s+(?:date|call|announcement)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'earnings\s+(?:date|call|announcement)[:\s]+(\d{4}-\d{2}-\d{2})',
            r'next\s+earnings[:\s]+([A-Z][a-z]{2,3}\s+\d{1,2},?\s+\d{4})',
            r'next\s+earnings[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'next\s+earnings[:\s]+(\d{4}-\d{2}-\d{2})',
            r'q[1-4]\s+\d{4}\s+earnings[:\s]+([A-Z][a-z]{2,3}\s+\d{1,2},?\s+\d{4})',
            r'q[1-4]\s+\d{4}\s+earnings[:\s]+(\d{4}-\d{2}-\d{2})',
        ]
        
        for pattern in earnings_patterns:
            matches = re.finditer(pattern, page_text, re.IGNORECASE)
            for match in matches:
                date_str = match.group(1)
                parsed_date = parse_date(date_str)
                if parsed_date and isinstance(parsed_date, datetime):
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                    if parsed_date >= datetime.now(timezone.utc):
                        earnings_date = parsed_date.strftime('%Y-%m-%d')
                        break
            if earnings_date:
                break
        
        # Pattern 2: Look in structured data (JSON-LD, microdata)
        if not earnings_date:
            # Check JSON-LD
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    def search_json(obj):
                        if isinstance(obj, dict):
                            for key, value in obj.items():
                                if 'earnings' in str(key).lower() and 'date' in str(key).lower():
                                    if isinstance(value, str):
                                        date_match = re.search(r'\d{4}-\d{2}-\d{2}', value)
                                        if date_match:
                                            return date_match.group()
                                result = search_json(value)
                                if result:
                                    return result
                        elif isinstance(obj, list):
                            for item in obj:
                                result = search_json(item)
                                if result:
                                    return result
                        return None
                    found = search_json(data)
                    if found:
                        parsed = parse_date(found)
                        if parsed and isinstance(parsed, datetime):
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            if parsed >= datetime.now(timezone.utc):
                                earnings_date = parsed.strftime('%Y-%m-%d')
                                break
                except:
                    pass
        
        # Pattern 3: Look for date patterns near "earnings" keyword in HTML attributes
        if not earnings_date:
            earnings_elements = soup.find_all(string=re.compile(r'earnings', re.I))
            for elem in earnings_elements[:10]:  # Limit search
                parent = elem.parent
                if parent:
                    parent_text = parent.get_text()
                    # Look for dates near earnings text
                    date_matches = re.findall(r'\d{4}-\d{2}-\d{2}', parent_text)
                    date_matches.extend(re.findall(r'[A-Z][a-z]{2,3}\s+\d{1,2},?\s+\d{4}', parent_text))
                    for date_match in date_matches:
                        parsed = parse_date(date_match)
                        if parsed and isinstance(parsed, datetime):
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            if parsed >= datetime.now(timezone.utc):
                                earnings_date = parsed.strftime('%Y-%m-%d')
                                break
                if earnings_date:
                    break
        
        # If we found an earnings date, create event
        if earnings_date:
            date_time = parse_date(earnings_date)
            if date_time and isinstance(date_time, datetime):
                if date_time.tzinfo is None:
                    date_time = date_time.replace(tzinfo=timezone.utc)
                
                # Only future events
                if date_time >= datetime.now(timezone.utc):
                    # Determine quarter
                    quarter = ((date_time.month - 1) // 3) + 1
                    label = f"Q{quarter} {date_time.year} Earnings"
                    
                    event = {
                        'source_id': f'marketwatch_{ticker}',
                        'event_name': label,
                        'link': url,
                        'date_time': date_time.isoformat(),
                        'date_text': earnings_date,
                        'ticker': ticker,
                        'event_type': 'earnings_call',
                        'calendar_source': 'marketwatch',
                        'evidence': f"MarketWatch: {label} on {earnings_date}"
                    }
                    
                    events.append(event)
                    diagnostics['items_found'] = 1
        
    except Exception as e:
        diagnostics['parse_errors'].append(f"Parse error: {str(e)}")
    
    # Save evidence
    save_evidence(ticker, 'marketwatch', response.text, events, diagnostics)
    
    return events, diagnostics


def extract_events(calendar_config: Dict, source_config: Dict, return_stats=False) -> Tuple[List[Dict], Optional[Dict]]:
    """
    Extract events from third-party calendar.
    
    Args:
        calendar_config: Calendar configuration with:
            - calendar_type: "yahoo_finance", etc.
            - ticker: Stock ticker symbol (optional, will lookup if not provided)
        source_config: Source configuration with:
            - firm_name: Bank name
            - default_tags_json: Default tags
            - enforce_events_only: bool
        return_stats: If True, return extraction stats
    
    Returns:
        (events, stats) where events is list of EventRaw dicts
    """
    firm_name = source_config.get('firm_name', '')
    default_tags = ensure_list(source_config.get('default_tags_json', []))
    enforce_events_only = source_config.get('enforce_events_only', True)
    
    # Get ticker
    ticker = calendar_config.get('ticker')
    if not ticker:
        ticker = BANK_TICKERS.get(firm_name)
        if not ticker:
            if return_stats:
                return [], {'raw': 0, 'kept': 0, 'rejected': {'ticker_not_found': 1}, 'diagnostics': {}}
            return []
    
    # Get calendar type
    calendar_type = calendar_config.get('calendar_type', 'yahoo_finance')
    
    # Parse calendar based on type
    raw_events = []
    diagnostics = {}
    
    if calendar_type == 'yahoo_finance':
        # Yahoo Finance redirects to consent page - use nasdaq instead
        calendar_type = 'nasdaq_earnings_api'
    
    if calendar_type == 'marketwatch':
        raw_events, diagnostics = parse_marketwatch_earnings(ticker)
    elif calendar_type == 'nasdaq_earnings_api':
        raw_events, diagnostics = parse_nasdaq_earnings_api(ticker)
    else:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'unknown_calendar_type': 1}, 'diagnostics': {}}
        return []
    
    # Check for blocking
    if diagnostics.get('status_code') in [403, 401]:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'licensing_blocked': 1}, 'diagnostics': diagnostics}
        return []
    
    if not raw_events:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'no_events_found': 1}, 'diagnostics': diagnostics}
        return []
    
    # Normalize and filter events
    events = []
    rejected = {}
    raw_count = len(raw_events)
    
    for raw_event in raw_events:
        # Add firm_name if not present
        if 'firm_name' not in raw_event:
            raw_event['firm_name'] = firm_name
        
        # Add source_id if not present
        if 'source_id' not in raw_event:
            raw_event['source_id'] = source_config.get('id', '')
        
        # Check events-only policy
        title = raw_event.get('event_name', '')
        link = raw_event.get('link', '')
        
        if should_reject_as_article(title, link, enforce_events_only):
            rejected['article_like'] = rejected.get('article_like', 0) + 1
            continue
        
        # Ensure required fields
        if not title or not link:
            rejected['no_title_or_link'] = rejected.get('no_title_or_link', 0) + 1
            continue
        
        # Add default tags
        if default_tags:
            raw_event['tags'] = default_tags
        
        events.append(raw_event)
    
    stats = {
        'raw': raw_count,
        'kept': len(events),
        'rejected': rejected,
        'diagnostics': diagnostics
    }
    
    if return_stats:
        return events, stats
    
    return events
