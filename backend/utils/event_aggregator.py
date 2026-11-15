"""
Event Aggregator: Clean separation between scraping and storage.

This module provides a normalized event stream interface.
Scrapers return raw events → Aggregator normalizes → DB storage.

Responsibilities:
- Accept raw extracted events (from ANY lane)
- Normalize fields (date, title, firm, link)
- Apply events-only enforcement
- Apply semantic inference
- Apply deduplication logic
- Emit a clean list of canonical events
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
import hashlib

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.contracts import normalize_event
from utils.events_only import should_reject_as_article
from utils.postprocess import apply_postprocess
from utils.semantics import enrich_event_semantics
from utils.enrich import enrich_event
from utils.json_utils import ensure_list


def compute_event_hash(event: Dict) -> str:
    """
    Compute a deterministic hash for event deduplication.
    
    Uses firm_name + event_name + link (normalized).
    
    Args:
        event: Event dict with firm_name, event_name, link
    
    Returns:
        SHA256 hash as hex string
    """
    firm = str(event.get('firm_name', '')).lower().strip()
    title = str(event.get('event_name', '')).lower().strip()
    link = str(event.get('link', '')).lower().strip()
    
    # Normalize whitespace
    firm = ' '.join(firm.split())
    title = ' '.join(title.split())
    link = ' '.join(link.split())
    
    # Create hash input
    hash_input = f"{firm}|{title}|{link}"
    
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()


def aggregate_events(
    raw_events: List[Dict],
    source_config: Dict,
    existing_event_hashes: Optional[Set[str]] = None
) -> Dict:
    """
    Aggregate and normalize events from any scraping lane.
    
    This is the clean interface between scrapers and storage.
    Scrapers should NOT talk to the database directly.
    
    Args:
        raw_events: List of raw events from adapter (EventRaw format)
        source_config: Source configuration dict
        existing_event_hashes: Optional set of existing event hashes for deduplication
    
    Returns:
        {
            'canonical_events': List[Dict],  # Normalized, deduplicated events
            'aggregation_stats': {
                'raw_count': int,
                'normalized_count': int,
                'after_events_only': int,
                'after_postprocess': int,
                'after_dedup': int,
                'final_count': int,
                'rejected': Dict[str, int]
            }
        }
    """
    if existing_event_hashes is None:
        existing_event_hashes = set()
    
    stats = {
        'raw_count': len(raw_events),
        'normalized_count': 0,
        'after_events_only': 0,
        'after_postprocess': 0,
        'after_dedup': 0,
        'final_count': 0,
        'rejected': {}
    }
    
    # Stage 1: Normalize (EventRaw → EventNormalized)
    normalized_events = []
    for raw_event in raw_events:
        # Add source_id if not present
        if 'source_id' not in raw_event:
            raw_event['source_id'] = source_config.get('id', '')
        
        normalized, rejection_reason = normalize_event(raw_event, source_config)
        if normalized is None:
            stats['rejected'][rejection_reason or 'normalization_failed'] = \
                stats['rejected'].get(rejection_reason or 'normalization_failed', 0) + 1
            continue
        normalized_events.append(normalized)
    
    stats['normalized_count'] = len(normalized_events)
    
    # Stage 2: Events-only filter
    enforce_events_only = source_config.get('enforce_events_only', True)
    events_after_filter = []
    for event in normalized_events:
        title = event.get('event_name', '')
        link = event.get('link', '')
        if should_reject_as_article(title, link, enforce_events_only):
            stats['rejected']['article_like'] = stats['rejected'].get('article_like', 0) + 1
            continue
        events_after_filter.append(event)
    
    stats['after_events_only'] = len(events_after_filter)
    
    # Stage 3: Postprocess rules
    events_after_postprocess = []
    for event in events_after_filter:
        processed = apply_postprocess(event, source_config)
        if processed is None:
            from utils.postprocess import get_rejection_reason
            reason = get_rejection_reason(event, source_config) or 'postprocess_rejected'
            stats['rejected'][reason] = stats['rejected'].get(reason, 0) + 1
            continue
        events_after_postprocess.append(processed)
    
    stats['after_postprocess'] = len(events_after_postprocess)
    
    # Stage 4: Semantic inference
    firm_type = source_config.get('firm_type')
    events_with_semantics = []
    for event in events_after_postprocess:
        # Enrich with format and tags (if not already done)
        if 'format' not in event or not event.get('format') or event.get('format') == 'Unknown':
            event = enrich_event(event, extra_text=event.get('raw_date_text', ''))
        
        # Enrich with semantics
        event = enrich_event_semantics(event, firm_type=firm_type)
        events_with_semantics.append(event)
    
    # Stage 5: Deduplication
    canonical_events = []
    seen_hashes = set(existing_event_hashes)
    
    for event in events_with_semantics:
        event_hash = compute_event_hash(event)
        
        if event_hash in seen_hashes:
            stats['rejected']['duplicate'] = stats['rejected'].get('duplicate', 0) + 1
            continue
        
        seen_hashes.add(event_hash)
        event['_event_hash'] = event_hash  # Store hash for future dedup
        canonical_events.append(event)
    
    stats['after_dedup'] = len(canonical_events)
    stats['final_count'] = len(canonical_events)
    
    return {
        'canonical_events': canonical_events,
        'aggregation_stats': stats
    }


def get_existing_event_hashes(source_id: str) -> Set[str]:
    """
    Get existing event hashes for a source from database.
    
    Used for deduplication during aggregation.
    
    Args:
        source_id: Source identifier
    
    Returns:
        Set of event hashes
    """
    from db import get_db
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Fetch existing events for this source
    cursor.execute("""
        SELECT firm_name, event_name, link
        FROM events
        WHERE source_id = ?
    """, (source_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Compute hashes
    hashes = set()
    for row in rows:
        event = {
            'firm_name': row['firm_name'],
            'event_name': row['event_name'],
            'link': row['link']
        }
        hashes.add(compute_event_hash(event))
    
    return hashes
