"""
Fallback extraction logic for JS-rendered pages.

Implements fallback chain: JSON-LD → Static HTML → Playwright
Only uses Playwright when simpler methods fail.
"""
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import requests
from bs4 import BeautifulSoup

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from adapters.playwright_adapter import PLAYWRIGHT_AVAILABLE, extract_events_playwright
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    extract_events_playwright = None


def extract_with_fallback(source_config: Dict, return_stats: bool = False) -> Tuple[List[Dict], Dict]:
    """
    Extract events using fallback chain:
    1. Try JSON-LD (embedded in HTML, no JS needed)
    2. Try static HTML extraction (html_list adapter)
    3. If 0 events + JS detected → try Playwright
    
    Args:
        source_config: Source configuration
        return_stats: If True, return stats dict
        
    Returns:
        (events_list, stats_dict) or (events_list, None)
    """
    source_url = source_config.get('url', '')
    stats = {
        'raw': 0,
        'kept': 0,
        'rejected': {},
        'method_used': None
    }
    
    events = []
    html = None
    
    # Step 1: Try JSON-LD first (fastest, no JS needed)
    try:
        response = requests.get(source_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        response.raise_for_status()
        html = response.text
        
        # Check for JSON-LD
        from adapters.json_ld import extract_events as extract_json_ld
        json_ld_events = extract_json_ld(html, source_config)
        
        if json_ld_events:
            from utils.pipeline import _convert_to_event_raw
            events = _convert_to_event_raw(json_ld_events, source_config.get('id', ''))
            stats['method_used'] = 'json_ld'
            stats['raw'] = len(events)
            stats['kept'] = len(events)
            
            if return_stats:
                return events, stats
            return events
            
    except Exception:
        pass  # Continue to next method
    
    # Step 2: Try static HTML extraction
    try:
        # If we don't have HTML yet, fetch it
        if html is None:
            response = requests.get(source_url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }, allow_redirects=True)
            response.raise_for_status()
            html = response.text
        
        from adapters.html_list import extract_events
        html_events, html_stats = extract_events(html, source_config, return_stats=True)
        
        if html_events:
            from utils.pipeline import _convert_to_event_raw
            events = _convert_to_event_raw(html_events, source_config.get('id', ''))
            stats['method_used'] = 'html_list'
            stats.update(html_stats)
            
            if return_stats:
                return events, stats
            return events
            
        # Step 3: If 0 events + JS detected → try Playwright
        if len(html_events) == 0 and len(html) > 10000:
            # Check for JS indicators
            html_lower = html.lower()
            js_indicators = [
                'enable javascript', 'javascript required', 'please enable javascript',
                'noscript', 'react-root', 'ng-app', 'data-reactroot'
            ]
            
            if any(indicator in html_lower for indicator in js_indicators):
                # JS detected, try Playwright
                if PLAYWRIGHT_AVAILABLE:
                    try:
                        playwright_events, playwright_stats = extract_events_playwright(
                            source_config, return_stats=True
                        )
                        if playwright_events:
                            from utils.pipeline import _convert_to_event_raw
                            events = _convert_to_event_raw(playwright_events, source_config.get('id', ''))
                            stats['method_used'] = 'playwright_fallback'
                            stats.update(playwright_stats)
                            
                            if return_stats:
                                return events, stats
                            return events
                    except Exception as e:
                        stats['rejected']['playwright_error'] = 1
                        stats['method_used'] = 'playwright_failed'
            
    except Exception as e:
        stats['rejected']['html_error'] = 1
    
    # If all methods failed, return empty
    stats['method_used'] = 'none'
    if return_stats:
        return [], stats
    return []
