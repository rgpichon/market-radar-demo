"""
Registration type detection and extraction utilities (PRIORITY 2, Phase 4).
"""
import re
from typing import Optional, Dict
from urllib.parse import urljoin, urlparse


REGISTRATION_KEYWORDS = {
    'public': ['public', 'free', 'open to all', 'open to everyone', 'all welcome', 'no registration required'],
    'members_only': ['members only', 'members-only', 'for members', 'member exclusive', 'membership required'],
    'invitation_only': ['invitation only', 'invitation-only', 'by invitation', 'invite only', 'invited guests only', 'by invite'],
    'fee_based': ['fee', 'paid', 'ticket', 'cost', 'registration fee', 'entry fee', 'ticket price', 'admission fee'],
    'registration_required': ['register', 'registration required', 'rsvp required', 'rsvp', 'sign up', 'registration', 'book now']
}


def detect_registration_type(event_name: str, description: str = '') -> Optional[str]:
    """
    Detect registration type from event name and description using keyword matching.
    
    Args:
        event_name: Event title
        description: Event description (optional)
    
    Returns:
        str: Registration type ('public', 'members_only', 'invitation_only', 'fee_based', 'registration_required') or None
    """
    if not event_name and not description:
        return None
    
    text = f"{event_name} {description}".lower()
    
    # Check for each registration type (order matters - more specific first)
    # Check invitation_only first (most restrictive)
    for keyword in REGISTRATION_KEYWORDS['invitation_only']:
        if keyword in text:
            return 'invitation_only'
    
    # Check members_only
    for keyword in REGISTRATION_KEYWORDS['members_only']:
        if keyword in text:
            return 'members_only'
    
    # Check fee_based
    for keyword in REGISTRATION_KEYWORDS['fee_based']:
        if keyword in text:
            return 'fee_based'
    
    # Check registration_required
    for keyword in REGISTRATION_KEYWORDS['registration_required']:
        if keyword in text:
            return 'registration_required'
    
    # Check public (least restrictive, but explicit)
    for keyword in REGISTRATION_KEYWORDS['public']:
        if keyword in text:
            return 'public'
    
    return None


def extract_registration_deadline(text: str) -> Optional[str]:
    """
    Extract registration deadline from text.
    
    Looks for patterns like:
    - "Registration deadline: March 1st"
    - "Deadline: 2024-03-01"
    - "Register by March 1"
    - "RSVP by 1 March 2024"
    
    Args:
        text: Text to search for deadline
    
    Returns:
        str: Deadline text if found, None otherwise
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Common deadline patterns
    deadline_patterns = [
        r'registration deadline[:\s]+([^\.\n]+)',
        r'deadline[:\s]+([^\.\n]+)',
        r'register by[:\s]+([^\.\n]+)',
        r'rsvp by[:\s]+([^\.\n]+)',
        r'registration closes[:\s]+([^\.\n]+)',
        r'closing date[:\s]+([^\.\n]+)',
        r'registration required by[:\s]+([^\.\n]+)',
        r'by[:\s]+([^\.\n]+?)(?:\.|$)',  # "by March 1st" or "by 2024-03-01"
    ]
    
    for pattern in deadline_patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            deadline = match.group(1).strip()
            # Clean up common trailing phrases
            deadline = re.sub(r'\s*(\.|,|;).*$', '', deadline)
            if deadline and len(deadline) < 100:  # Reasonable length
                return deadline.strip()
    
    return None


def extract_registration_fee(text: str) -> Optional[str]:
    """
    Extract registration fee information from text.
    
    Looks for patterns like:
    - "Registration fee: $100"
    - "Cost: €50"
    - "Free admission"
    - "Ticket price: £75"
    
    Args:
        text: Text to search for fee information
    
    Returns:
        str: Fee text if found, None otherwise
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Check for "free" first
    if 'free' in text_lower and ('admission' in text_lower or 'entry' in text_lower or 'registration' in text_lower):
        return 'Free'
    
    # Fee patterns
    fee_patterns = [
        r'registration fee[:\s]+([^\s\.\n]+(?:\s+[^\s\.\n]+)?)',
        r'fee[:\s]+([^\s\.\n]+(?:\s+[^\s\.\n]+)?)',
        r'cost[:\s]+([^\s\.\n]+(?:\s+[^\s\.\n]+)?)',
        r'ticket price[:\s]+([^\s\.\n]+(?:\s+[^\s\.\n]+)?)',
        r'admission fee[:\s]+([^\s\.\n]+(?:\s+[^\s\.\n]+)?)',
        r'entry fee[:\s]+([^\s\.\n]+(?:\s+[^\s\.\n]+)?)',
    ]
    
    for pattern in fee_patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            fee = match.group(1).strip()
            # Clean up
            fee = re.sub(r'\s*(\.|,|;).*$', '', fee)
            if fee and len(fee) < 50:  # Reasonable length
                return fee.strip()
    
    return None
