"""
Notification aggregation logic.

Groups related notifications to reduce notification overload.
"""
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import json

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_db


def aggregate_notifications_by_firm(
    notifications: List[Dict], 
    time_window_hours: int = 24
) -> List[Dict]:
    """
    Aggregate notifications by firm within a time window.
    
    Args:
        notifications: List of notification dicts with event info
        time_window_hours: Hours to group within (default 24)
    
    Returns:
        List of aggregated notification dicts
    """
    # Group by firm and time window
    groups = defaultdict(list)
    
    for notif in notifications:
        firm_name = notif.get('firm_name', 'Unknown')
        created_at = notif.get('created_at')
        
        # Parse timestamp
        try:
            if created_at.endswith('Z'):
                created_at = created_at[:-1] + '+00:00'
            dt = datetime.fromisoformat(created_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        
        # Group key: firm + time window
        window_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        key = (firm_name, window_start.isoformat())
        
        groups[key].append(notif)
    
    # Create aggregated notifications
    aggregated = []
    
    for (firm_name, window_start), group_notifs in groups.items():
        if len(group_notifs) == 1:
            # Single notification, no aggregation needed
            aggregated.append(group_notifs[0])
        else:
            # Multiple notifications, create aggregated
            event_ids = [n['event_id'] for n in group_notifs]
            
            aggregated.append({
                'type': 'aggregated',
                'firm_name': firm_name,
                'count': len(group_notifs),
                'event_ids': event_ids,
                'events': group_notifs,
                'created_at': window_start.isoformat(),
                'reason': f'{len(group_notifs)} new events from {firm_name}'
            })
    
    return aggregated


def aggregate_notifications_by_tag(
    notifications: List[Dict],
    time_window_hours: int = 24
) -> List[Dict]:
    """
    Aggregate notifications by tag within a time window.
    
    Args:
        notifications: List of notification dicts with event info
        time_window_hours: Hours to group within (default 24)
    
    Returns:
        List of aggregated notification dicts
    """
    # Group by common tags and time window
    groups = defaultdict(list)
    
    for notif in notifications:
        # Get tags from event (may be in tags_json field)
        tags_json = notif.get('tags_json', '[]')
        try:
            tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
        except:
            tags = []
        
        if not tags:
            # No tags, add as individual notification
            groups[('no_tags',)].append(notif)
            continue
        
        created_at = notif.get('created_at')
        try:
            if created_at.endswith('Z'):
                created_at = created_at[:-1] + '+00:00'
            dt = datetime.fromisoformat(created_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        
        # Group by primary tag (first tag) and time window
        primary_tag = tags[0] if tags else 'no_tags'
        window_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        key = (primary_tag, window_start.isoformat())
        
        groups[key].append(notif)
    
    # Create aggregated notifications
    aggregated = []
    
    for (tag, window_start), group_notifs in groups.items():
        if len(group_notifs) == 1:
            aggregated.append(group_notifs[0])
        else:
            event_ids = [n['event_id'] for n in group_notifs]
            aggregated.append({
                'type': 'aggregated',
                'tag': tag,
                'count': len(group_notifs),
                'event_ids': event_ids,
                'events': group_notifs,
                'created_at': window_start.isoformat(),
                'reason': f'{len(group_notifs)} new events tagged {tag}'
            })
    
    return aggregated


def aggregate_notifications(
    notifications: List[Dict],
    aggregation_mode: str = 'none'
) -> List[Dict]:
    """
    Aggregate notifications based on mode.
    
    Args:
        notifications: List of notification dicts
        aggregation_mode: 'none', 'by_firm', 'by_tag', 'by_time'
    
    Returns:
        List of aggregated notification dicts
    """
    if aggregation_mode == 'none':
        return notifications
    elif aggregation_mode == 'by_firm':
        return aggregate_notifications_by_firm(notifications)
    elif aggregation_mode == 'by_tag':
        return aggregate_notifications_by_tag(notifications)
    else:
        return notifications
