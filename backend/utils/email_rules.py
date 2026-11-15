"""
Email Rules: Event-like detection and rejection reasons.

Enforces EMAIL_INGESTION_CONTRACT.md rules.
"""
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.dates import parse_date


# Rejection keywords
EARNINGS_KEYWORDS = [
    r'\bearnings\b',
    r'\bQ[1-4]\b',
    r'\bresults\b',
    r'\bquarterly results\b',
    r'\binvestor relations\b',
    r'\bIR\b',
    r'\b10-Q\b',
    r'\b10-K\b'
]

MARKETING_KEYWORDS = [
    r'\bpress release\b',
    r'\bannounces\b',
    r'\blaunch\b',
    r'\bnew product\b',
    r'\bwhitepaper\b',
    r'\bdownload report\b',
    r'\bmarketing\b'
]

EVENT_KEYWORDS = [
    r'\bwebinar\b',
    r'\bforum\b',
    r'\broundtable\b',
    r'\bbriefing\b',
    r'\bconference\b',
    r'\bsummit\b',
    r'\boutlook\b',
    r'\bpanel\b',
    r'\bseminar\b'
]


def check_earnings_call(subject: str, body: str) -> bool:
    """
    Check if email is an earnings call.
    
    Args:
        subject: Email subject
        body: Email body text
    
    Returns:
        True if earnings-related
    """
    text = f"{subject} {body}".lower()
    for pattern in EARNINGS_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def check_marketing_pr(subject: str, body: str) -> bool:
    """
    Check if email is marketing/PR.
    
    Args:
        subject: Email subject
        body: Email body text
    
    Returns:
        True if marketing/PR
    """
    text = f"{subject} {body}".lower()
    for pattern in MARKETING_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def check_event_anchor(subject: str, body: str) -> bool:
    """
    Check if email contains event keywords.
    
    Args:
        subject: Email subject
        body: Email body text
    
    Returns:
        True if event keywords found
    """
    text = f"{subject} {body}".lower()
    for pattern in EVENT_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def extract_date_time_from_text(text: str) -> Optional[datetime]:
    """
    Extract date/time from text using regex heuristics.
    
    Args:
        text: Text to parse
    
    Returns:
        datetime object if found, None otherwise
    """
    from dateutil import parser as date_parser
    
    # Common patterns
    patterns = [
        # "Jan 12, 2026 15:00"
        r'\b([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2})',
        # "12 January 2026"
        r'\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})',
        # "2026-01-12"
        r'\b(\d{4})-(\d{1,2})-(\d{1,2})',
        # "15:00 CET" (timezone)
        r'\b(\d{1,2}):(\d{2})\s+([A-Z]{2,4})\b',
    ]
    
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            # Try to parse the first match
            match_text = matches[0].group(0)
            try:
                parsed_dt = date_parser.parse(match_text, fuzzy=True)
                # Validate year is reasonable
                if 2000 <= parsed_dt.year <= 2100:
                    # Ensure timezone aware
                    if parsed_dt.tzinfo is None:
                        from datetime import timezone
                        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                    return parsed_dt
            except (ValueError, TypeError):
                pass
    
    # Fallback: try parsing entire text
    try:
        parsed_dt = date_parser.parse(text, fuzzy=True)
        if 2000 <= parsed_dt.year <= 2100:
            if parsed_dt.tzinfo is None:
                from datetime import timezone
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
            return parsed_dt
    except (ValueError, TypeError):
        pass
    
    return None


def is_macro_signal_intel(subject: str, body: str) -> bool:
    """
    Check if email is macro-signal intel (outlook, strategy, market views).
    
    We DO care about: macro outlook calls, sector themes, cross-asset strategy,
    client webinars, "market views", "rates/FX/credit outlook".
    """
    text = f"{subject} {body}".lower()
    
    macro_keywords = [
        r'\boutlook\b',
        r'\bmarket view\b',
        r'\bmarket views\b',
        r'\brates outlook\b',
        r'\bfx outlook\b',
        r'\bcredit outlook\b',
        r'\bstrategy\b',
        r'\bcross-asset\b',
        r'\bsector theme\b',
        r'\bmacro\b',
        r'\bcentral bank\b',
        r'\bmonetary policy\b',
        r'\bfixed income\b',
        r'\bforeign exchange\b'
    ]
    
    for pattern in macro_keywords:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def validate_email_event(subject: str, body: str, date_time: Optional[datetime], links: List[Tuple[str, str]]) -> Tuple[bool, Optional[str]]:
    """
    Validate if email qualifies as an event invitation or macro-signal intel.
    
    Args:
        subject: Email subject
        body: Email body text
        date_time: Extracted date/time (if any)
        links: List of (url, text) tuples
    
    Returns:
        (is_valid, rejection_reason)
        is_valid: True if email qualifies as event/intel
        rejection_reason: Reason code if rejected, None if accepted
    """
    # Check earnings (hard reject)
    if check_earnings_call(subject, body):
        return False, 'earnings_call'
    
    # Check marketing/PR (hard reject)
    if check_marketing_pr(subject, body):
        return False, 'press_release'
    
    # Check if it's macro-signal intel (allows undated)
    is_macro_intel = is_macro_signal_intel(subject, body)
    
    # Check event anchor (required for events, optional for macro intel)
    has_event_anchor = check_event_anchor(subject, body)
    
    if not is_macro_intel and not has_event_anchor:
        return False, 'no_event_anchor'
    
    # For events (not macro intel), require date_time
    if not is_macro_intel and not date_time:
        return False, 'no_date_time'
    
    # For macro intel, prefer link but don't require it
    if not is_macro_intel and not links:
        return False, 'no_link'
    
    return True, None


def extract_participant_text(body: str) -> Optional[str]:
    """
    Extract participant/speaker text from body.
    
    Args:
        body: Email body text
    
    Returns:
        Participant text snippet or None
    """
    # Look for speaker blocks
    speaker_keywords = ['Speakers', 'Panelists', 'Featuring', 'With', 'Participants']
    
    for keyword in speaker_keywords:
        # Find section starting with keyword
        pattern = rf'\b{keyword}\b[:\s]*(.+?)(?=\n\n|\n[A-Z]|\Z)'
        match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    
    return None


def choose_best_link(links: List[Tuple[str, str]]) -> Optional[str]:
    """
    Choose the best link from a list of links.
    
    Prefers registration/event page links.
    
    Args:
        links: List of (url, text) tuples
    
    Returns:
        Best URL or None
    """
    if not links:
        return None
    
    # Prefer links with registration keywords
    registration_keywords = ['register', 'rsvp', 'event', 'webinar', 'conference', 'join']
    
    for url, text in links:
        url_lower = url.lower()
        text_lower = text.lower()
        combined = f"{url_lower} {text_lower}"
        for keyword in registration_keywords:
            if keyword in combined:
                return url
    
    # Fallback to first https link
    for url, text in links:
        if url.startswith('http'):
            return url
    
    return None


def infer_firm_name(from_addr: str, body: str) -> str:
    """
    Infer firm name from sender email or body.
    
    Args:
        from_addr: Sender email address
        body: Email body text
    
    Returns:
        Firm name string
    """
    # Extract domain
    if '@' in from_addr:
        domain = from_addr.split('@')[1].lower()
        # Remove common TLDs and try to extract organization
        domain_parts = domain.split('.')
        if len(domain_parts) >= 2:
            org = domain_parts[-2]  # e.g., "example" from "example.com"
            # Capitalize
            org = org.capitalize()
            return org
    
    return 'Email Source'
