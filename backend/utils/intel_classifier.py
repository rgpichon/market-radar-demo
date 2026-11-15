#!/usr/bin/env python3
"""
Intel Classification Module

Classifies items as events vs intel_items and determines intel_type.
"""
import re
from typing import Dict, Optional, Tuple
from datetime import datetime


# Macro keywords (positive signals)
MACRO_KEYWORDS = [
    'rates', 'inflation', 'growth', 'fx', 'forex', 'credit', 'geopolitics',
    'monetary policy', 'fiscal policy', 'central bank', 'fed', 'ecb', 'boj',
    'yield curve', 'spread', 'sovereign', 'corporate credit', 'equity',
    'commodities', 'oil', 'gold', 'currency', 'dollar', 'euro', 'yen',
    'outlook', 'forecast', 'scenario', 'risk', 'volatility', 'liquidity'
]

# Outlook language patterns
OUTLOOK_PATTERNS = [
    r'\bour\s+view\b',
    r'\bwe\s+expect\b',
    r'\bwe\s+believe\b',
    r'\bscenario\b',
    r'\boutlook\b',
    r'\bforecast\b',
    r'\bprojection\b',
    r'\brisk\s+factors?\b',
    r'\bkey\s+drivers?\b'
]

# Event-type indicators
EVENT_INDICATORS = [
    'webinar', 'conference', 'roundtable', 'briefing', 'seminar',
    'forum', 'panel', 'summit', 'event', 'meeting', 'call',
    'presentation', 'launch', 'announcement'
]

# Intel-type indicators
BRIEFING_INDICATORS = ['briefing', 'update', 'alert', 'flash']
OUTLOOK_INDICATORS = ['outlook', 'forecast', 'view', 'perspective', 'scenario']
WEBINAR_INDICATORS = ['webinar', 'webcast', 'online event', 'virtual event']
NOTE_INDICATORS = ['note', 'commentary', 'analysis', 'insight', 'thought']
INVITE_INDICATORS = ['invitation', 'invite', 'rsvp', 'register', 'join us']

# Debate indicators (for macroeconomic debates/discussions)
DEBATE_INDICATORS = [
    'debate', 'discussion', 'dialogue', 'roundtable', 'panel discussion',
    'fireside chat', 'conversation', 'exchange', 'forum', 'symposium',
    'differing views', 'contrasting perspectives', 'multiple viewpoints'
]

# Signal indicators (for policy announcements/signals)
SIGNAL_INDICATORS = [
    'announcement', 'decision', 'statement', 'release', 'policy decision',
    'rate decision', 'monetary policy decision', 'fomc decision', 'ecb decision',
    'press conference', 'policy statement', 'forward guidance', 'signals',
    'policy signal', 'central bank decision', 'policy announcement'
]


def classify_intel_type(
    event_name: str,
    description: str = '',
    date_time: Optional[str] = None,
    link: str = ''
) -> Tuple[str, int]:
    """
    Classify an item's intel_type and confidence.
    
    Returns:
        (intel_type, confidence_score) where:
        - intel_type: 'event' | 'briefing' | 'outlook' | 'webinar' | 'note' | 'invite' | 'debate' | 'signal'
        - confidence_score: 0-100
    """
    text = f"{event_name} {description} {link}".lower()
    
    # Check for signal indicators FIRST (policy announcements are high priority)
    signal_score = sum(1 for ind in SIGNAL_INDICATORS if ind in text)
    if signal_score >= 1:
        # Boost confidence if it's a policy-related signal
        if any(kw in text for kw in ['policy', 'monetary', 'fiscal', 'central bank', 'fed', 'ecb']):
            return ('signal', 85)
        return ('signal', 75)
    
    # Check for debate indicators (discussions/roundtables)
    debate_score = sum(1 for ind in DEBATE_INDICATORS if ind in text)
    if debate_score >= 1:
        # Boost confidence if multiple debate indicators
        if debate_score >= 2:
            return ('debate', 80)
        return ('debate', 70)
    
    # Check for explicit event indicators
    event_score = sum(1 for ind in EVENT_INDICATORS if ind in text)
    if event_score >= 2:
        return ('event', min(90, 60 + event_score * 10))
    
    # Check for webinar
    webinar_score = sum(1 for ind in WEBINAR_INDICATORS if ind in text)
    if webinar_score >= 1:
        return ('webinar', 75)
    
    # Check for briefing
    briefing_score = sum(1 for ind in BRIEFING_INDICATORS if ind in text)
    if briefing_score >= 1:
        return ('briefing', 70)
    
    # Check for outlook
    outlook_score = sum(1 for ind in OUTLOOK_INDICATORS if ind in text)
    outlook_lang = sum(1 for pattern in OUTLOOK_PATTERNS if re.search(pattern, text, re.I))
    if outlook_score >= 1 or outlook_lang >= 1:
        return ('outlook', 75)
    
    # Check for invite
    invite_score = sum(1 for ind in INVITE_INDICATORS if ind in text)
    if invite_score >= 1:
        return ('invite', 70)
    
    # Default to note for undated items, event for dated
    if date_time:
        return ('event', 50)
    else:
        return ('note', 60)


def has_explicit_date(date_time: Optional[str], raw_date_text: str = '') -> bool:
    """
    Determine if date_time represents an explicit date or is inferred/undated.
    
    Returns:
        True if explicit date, False if inferred/undated
    """
    if not date_time:
        return False
    
    # If raw_date_text suggests it was parsed from content (not explicit)
    if raw_date_text:
        inferred_indicators = ['published', 'updated', 'posted', 'sent']
        if any(ind in raw_date_text.lower() for ind in inferred_indicators):
            return False
    
    # Try to parse as datetime
    try:
        # If it's a valid ISO datetime, consider it explicit
        datetime.fromisoformat(date_time.replace('Z', '+00:00'))
        return True
    except:
        return False


def calculate_confidence_score(
    intel_type: str,
    has_explicit_date: bool,
    macro_keyword_density: float,
    has_speakers: bool = False,
    has_institutions: bool = False
) -> int:
    """
    Calculate confidence score (0-100) for an intel item.
    
    Args:
        intel_type: Classified intel type
        has_explicit_date: Whether date is explicit
        macro_keyword_density: Ratio of macro keywords found (0-1)
        has_speakers: Whether speakers/participants mentioned
        has_institutions: Whether institutions mentioned
    
    Returns:
        Confidence score 0-100
    """
    score = 50  # Base
    
    # Boost for explicit dates
    if has_explicit_date:
        score += 15
    
    # Boost for macro keywords
    score += int(macro_keyword_density * 20)
    
    # Boost for speakers/institutions
    if has_speakers:
        score += 10
    if has_institutions:
        score += 5
    
    # Type-specific adjustments
    if intel_type == 'event' and has_explicit_date:
        score += 10
    elif intel_type == 'outlook':
        score += 5
    
    return min(100, max(0, score))


def extract_macro_keyword_density(text: str) -> float:
    """
    Calculate macro keyword density in text.
    
    Returns:
        Density ratio (0-1)
    """
    if not text:
        return 0.0
    
    text_lower = text.lower()
    found = sum(1 for kw in MACRO_KEYWORDS if kw in text_lower)
    total_words = len(text.split())
    
    if total_words == 0:
        return 0.0
    
    # Normalize by word count (cap at reasonable density)
    density = min(1.0, found / max(50, total_words * 0.1))
    return density


def detect_speakers(text: str) -> bool:
    """Detect if text mentions speakers/participants."""
    speaker_patterns = [
        r'\bspeaker[s]?\b',
        r'\bpresenter[s]?\b',
        r'\bpanelist[s]?\b',
        r'\bparticipant[s]?\b',
        r'\bhosted\s+by\b',
        r'\bfeaturing\b'
    ]
    text_lower = text.lower()
    return any(re.search(pattern, text_lower, re.I) for pattern in speaker_patterns)


def detect_institutions(text: str) -> bool:
    """Detect if text mentions institutions."""
    institution_patterns = [
        r'\bfederal\s+reserve\b',
        r'\becb\b',
        r'\bcentral\s+bank\b',
        r'\bimf\b',
        r'\bworld\s+bank\b',
        r'\bgovernment\b',
        r'\bministry\b'
    ]
    text_lower = text.lower()
    return any(re.search(pattern, text_lower, re.I) for pattern in institution_patterns)
