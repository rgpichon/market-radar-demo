"""
Playwright adapter for JavaScript-rendered pages.

Uses Playwright to render pages with JavaScript execution,
then extracts events using the same selectors as html_list adapter.
"""
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None

from utils.json_utils import ensure_dict, ensure_list


def extract_events_playwright(source_config: Dict, return_stats: bool = False, use_pool: bool = True) -> Tuple[List[Dict], Dict]:
    """
    Extract events from a JavaScript-rendered page using Playwright.
    
    This function:
    1. Launches Playwright browser (or uses pool if enabled)
    2. Navigates to the page and waits for content to load
    3. Gets rendered HTML
    4. Extracts events using same selectors as html_list adapter
    5. Closes browser (or returns page to pool)
    
    Args:
        source_config: Source configuration with:
            - url: Page URL
            - selectors_json: Same selectors as html_list adapter
            - firm_name: Firm name
            - default_tags_json: Default tags
            - playwright_config: Optional config for wait time, timeout, etc.
        return_stats: If True, return stats dict
        use_pool: If True, use browser pool (default: True)
        
    Returns:
        (events_list, stats_dict) if return_stats=True, else events_list
        Returns empty list if Playwright not available or extraction fails
    """
    if not PLAYWRIGHT_AVAILABLE:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'playwright_not_available': 1}}
        return []
    
    source_url = source_config.get('url', '')
    firm_name = source_config.get('firm_name', '')
    default_tags = ensure_list(source_config.get('default_tags_json', []))
    selectors = ensure_dict(source_config.get('selectors_json', {}))
    
    # Playwright-specific config
    playwright_config = ensure_dict(source_config.get('playwright_config', {}))
    wait_time = playwright_config.get('wait_time', 2000)  # Wait 2 seconds for JS to load (default)
    timeout = playwright_config.get('timeout', 30000)  # 30 second timeout (default)
    wait_selector = playwright_config.get('wait_selector', None)  # Optional: wait for specific selector
    
    events = []
    stats = {
        'raw': 0,
        'kept': 0,
        'rejected': {}
    }
    
    def reject(reason):
        stats['rejected'][reason] = stats['rejected'].get(reason, 0) + 1
    
    # Use browser pool if enabled
    if use_pool:
        try:
            from utils.browser_pool import get_browser_pool
            pool = get_browser_pool(max_requests=10, max_age_seconds=300)
            
            with pool.get_page() as page:
                try:
                    # Navigate to page
                    page.goto(source_url, wait_until='domcontentloaded', timeout=timeout)
                    
                    # Wait for JavaScript to render (configurable)
                    if wait_selector:
                        page.wait_for_selector(wait_selector, timeout=timeout)
                    else:
                        page.wait_for_timeout(wait_time)
                    
                    # Get rendered HTML
                    html = page.content()
                    
                    # Extract events using same logic as html_list adapter
                    from adapters.html_list import extract_events
                    events, html_stats = extract_events(html, source_config, return_stats=True)
                    stats.update(html_stats)
                    
                except PlaywrightTimeoutError:
                    reject('playwright_timeout')
                    try:
                        html = page.content()
                        from adapters.html_list import extract_events
                        events, html_stats = extract_events(html, source_config, return_stats=True)
                        stats.update(html_stats)
                    except:
                        pass
                except Exception as e:
                    reject(f'playwright_error: {str(e)}')
            
            if return_stats:
                return events, stats
            return events
            
        except ImportError:
            # Browser pool not available, fall back to direct usage
            use_pool = False
    
    # Fallback: Direct browser usage (no pool)
    if not use_pool:
        try:
            with sync_playwright() as p:
                # Launch browser (headless by default)
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                try:
                    # Navigate to page
                    page.goto(source_url, wait_until='domcontentloaded', timeout=timeout)
                    
                    # Wait for JavaScript to render (configurable)
                    if wait_selector:
                        # Wait for specific element to appear
                        page.wait_for_selector(wait_selector, timeout=timeout)
                    else:
                        # Wait fixed time for JS to execute
                        page.wait_for_timeout(wait_time)
                    
                    # Get rendered HTML
                    html = page.content()
                    
                    # Extract events using same logic as html_list adapter
                    # Reuse extraction logic from html_list.py
                    from adapters.html_list import extract_events
                    events, html_stats = extract_events(html, source_config, return_stats=True)
                    
                    # Merge stats
                    stats.update(html_stats)
                    
                except PlaywrightTimeoutError:
                    reject('playwright_timeout')
                    # Try to get HTML anyway (might be partially loaded)
                    try:
                        html = page.content()
                        from adapters.html_list import extract_events
                        events, html_stats = extract_events(html, source_config, return_stats=True)
                        stats.update(html_stats)
                    except:
                        pass
                
                finally:
                    browser.close()
        
        except Exception as e:
            reject(f'playwright_error: {str(e)}')
            # Save screenshot for debugging if possible
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(source_url, timeout=10000)
                    screenshot_path = backend_dir / "_evidence" / "playwright" / f"error_{hash(source_url) % 10000}.png"
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path))
                    browser.close()
            except:
                pass
    
    if return_stats:
        return events, stats
    return events


def fetch_detail_with_playwright(url: str, selectors: Dict, timeout: int = 30000) -> Optional[str]:
    """
    Fetch a detail page using Playwright and extract content.
    
    Args:
        url: Detail page URL
        selectors: Selectors dict (for title, description, etc.)
        timeout: Request timeout
        
    Returns:
        HTML content or None
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            page.wait_for_timeout(2000)  # Wait for JS
            
            html = page.content()
            browser.close()
            return html
    except Exception:
        return None
