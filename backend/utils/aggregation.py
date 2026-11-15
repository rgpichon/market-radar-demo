"""
Aggregation layer: clean API boundary for querying events and source health.

This module provides a clean interface for the API layer, separating
query logic from HTTP handling.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from pathlib import Path
import sys

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_db, list_saved_event_ids


def get_events(
    q: Optional[str] = None,
    firms: Optional[List[str]] = None,
    firm: Optional[str] = None,
    saved_only: bool = False,
    with_date: bool = True,
    days_ahead: int = 365,
    limit: Optional[int] = None,
    min_signal_score: Optional[int] = None,  # PHASE 6
    tags: Optional[List[str]] = None,  # Priority 6, Phase 3
    format_filter: Optional[str] = None,  # Priority 6, Phase 3
    date_start: Optional[str] = None,  # Priority 6, Phase 3
    date_end: Optional[str] = None  # Priority 6, Phase 3
) -> List[Dict]:
    """
    Get events with filtering.
    
    Args:
        q: Search query (searches firm_name and event_name)
        firms: List of firm names to filter by
        firm: Single firm name (backward compatible)
        saved_only: Only return saved events
        with_date: If True, only return dated events (default: True)
        days_ahead: Number of days ahead to include (default: 365)
        limit: Maximum number of events to return
    
    Returns:
        List of event dicts
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Build query
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    
    # Search filter
    if q:
        query += " AND (firm_name LIKE ? OR event_name LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    
    # Firm filter (single or multi)
    if firms:
        firm_list = [f.strip() for f in firms if f.strip()]
        if firm_list:
            placeholders = ','.join(['?'] * len(firm_list))
            query += f" AND firm_name IN ({placeholders})"
            params.extend(firm_list)
    elif firm:
        # Single firm (backward compatible)
        query += " AND firm_name = ?"
        params.append(firm)
    
    # Saved-only filter
    if saved_only:
        saved_event_ids = set(list_saved_event_ids())
        if not saved_event_ids:
            conn.close()
            return []
        placeholders = ','.join(['?'] * len(saved_event_ids))
        query += f" AND id IN ({placeholders})"
        params.extend(list(saved_event_ids))
    
    # Signal score filter (PHASE 6)
    if min_signal_score is not None:
        query += " AND COALESCE(signal_score, 50) >= ?"
        params.append(min_signal_score)
    
    # Phase 3: Tag filter (Priority 6, Phase 3)
    if tags:
        tag_list = [t.strip() for t in tags if t.strip()]
        if tag_list:
            tag_conditions = []
            for tag in tag_list:
                tag_conditions.append("tags_json LIKE ?")
                params.append(f'%"{tag}"%')
            if tag_conditions:
                query += " AND (" + " OR ".join(tag_conditions) + ")"
    
    # Phase 3: Format filter (Priority 6, Phase 3)
    if format_filter:
        query += " AND format = ?"
        params.append(format_filter)
    
    # Phase 3: Date range filter (Priority 6, Phase 3)
    if date_start:
        query += " AND date_time >= ?"
        params.append(date_start)
    
    if date_end:
        query += " AND date_time <= ?"
        params.append(date_end)
    
    # Date filter (default: upcoming future-dated events only)
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    now_iso = now.isoformat()
    cutoff = (now + timedelta(days=days_ahead)).isoformat()
    
    if with_date:
        # Only dated events, future-only (>= today), within days_ahead window
        query += " AND date_time IS NOT NULL"
        query += " AND date_time >= ?"  # Future-only: exclude past events
        query += " AND date_time <= ?"
        params.extend([now_iso, cutoff])
    else:
        # Include undated events at the end, but dated events must still be future-only
        query += " AND (date_time IS NULL OR (date_time >= ? AND date_time <= ?))"
        params.extend([now_iso, cutoff])
    
    # Ordering: dated first (ascending), then undated (by confidence + recency) (PHASE 1)
    query += " ORDER BY "
    query += "CASE WHEN date_time IS NULL THEN 1 ELSE 0 END,"  # Dated first
    query += "date_time ASC,"  # Dated events ascending
    query += "COALESCE(confidence_score, 50) DESC,"  # Undated by confidence (PHASE 1)
    query += "last_seen DESC"  # Then by recency
    
    # Limit
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    # Convert rows to dicts
    events = []
    for row in rows:
        event = dict(row)
        # Parse JSON fields
        if event.get('tags_json'):
            try:
                event['tags_json'] = json.loads(event['tags_json'])
            except (json.JSONDecodeError, TypeError):
                event['tags_json'] = []
        else:
            event['tags_json'] = []
        
        if event.get('market_scope_json'):
            try:
                event['market_scope_json'] = json.loads(event['market_scope_json'])
            except (json.JSONDecodeError, TypeError):
                event['market_scope_json'] = []
        else:
            event['market_scope_json'] = []
        
        if event.get('bank_participants_json'):
            try:
                event['bank_participants_json'] = json.loads(event['bank_participants_json'])
            except (json.JSONDecodeError, TypeError):
                event['bank_participants_json'] = []
        else:
            event['bank_participants_json'] = []
        
        # Parse participant_roles_json (PHASE 4)
        if event.get('participant_roles_json'):
            try:
                event['participant_roles_json'] = json.loads(event['participant_roles_json'])
            except (json.JSONDecodeError, TypeError):
                event['participant_roles_json'] = None
        
        # Parse speakers_json (Priority 6, Phase 1)
        if event.get('speakers_json'):
            try:
                event['speakers_json'] = json.loads(event['speakers_json']) if isinstance(event['speakers_json'], str) else event['speakers_json']
            except (json.JSONDecodeError, TypeError):
                event['speakers_json'] = []
        else:
            event['speakers_json'] = []
        
        # Parse participant_roles_json if not already parsed
        if event.get('participant_roles_json'):
            try:
                event['participant_roles_json'] = json.loads(event['participant_roles_json']) if isinstance(event['participant_roles_json'], str) else event['participant_roles_json']
            except (json.JSONDecodeError, TypeError):
                event['participant_roles_json'] = {}
        else:
            event['participant_roles_json'] = {}
        
        events.append(event)
    
    return events


def get_source_health() -> Dict[str, Dict]:
    """
    Get source health statistics.
    
    Returns:
        Dict mapping source_id to health stats
    """
    source_stats_path = backend_dir / "source_stats.json"
    
    if not source_stats_path.exists():
        return {}
    
    try:
        with open(source_stats_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def get_source_summary() -> Dict:
    """
    Get summary statistics across all sources.
    
    Returns:
        Dict with summary stats
    """
    health = get_source_health()
    
    if not health:
        return {
            'active_sources': 0,
            'total_future_events': 0,
            'total_dated_events': 0,
            'total_undated_events': 0
        }
    
    active_sources = len(health)
    total_future = sum(s.get('future_count', 0) for s in health.values())
    total_dated = sum(s.get('dated_count', 0) for s in health.values())
    total_undated = sum(s.get('undated_count', 0) for s in health.values())
    
    return {
        'active_sources': active_sources,
        'total_future_events': total_future,
        'total_dated_events': total_dated,
        'total_undated_events': total_undated
    }
