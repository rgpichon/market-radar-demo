from datetime import datetime, timezone
from dateutil import parser as date_parser
import re


def parse_date(date_str, source_url=None):
    """
    Best-effort date parsing.
    Returns ISO string (UTC) if parsed successfully, None otherwise.
    
    All parsed dates are normalized to UTC timezone for consistent comparison.
    Invalid years (< 2000 or > 2100) are treated as parse failures.
    """
    if not date_str:
        return None
    
    # Clean the string
    date_str = str(date_str).strip()
    if not date_str:
        return None
    
    # Handle date ranges like "April 9-10, 2027" or "May 7-8, 2026"
    # Extract just the first date from ranges
    date_str = normalize_date_range(date_str)
    
    try:
        # Try dateutil parser (handles many formats)
        dt = date_parser.parse(date_str, fuzzy=True)
        
        # Guardrail: reject implausible years
        if dt.year < 2000 or dt.year > 2100:
            return None
        
        # Normalize to UTC: if naive, assume UTC; if aware, convert
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        
        return dt.isoformat()
    except (ValueError, TypeError, OverflowError):
        # If parsing fails, return None
        return None


def parse_date_safe(date_str):
    """
    Safe date parsing that returns a datetime object or None.
    Use this for comparisons where you need a datetime, not a string.
    """
    iso_str = parse_date(date_str)
    if not iso_str:
        return None
    try:
        # Parse the ISO string back to datetime
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def normalize_date_range(date_str):
    """
    Normalize date ranges to just the start date.
    E.g., "April 9-10, 2027" -> "April 9, 2027"
    """
    # Pattern: Month Day-Day, Year (e.g., "April 9-10, 2027")
    pattern1 = r'^(\w+)\s+(\d{1,2})-\d{1,2},?\s*(\d{4})$'
    match = re.match(pattern1, date_str)
    if match:
        return f"{match.group(1)} {match.group(2)}, {match.group(3)}"
    
    # Pattern: Month Day - Month Day, Year (e.g., "April 9 - April 10, 2027")
    pattern2 = r'^(\w+)\s+(\d{1,2})\s*[-–]\s*\w+\s+\d{1,2},?\s*(\d{4})$'
    match = re.match(pattern2, date_str)
    if match:
        return f"{match.group(1)} {match.group(2)}, {match.group(3)}"
    
    # Pattern: Day-Day Month Year (e.g., "9-10 April 2027")
    pattern3 = r'^(\d{1,2})-\d{1,2}\s+(\w+)\s+(\d{4})$'
    match = re.match(pattern3, date_str)
    if match:
        return f"{match.group(1)} {match.group(2)} {match.group(3)}"
    
    return date_str

