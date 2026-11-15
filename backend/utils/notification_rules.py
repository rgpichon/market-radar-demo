"""
Notification rules evaluation logic.

Evaluates time-based, event type, and location filtering rules
for notifications.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta, timezone

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.json_utils import ensure_list, ensure_dict


def evaluate_time_based_rule(event: Dict, rule: Dict) -> bool:
    """
    Evaluate time-based alert rules.
    
    Args:
        event: Event dict with 'date_time' field (ISO string)
        rule: Time-based rule dict with:
            - enabled: bool
            - alert_days_before: List[int] (e.g., [7, 1])
            - only_future_events: bool
    
    Returns:
        True if event matches time-based rule, False otherwise
    """
    if not rule.get('enabled', True):
        return True  # Rule disabled, don't filter
    
    date_time_str = event.get('date_time')
    if not date_time_str:
        # Event has no date
        return False  # Can't match time-based rule without date
    
    try:
        # Parse ISO date
        if date_time_str.endswith('Z'):
            date_time_str = date_time_str[:-1] + '+00:00'
        event_date = datetime.fromisoformat(date_time_str)
        if event_date.tzinfo is None:
            event_date = event_date.replace(tzinfo=timezone.utc)
        else:
            event_date = event_date.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return False  # Invalid date format
    
    now = datetime.now(timezone.utc)
    
    # Check if only future events
    if rule.get('only_future_events', True) and event_date <= now:
        return False  # Past event, don't alert
    
    # Check if event date is within any alert window
    alert_days = ensure_list(rule.get('alert_days_before', []))
    if not alert_days:
        return True  # No alert days specified, match immediately
    
    for days_before in alert_days:
        alert_date = event_date - timedelta(days=days_before)
        # Check if we're within this alert window (alert_date to event_date)
        if now >= alert_date and now <= event_date:
            return True
    
    return False  # Not within any alert window


def evaluate_event_type_rule(event: Dict, rule: Dict) -> bool:
    """
    Evaluate event type filtering rules.
    
    Args:
        event: Event dict with 'intel_type' and 'event_type' fields
        rule: Event type rule dict with:
            - include_intel_types: List[str]
            - exclude_intel_types: List[str]
            - include_event_types: List[str]
            - exclude_event_types: List[str]
    
    Returns:
        True if event matches event type rule, False otherwise
    """
    intel_type = event.get('intel_type', '').lower() if event.get('intel_type') else ''
    event_type = event.get('event_type', '').lower() if event.get('event_type') else ''
    
    include_intel = ensure_list(rule.get('include_intel_types', []))
    exclude_intel = ensure_list(rule.get('exclude_intel_types', []))
    include_event = ensure_list(rule.get('include_event_types', []))
    exclude_event = ensure_list(rule.get('exclude_event_types', []))
    
    # Normalize lists to lowercase
    include_intel = [t.lower() for t in include_intel]
    exclude_intel = [t.lower() for t in exclude_intel]
    include_event = [t.lower() for t in include_event]
    exclude_event = [t.lower() for t in exclude_event]
    
    # Check intel_type inclusion/exclusion
    if include_intel and intel_type not in include_intel:
        return False  # Not in include list
    if exclude_intel and intel_type in exclude_intel:
        return False  # In exclude list
    
    # Check event_type inclusion/exclusion
    if include_event and event_type and event_type not in include_event:
        return False  # Not in include list
    if exclude_event and event_type and event_type in exclude_event:
        return False  # In exclude list
    
    return True  # Passes all checks


def evaluate_location_rule(event: Dict, rule: Dict) -> bool:
    """
    Evaluate location-based filtering rules.
    
    Args:
        event: Event dict with 'location_city', 'location_country', 'format' fields
        rule: Location rule dict with:
            - cities: List[str]
            - countries: List[str]
            - formats: List[str] (online, in-person, hybrid)
            - exclude_online: bool
    
    Returns:
        True if event matches location rule, False otherwise
    """
    event_city = (event.get('location_city') or '').lower()
    event_country = (event.get('location_country') or '').lower()
    event_format = (event.get('format') or '').lower()
    
    cities = ensure_list(rule.get('cities', []))
    countries = ensure_list(rule.get('countries', []))
    formats = ensure_list(rule.get('formats', []))
    exclude_online = rule.get('exclude_online', False)
    
    # Normalize lists to lowercase
    cities = [c.lower() for c in cities]
    countries = [c.lower() for c in countries]
    formats = [f.lower() for f in formats]
    
    # Check exclude_online
    if exclude_online and event_format == 'online':
        return False
    
    # Check city match
    if cities and event_city:
        if event_city not in cities:
            return False  # City not in allowed list
    
    # Check country match
    if countries and event_country:
        if event_country not in countries:
            return False  # Country not in allowed list
    
    # Check format match
    if formats and event_format:
        if event_format not in formats:
            return False  # Format not in allowed list
    
    # If all rule lists are empty, match everything (no filtering)
    if not cities and not countries and not formats and not exclude_online:
        return True
    
    # If we have rules but event has no location data, don't match
    if (cities or countries or formats) and not event_city and not event_country and not event_format:
        return False
    
    return True  # Passes all checks


def evaluate_all_rules(event: Dict, alert_rules: Dict) -> bool:
    """
    Evaluate all notification rules for an event.
    
    Args:
        event: Event dict
        alert_rules: Alert rules dict from preferences
    
    Returns:
        True if event matches all rules, False otherwise
    """
    if not alert_rules:
        return True  # No rules, match everything
    
    # Evaluate time-based rule
    time_rule = ensure_dict(alert_rules.get('time_based', {}))
    if not evaluate_time_based_rule(event, time_rule):
        return False
    
    # Evaluate event type rule
    event_type_rule = ensure_dict(alert_rules.get('event_type', {}))
    if not evaluate_event_type_rule(event, event_type_rule):
        return False
    
    # Evaluate location rule
    location_rule = ensure_dict(alert_rules.get('location', {}))
    if not evaluate_location_rule(event, location_rule):
        return False
    
    return True  # All rules passed
