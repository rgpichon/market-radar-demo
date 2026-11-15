"""
Recommendation engine for suggesting events based on user interest.

Tracks user engagement and suggests similar events.
"""
import sys
from pathlib import Path
from typing import Dict, List
from collections import Counter
import json

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_db


def track_engagement(event_id: str, action: str = 'view'):
    """
    Track user engagement with an event.
    
    Args:
        event_id: Event ID
        action: Action type ('view', 'click', 'save')
    """
    from datetime import datetime, timezone
    
    conn = get_db()
    cursor = conn.cursor()
    
    now = datetime.now(timezone.utc).isoformat()
    
    cursor.execute("""
        INSERT INTO user_engagement (event_id, action, action_timestamp)
        VALUES (?, ?, ?)
    """, (event_id, action, now))
    
    conn.commit()
    conn.close()


def calculate_interest_scores() -> Dict[str, Dict[str, float]]:
    """
    Calculate interest scores for firms, tags, and event types.
    
    Returns:
        Dict with 'firms', 'tags', 'event_types' keys containing score dicts
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Get viewed events
    cursor.execute("""
        SELECT DISTINCT ue.event_id, e.firm_name, e.tags_json, e.intel_type
        FROM user_engagement ue
        JOIN events e ON ue.event_id = e.id
        WHERE ue.action = 'view'
    """)
    
    viewed_events = cursor.fetchall()
    conn.close()
    
    # Count frequencies
    firm_counts = Counter()
    tag_counts = Counter()
    intel_type_counts = Counter()
    
    for event in viewed_events:
        event_id, firm_name, tags_json, intel_type = event
        
        if firm_name:
            firm_counts[firm_name] += 1
        
        # Parse tags
        try:
            tags = json.loads(tags_json) if tags_json else []
            for tag in tags:
                if tag:
                    tag_counts[tag] += 1
        except:
            pass
        
        if intel_type:
            intel_type_counts[intel_type] += 1
    
    # Normalize scores (0-1)
    total_views = len(viewed_events)
    if total_views == 0:
        return {'firms': {}, 'tags': {}, 'event_types': {}}
    
    firm_scores = {firm: count / total_views for firm, count in firm_counts.items()}
    tag_scores = {tag: count / total_views for tag, count in tag_counts.items()}
    intel_type_scores = {it: count / total_views for it, count in intel_type_counts.items()}
    
    return {
        'firms': firm_scores,
        'tags': tag_scores,
        'event_types': intel_type_scores
    }


def recommend_events(limit: int = 10) -> List[Dict]:
    """
    Recommend events based on user interest patterns.
    
    Args:
        limit: Maximum number of recommendations
    
    Returns:
        List of event dicts with recommendation scores
    """
    # Get interest scores
    scores = calculate_interest_scores()
    
    if not scores['firms'] and not scores['tags'] and not scores['event_types']:
        return []  # No engagement data
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get future events that user hasn't viewed
    cursor.execute("""
        SELECT e.*
        FROM events e
        WHERE e.date_time IS NOT NULL
        AND e.date_time >= datetime('now')
        AND e.id NOT IN (
            SELECT DISTINCT event_id FROM user_engagement WHERE action = 'view'
        )
        ORDER BY e.date_time ASC
        LIMIT 500
    """)
    
    candidate_events = []
    for row in cursor.fetchall():
        event = dict(row)
        
        # Calculate recommendation score
        score = 0.0
        
        # Firm match
        firm_name = event.get('firm_name', '')
        if firm_name in scores['firms']:
            score += scores['firms'][firm_name] * 0.4
        
        # Tag match
        tags_json = event.get('tags_json', '[]')
        try:
            tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
            for tag in tags:
                if tag in scores['tags']:
                    score += scores['tags'][tag] * 0.4 / len(tags)  # Distribute weight across tags
        except:
            pass
        
        # Intel type match
        intel_type = event.get('intel_type', '')
        if intel_type in scores['event_types']:
            score += scores['event_types'][intel_type] * 0.2
        
        if score > 0:
            event['recommendation_score'] = score
            candidate_events.append(event)
    
    conn.close()
    
    # Sort by score (descending) and return top N
    candidate_events.sort(key=lambda x: x.get('recommendation_score', 0), reverse=True)
    
    return candidate_events[:limit]
