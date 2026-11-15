"""
Post-processing pipeline for extracted events.
Applies per-source quality rules to clean up and filter events.
"""

import re
from .json_utils import ensure_dict, ensure_list


def apply_postprocess(event, source_config):
    """
    Apply post-processing rules to an event.
    
    Args:
        event: dict with keys: event_name, link, date_time, firm_name, tags
        source_config: source configuration dict with optional postprocess_rules
    
    Returns:
        event dict (possibly modified) or None if event should be rejected
    """
    rules = ensure_dict(source_config.get('postprocess_rules'))
    if not rules:
        return event
    
    title = event.get('event_name', '')
    link = event.get('link', '')
    
    # Normalize title
    title = normalize_title(title)
    
    # Check minimum title length
    min_length = rules.get('min_title_length', 0)
    if min_length and len(title) < min_length:
        return None
    
    # Reject if title contains banned phrases (case-insensitive)
    reject_title = ensure_list(rules.get('reject_title_contains'))
    title_lower = title.lower()
    for phrase in reject_title:
        if phrase.lower() in title_lower:
            return None
    
    # Reject if URL contains banned fragments
    reject_url = ensure_list(rules.get('reject_url_contains'))
    link_lower = link.lower()
    for fragment in reject_url:
        if fragment.lower() in link_lower:
            return None
    
    # Require URL to contain at least one of the specified patterns
    require_url = ensure_list(rules.get('require_url_contains_one_of'))
    if require_url:
        found_match = False
        for pattern in require_url:
            if pattern.lower() in link_lower:
                found_match = True
                break
        if not found_match:
            return None
    
    # Apply title prefix stripping
    prefix_strip = ensure_list(rules.get('title_prefix_strip'))
    for prefix in prefix_strip:
        if title.lower().startswith(prefix.lower()):
            title = title[len(prefix):].strip()
    
    # Apply regex replacements to title
    regex_replacements = ensure_list(rules.get('title_regex_replace'))
    for replacement in regex_replacements:
        if isinstance(replacement, dict):
            pattern = replacement.get('pattern', '')
            repl = replacement.get('repl', '')
            if pattern:
                try:
                    title = re.sub(pattern, repl, title, flags=re.IGNORECASE)
                except re.error:
                    pass
    
    # Reject date-only titles (titles that are just month names or dates)
    if rules.get('reject_date_only_titles', False):
        if is_date_only_title(title):
            return None
    
    # Update event with cleaned title
    event['event_name'] = title.strip()
    
    # Final validation - reject if title became too short after cleaning
    if len(event['event_name']) < max(min_length, 5):
        return None
    
    return event


def normalize_title(title):
    """Normalize a title: strip whitespace, collapse multiple spaces."""
    if not title:
        return ""
    # Collapse multiple whitespace to single space
    title = re.sub(r'\s+', ' ', title)
    # Strip leading/trailing whitespace
    return title.strip()


def is_date_only_title(title):
    """
    Check if a title is just a date (like "15 January" or "5 February").
    """
    if not title:
        return True
    
    title_clean = title.strip().lower()
    
    # Check for patterns like "15 january", "5 february", "08 january"
    date_pattern = r'^\d{1,2}\s*(january|february|march|april|may|june|july|august|september|october|november|december)$'
    if re.match(date_pattern, title_clean):
        return True
    
    # Check for patterns like "january 15", "february 5"
    date_pattern2 = r'^(january|february|march|april|may|june|july|august|september|october|november|december)\s*\d{1,2}$'
    if re.match(date_pattern2, title_clean):
        return True
    
    # Check for short date patterns like "jan 15", "feb 5"
    short_date = r'^\d{1,2}\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?$'
    if re.match(short_date, title_clean):
        return True
    
    short_date2 = r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s*\d{1,2}$'
    if re.match(short_date2, title_clean):
        return True
    
    return False


def get_rejection_reason(event, source_config):
    """
    Get the reason why an event would be rejected (for logging).
    Returns None if event would not be rejected.
    """
    rules = ensure_dict(source_config.get('postprocess_rules'))
    if not rules:
        return None
    
    title = normalize_title(event.get('event_name', ''))
    link = event.get('link', '')
    
    min_length = rules.get('min_title_length', 0)
    if min_length and len(title) < min_length:
        return f"title_too_short (<{min_length})"
    
    reject_title = ensure_list(rules.get('reject_title_contains'))
    title_lower = title.lower()
    for phrase in reject_title:
        if phrase.lower() in title_lower:
            return f"title_contains: {phrase}"
    
    reject_url = ensure_list(rules.get('reject_url_contains'))
    link_lower = link.lower()
    for fragment in reject_url:
        if fragment.lower() in link_lower:
            return f"url_contains: {fragment}"
    
    require_url = ensure_list(rules.get('require_url_contains_one_of'))
    if require_url:
        found_match = False
        for pattern in require_url:
            if pattern.lower() in link_lower:
                found_match = True
                break
        if not found_match:
            return f"url_missing_required_pattern"
    
    if rules.get('reject_date_only_titles', False) and is_date_only_title(title):
        return "date_only_title"
    
    return None
