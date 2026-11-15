"""
Storyline detection and grouping.

Groups related events into storylines based on:
- Same firm + similar topics
- Related events over time
- Common participants
"""
from typing import Dict, List
from datetime import datetime
from collections import defaultdict
import json


def detect_storylines(events: List[Dict], max_days_apart: int = 90) -> List[Dict]:
    """
    Detect storylines from events.
    
    Args:
        events: List of event dicts
        max_days_apart: Maximum days between events in same storyline
    
    Returns:
        List of storyline dicts with events
    """
    storylines = []
    
    # Group by firm + primary topic
    firm_topic_groups = defaultdict(list)
    
    for event in events:
        firm = event.get('firm_name', '')
        tags_json = event.get('tags_json', '[]')
        
        # Parse tags
        try:
            if isinstance(tags_json, str):
                tags = json.loads(tags_json)
            else:
                tags = tags_json
            if not isinstance(tags, list):
                tags = []
        except:
            tags = []
        
        primary_topic = tags[0] if tags else 'General'
        
        key = (firm, primary_topic)
        firm_topic_groups[key].append(event)
    
    # Create storylines from groups
    for (firm, topic), group_events in firm_topic_groups.items():
        if len(group_events) >= 2:
            # Sort by date
            group_events.sort(key=lambda e: e.get('date_time', '') or '')
            
            # Check if events are close enough in time
            storyline_events = []
            for i, event in enumerate(group_events):
                if i == 0:
                    storyline_events.append(event)
                else:
                    prev_date = storyline_events[-1].get('date_time')
                    curr_date = event.get('date_time')
                    
                    if prev_date and curr_date:
                        try:
                            # Handle ISO format dates
                            prev_str = prev_date.replace('Z', '+00:00') if 'Z' in prev_date else prev_date
                            curr_str = curr_date.replace('Z', '+00:00') if 'Z' in curr_date else curr_date
                            
                            prev_dt = datetime.fromisoformat(prev_str)
                            curr_dt = datetime.fromisoformat(curr_str)
                            days_apart = (curr_dt - prev_dt).days
                            
                            if days_apart <= max_days_apart:
                                storyline_events.append(event)
                        except Exception:
                            # If date parsing fails, include event anyway
                            storyline_events.append(event)
            
            if len(storyline_events) >= 2:
                storyline_id = f"{firm}_{topic}_{abs(hash(str([e.get('id') for e in storyline_events]))) % 10000}"
                storylines.append({
                    'id': storyline_id,
                    'title': f"{firm} - {topic}",
                    'firm': firm,
                    'topic': topic,
                    'events': storyline_events,
                    'event_count': len(storyline_events),
                    'start_date': storyline_events[0].get('date_time'),
                    'end_date': storyline_events[-1].get('date_time')
                })
    
    return storylines
