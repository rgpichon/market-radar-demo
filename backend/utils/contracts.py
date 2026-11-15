"""
Event contracts: EventRaw and EventNormalized.

This module defines the contract between adapters and the rest of the system.
Adapters MUST output EventRaw. The pipeline normalizes to EventNormalized.
"""
import sys
import re
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.dates import parse_date
from utils.json_utils import ensure_list


# ============================================================================
# EventRaw: What adapters MUST output
# ============================================================================

def validate_event_raw(event: Dict) -> Tuple[bool, Optional[str]]:
    """
    Validate that an event dict conforms to EventRaw contract.
    
    Returns:
        (is_valid, error_message)
    """
    # Required fields
    if 'source_id' not in event:
        return False, "Missing required field: source_id"
    
    if 'event_name' not in event:
        return False, "Missing required field: event_name"
    
    if 'link' not in event:
        return False, "Missing required field: link"
    
    # At least one of date_text or date_time must exist
    if 'date_text' not in event and 'date_time' not in event:
        return False, "Missing required field: at least one of date_text or date_time"
    
    # Validate types
    if not isinstance(event.get('event_name'), str):
        return False, "event_name must be a string"
    
    if not isinstance(event.get('link'), str):
        return False, "link must be a string"
    
    return True, None


# ============================================================================
# EventNormalized: What the pipeline guarantees
# ============================================================================

def normalize_event(raw_event: Dict, source_config: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Normalize EventRaw to EventNormalized.
    
    Rules:
    - Strip whitespace, collapse repeated spaces
    - Absolute URL resolution
    - Reject empty or nonsense titles
    - Ensure tags_json is always a list
    - Ensure date_time is timezone-aware if present
    - Never throw; return (event, rejection_reason)
    
    Args:
        raw_event: EventRaw dict from adapter
        source_config: Source configuration dict
    
    Returns:
        (normalized_event, rejection_reason)
        If rejection_reason is not None, event should be None
    """
    # Validate raw event
    is_valid, error = validate_event_raw(raw_event)
    if not is_valid:
        return None, error
    
    # Start building normalized event
    normalized = {}
    
    # source_id (required)
    normalized['source_id'] = str(raw_event['source_id'])
    
    # firm_name (from source config)
    normalized['firm_name'] = source_config.get('firm_name', '')
    
    # event_name: strip, collapse whitespace, validate
    event_name = str(raw_event['event_name']).strip()
    # Collapse repeated spaces
    event_name = re.sub(r'\s+', ' ', event_name)
    
    # Reject empty or too short
    if not event_name or len(event_name) < 3:
        return None, "event_name too short or empty"
    
    # Reject nonsense titles (common navigation text)
    event_name_lower = event_name.lower()
    nonsense_patterns = [
        'read more', 'learn more', 'register', 'sign up', 'view all',
        'see more', 'click here', 'more info', 'details', 'privacy notice',
        'privacy policy', 'accessibility', 'website policies'
    ]
    if any(pattern in event_name_lower for pattern in nonsense_patterns):
        return None, "event_name looks like navigation text"
    
    normalized['event_name'] = event_name
    
    # link: normalize to absolute URL
    link = str(raw_event['link']).strip()
    if not link:
        return None, "link is empty"
    
    # Skip navigation links
    if link.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
        return None, "link is navigation/anchor"
    
    # Make absolute if relative
    source_url = source_config.get('url', '')
    if source_url and not link.startswith(('http://', 'https://')):
        link = urljoin(source_url, link)
    
    # Normalize URL (remove fragment, normalize query)
    parsed = urlparse(link)
    normalized_link = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        normalized_link += f"?{parsed.query}"
    
    normalized['link'] = normalized_link
    
    # date_time: parse from date_text or use existing date_time
    date_time = None
    if 'date_time' in raw_event and raw_event['date_time']:
        # Already parsed
        date_str = raw_event['date_time']
        if isinstance(date_str, str):
            # Try to parse if it's a string
            date_time = parse_date(date_str)
        else:
            # Assume it's already a datetime or ISO string
            date_time = date_str
    elif 'date_text' in raw_event and raw_event['date_text']:
        # Parse from text
        date_time = parse_date(raw_event['date_text'])
    
    # Ensure timezone-aware if present
    if date_time:
        if isinstance(date_time, str):
            # Parse ISO string
            try:
                if date_time.endswith('Z'):
                    date_time = date_time[:-1] + '+00:00'
                dt = datetime.fromisoformat(date_time)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                date_time = dt.isoformat()
            except (ValueError, TypeError):
                date_time = None
        elif isinstance(date_time, datetime):
            # Ensure timezone-aware
            if date_time.tzinfo is None:
                date_time = date_time.replace(tzinfo=timezone.utc)
            else:
                date_time = date_time.astimezone(timezone.utc)
            date_time = date_time.isoformat()
    
    normalized['date_time'] = date_time
    
    # format: default to 'Unknown', will be enriched later
    normalized['format'] = raw_event.get('format', 'Unknown')
    
    # tags_json: ensure it's a list
    tags = ensure_list(raw_event.get('tags', []))
    # Merge with default_tags from source config
    default_tags = ensure_list(source_config.get('default_tags_json', []))
    all_tags = list(set(default_tags + tags))  # Deduplicate
    normalized['tags_json'] = all_tags
    
    # Optional fields
    if 'location' in raw_event:
        normalized['location'] = str(raw_event['location']).strip()
    
    if 'speakers' in raw_event:
        normalized['speakers'] = raw_event['speakers']
    
    if 'extra' in raw_event:
        normalized['extra'] = raw_event['extra']
    
    # Semantic fields will be added by pipeline stage 5
    # For now, set defaults
    normalized['event_type'] = 'other'
    normalized['signal_level'] = 'medium'
    normalized['market_scope_json'] = []
    
    return normalized, None
