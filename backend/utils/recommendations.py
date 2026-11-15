"""
Recommendation engine for Zone 1: Personalized event recommendations.

Calculates relevance scores based on user interests, behavior, and event characteristics.
"""
import json
from typing import Dict, List
from db import get_user_interests, get_user_behavior, get_db


def calculate_relevance_score(event, user_interests, user_behavior):
    """Calculate how relevant an event is to a user (0-100)."""
    score = 0
    
    # Interest matching (60 points max)
    event_tags = []
    tags_json = event.get('tags_json', '[]')
    if tags_json:
        try:
            if isinstance(tags_json, str):
                event_tags = json.loads(tags_json)
            else:
                event_tags = tags_json
            if not isinstance(event_tags, list):
                event_tags = []
        except:
            event_tags = []
    
    user_topics = user_interests.get('topic', [])
    for tag in event_tags:
        if tag in user_topics:
            score += 20  # High relevance for matching topic
    
    # Format preference (10 points)
    user_formats = user_interests.get('format', [])
    event_format = event.get('format', '')
    if event_format in user_formats:
        score += 10
    
    # Institution matching (20 points)
    user_institutions = user_interests.get('institution', [])
    firm_name = event.get('firm_name', '')
    if any(inst.lower() in firm_name.lower() for inst in user_institutions):
        score += 20
    
    # Signal score boost (10 points)
    signal_score = event.get('signal_score', 0) or 0
    if signal_score > 70:
        score += 10
    
    return min(score, 100)


def get_recommended_events(user_id, limit=20):
    """Get recommended events for a user (Zone 1)."""
    from utils.aggregation import get_events
    
    user_interests = get_user_interests(user_id)
    user_behavior = get_user_behavior(user_id)
    
    # Get all future events
    events = get_events(with_date=True, days_ahead=365)
    
    # Calculate relevance for each event
    scored_events = []
    registered_event_ids = {
        b['event_id'] for b in user_behavior 
        if b['action_type'] == 'register'
    }
    
    for event in events:
        # Skip events user has already registered for
        if event['id'] in registered_event_ids:
            continue
        
        relevance = calculate_relevance_score(event, user_interests, user_behavior)
        if relevance > 0:  # Only include events with some relevance
            scored_events.append({
                'event': event,
                'relevance_score': relevance
            })
    
    # Sort by relevance (descending)
    scored_events.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    return [item['event'] for item in scored_events[:limit]]
