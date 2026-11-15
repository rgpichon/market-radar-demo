"""
Simple browser pool for Playwright.
Reuses browser instances across sources to reduce startup overhead.
"""
import sys
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
from datetime import datetime, timedelta
import threading

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from playwright.sync_api import sync_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None
    Browser = None
    Page = None


class BrowserPool:
    """
    Simple browser pool that reuses browser instances.
    
    Features:
    - Reuses browser across multiple requests
    - Closes browser after max_requests or max_age
    - Thread-safe (uses locks)
    """
    
    def __init__(self, max_requests: int = 10, max_age_seconds: int = 300):
        """
        Initialize browser pool.
        
        Args:
            max_requests: Maximum requests per browser instance before closing
            max_age_seconds: Maximum age of browser instance before closing
        """
        self.max_requests = max_requests
        self.max_age_seconds = max_age_seconds
        self._playwright = None
        self._browser = None
        self._request_count = 0
        self._created_at = None
        self._lock = threading.Lock()
    
    def _ensure_playwright(self):
        """Ensure Playwright context is initialized."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not available")
        
        if self._playwright is None:
            self._playwright = sync_playwright().start()
    
    def _ensure_browser(self):
        """Ensure browser instance exists and is valid."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not available")
        
        self._ensure_playwright()
        
        # Check if browser needs to be recreated
        should_recreate = False
        
        if self._browser is None:
            should_recreate = True
        elif self._request_count >= self.max_requests:
            should_recreate = True
        elif self._created_at:
            age = (datetime.now() - self._created_at).total_seconds()
            if age >= self.max_age_seconds:
                should_recreate = True
        
        if should_recreate:
            self._close_browser()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._request_count = 0
            self._created_at = datetime.now()
    
    def _close_browser(self):
        """Close current browser instance."""
        if self._browser:
            try:
                self._browser.close()
            except:
                pass
            self._browser = None
        self._request_count = 0
        self._created_at = None
    
    @contextmanager
    def get_page(self):
        """
        Get a page from the browser pool.
        
        Usage:
            with pool.get_page() as page:
                page.goto(url)
                html = page.content()
        """
        with self._lock:
            self._ensure_browser()
            page = self._browser.new_page()
            self._request_count += 1
        
        try:
            yield page
        finally:
            try:
                page.close()
            except:
                pass
    
    def close(self):
        """Close browser and Playwright context."""
        with self._lock:
            self._close_browser()
            if self._playwright:
                try:
                    self._playwright.stop()
                except:
                    pass
                self._playwright = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Global browser pool instance
_global_pool: Optional[BrowserPool] = None
_pool_lock = threading.Lock()


def get_browser_pool(max_requests: int = 10, max_age_seconds: int = 300) -> BrowserPool:
    """
    Get or create global browser pool instance.
    
    Args:
        max_requests: Maximum requests per browser instance
        max_age_seconds: Maximum age of browser instance in seconds
        
    Returns:
        BrowserPool instance
    """
    global _global_pool
    
    with _pool_lock:
        if _global_pool is None:
            _global_pool = BrowserPool(max_requests=max_requests, max_age_seconds=max_age_seconds)
        return _global_pool


def close_browser_pool():
    """Close global browser pool."""
    global _global_pool
    
    with _pool_lock:
        if _global_pool:
            _global_pool.close()
            _global_pool = None
