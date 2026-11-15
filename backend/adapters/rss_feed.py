"""
RSS/Atom feed adapter for event extraction.
"""
import feedparser
import sys
from pathlib import Path

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.dates import parse_date
from utils.json_utils import ensure_list
from utils.enrich import enrich_event
from utils.events_only import should_reject_as_article


def extract_events(feed_url, source_config, return_stats=False):
    """
    Extract events from RSS/Atom feed.
    
    Args:
        feed_url: URL of the RSS/Atom feed
        source_config: Source configuration dict with:
            - firm_name: Firm name
            - default_tags_json: List of default tags
            - enforce_events_only: bool (default True)
        return_stats: If True, return extraction stats
    
    Returns:
        list: List of event dicts, or (events, stats) if return_stats=True
    """
    import requests
    
    # Health check: fetch and validate
    try:
        # Get retry config from source
        from utils.retry_handler import retry_request, PermanentError, RetryableError
        from utils.json_utils import ensure_dict
        from utils.rate_limiter import get_rate_limiter
        
        # Get timeout config from source
        timeout_config = ensure_dict(source_config.get('timeout_config', {}))
        timeout_seconds = timeout_config.get('timeout_seconds', 15)  # Default 15s
        
        # Get rate limit config and apply rate limiting
        rate_limit_config = ensure_dict(source_config.get('rate_limit_config', {}))
        max_rps = rate_limit_config.get('max_requests_per_second', 1.0)
        delay = rate_limit_config.get('delay_between_requests', 1.0)
        
        limiter = get_rate_limiter(max_requests_per_second=max_rps, delay_between_requests=delay)
        limiter.wait_if_needed(feed_url)
        
        retry_config = ensure_dict(source_config.get('retry_config', {}))
        max_attempts = retry_config.get('max_attempts', 3)
        backoff_multiplier = retry_config.get('backoff_multiplier', 2.0)
        initial_delay = retry_config.get('initial_delay', 1.0)
        
        try:
            response = retry_request(
                requests.get,
                max_attempts=max_attempts,
                backoff_multiplier=backoff_multiplier,
                initial_delay=initial_delay,
                url=feed_url,
                timeout=timeout_seconds,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                allow_redirects=True
            )
        except (PermanentError, RetryableError) as e:
            # Re-raise as RequestException for compatibility
            raise requests.RequestException(f"Retry failed: {e}") from e
        
        # Check content type (should be RSS/XML)
        content_type = response.headers.get('Content-Type', '').lower()
        if 'xml' not in content_type and 'rss' not in content_type and 'atom' not in content_type:
            # Not a hard failure, but log it
            pass
        
        feed = feedparser.parse(response.text)
        
        # Check for feed parsing errors
        if feed.bozo and feed.bozo_exception:
            if return_stats:
                return [], {'raw': 0, 'kept': 0, 'rejected': {'feed_parse_error': 1}}
            return []
    except requests.RequestException as e:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'feed_http_error': 1}}
        return []
    except Exception as e:
        if return_stats:
            return [], {'raw': 0, 'kept': 0, 'rejected': {'feed_parse_error': 1}}
        return []
    
    events = []
    rejected = {}
    raw_count = 0
    
    firm_name = source_config.get('firm_name', '')
    default_tags = ensure_list(source_config.get('default_tags_json', []))
    enforce_events_only = source_config.get('enforce_events_only', True)
    
    for entry in feed.entries:
        raw_count += 1
        
        # Extract basic fields
        title = entry.get('title', '').strip()
        link = entry.get('link', '').strip()
        
        if not title or not link:
            rejected['no_title_or_link'] = rejected.get('no_title_or_link', 0) + 1
            continue
        
        # Check events-only policy
        if should_reject_as_article(title, link, enforce_events_only):
            rejected['article_like'] = rejected.get('article_like', 0) + 1
            continue
        
        # Extract date
        date_time = None
        # Try published first, then updated
        date_str = entry.get('published') or entry.get('updated')
        if date_str:
            date_time = parse_date(date_str)
        
        # Build event dict
        event = {
            'firm_name': firm_name,
            'event_name': title,
            'link': link,
            'date_time': date_time,
            'tags': list(default_tags),
            'raw_date_text': date_str or ''
        }
        
        # Enrich with format and tags from description if available
        description = entry.get('description', '') or entry.get('summary', '')
        if description:
            event = enrich_event(event, extra_text=description)
        else:
            event = enrich_event(event)
        
        events.append(event)
    
    if return_stats:
        stats = {
            'raw': raw_count,
            'kept': len(events),
            'rejected': rejected
        }
        return events, stats
    
    return events
