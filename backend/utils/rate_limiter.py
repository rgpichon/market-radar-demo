"""
Rate limiter for respectful scraping.

Limits requests per domain and adds delays between requests.
"""
import time
from typing import Dict, Optional
from collections import defaultdict
from urllib.parse import urlparse


class RateLimiter:
    """
    Rate limiter that tracks requests per domain.
    """
    def __init__(self, max_requests_per_second: float = 1.0, delay_between_requests: float = 1.0):
        """
        Args:
            max_requests_per_second: Maximum requests per second per domain
            delay_between_requests: Minimum delay between requests in seconds
        """
        self.max_requests_per_second = max_requests_per_second
        self.delay_between_requests = delay_between_requests
        self.request_times: Dict[str, list] = defaultdict(list)
        self.last_request_time: Dict[str, float] = {}
    
    def get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split('/')[0]
    
    def wait_if_needed(self, url: str):
        """
        Wait if needed to respect rate limits.
        
        Args:
            url: URL being requested
        """
        domain = self.get_domain(url)
        now = time.time()
        
        # Check delay between requests
        if domain in self.last_request_time:
            time_since_last = now - self.last_request_time[domain]
            if time_since_last < self.delay_between_requests:
                wait_time = self.delay_between_requests - time_since_last
                time.sleep(wait_time)
                now = time.time()
        
        # Check requests per second
        cutoff_time = now - 1.0
        self.request_times[domain] = [
            t for t in self.request_times[domain] if t > cutoff_time
        ]
        
        if len(self.request_times[domain]) >= self.max_requests_per_second:
            # Need to wait
            oldest_request = min(self.request_times[domain])
            wait_time = 1.0 - (now - oldest_request)
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.time()
        
        # Record this request
        self.request_times[domain].append(now)
        self.last_request_time[domain] = now


# Global rate limiter instance
_global_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(max_requests_per_second: float = 1.0, delay_between_requests: float = 1.0) -> RateLimiter:
    """
    Get global rate limiter instance (singleton).
    
    Args:
        max_requests_per_second: Max requests per second
        delay_between_requests: Delay between requests
    
    Returns:
        RateLimiter instance
    """
    global _global_rate_limiter
    
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter(max_requests_per_second, delay_between_requests)
    
    return _global_rate_limiter


def reset_rate_limiter():
    """Reset global rate limiter (for testing)."""
    global _global_rate_limiter
    _global_rate_limiter = None
