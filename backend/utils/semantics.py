"""
Semantic inference for events: event_type, signal_level, market_scope.
All rule-based, deterministic, testable.
"""

import re
import json
from typing import Dict, List, Optional, Set


# Event type inference rules
POLICY_FIRMS = {
    'ECB', 'European Central Bank', 'Federal Reserve', 'Fed', 'BIS', 'Bank for International Settlements',
    'BIS IFC', 'Bank of England', 'BoE', 'Bank of Japan', 'BoJ', 'SNB', 'Swiss National Bank',
    'RBA', 'Reserve Bank of Australia', 'RBNZ', 'Reserve Bank of New Zealand',
    'IMF', 'International Monetary Fund', 'World Bank', 'OECD'
}

MARKET_FIRMS = {
    'ICMA', 'International Capital Market Association', 'IIF', 'Institute of International Finance',
    'AFME', 'Association for Financial Markets in Europe', 'SIFMA', 'ISDA',
    'FIA', 'Futures Industry Association', 'CFA Institute', 'CFA'
}

RESEARCH_FIRMS = {
    'Brookings Institution', 'Brookings', 'CSIS', 'Center for Strategic and International Studies',
    'Bruegel', 'Peterson Institute', 'PIIE', 'Council on Foreign Relations', 'CFR',
    'Chatham House', 'RAND', 'Heritage Foundation', 'Cato Institute'
}

ACADEMIC_FIRMS = {
    'LSE', 'London School of Economics', 'CEPR', 'Centre for Economic Policy Research',
    'NBER', 'National Bureau of Economic Research', 'AEA', 'American Economic Association',
    'University', 'College', 'School of Economics', 'Department of Economics'
}

# Signal level keywords (for named speakers, important events)
HIGH_SIGNAL_KEYWORDS = [
    'governor', 'chair', 'president', 'chief economist', 'deputy governor',
    'policy rate', 'monetary policy decision', 'fomc', 'ecb governing council',
    'press conference', 'speech by', 'remarks by', 'testimony'
]

MEDIUM_SIGNAL_KEYWORDS = [
    'conference', 'summit', 'forum', 'symposium', 'workshop', 'webinar',
    'annual meeting', 'seminar series'
]

# Market scope mapping (from tags to normalized market_scope)
TAG_TO_MARKET_SCOPE = {
    'Rates': 'rates',
    'FX': 'fx',
    'Credit': 'credit',
    'Equity': 'equities',
    'Equities': 'equities',
    'Macro': 'macro',
    'Geopolitics': 'geopolitics',
    'China': 'geopolitics',  # China events often geopolitical
    'Regulation': 'macro',  # Regulation is macro-level
    'FinTech': 'equities',  # FinTech often equity-focused
    'Real Estate': 'macro',
    'Commodities': 'macro',
    'Insurance': 'credit',
    'Banking': 'macro'
}

# Participant role keywords (PHASE 4)
ROLE_KEYWORDS = {
    'central_banker': ['fed official', 'ecb member', 'central banker', 'governor', 'chair', 'deputy governor', 'fomc', 'ecb governing council'],
    'policymaker': ['policymaker', 'policy maker', 'government official', 'minister', 'secretary', 'treasury secretary'],
    'academic': ['professor', 'academic', 'researcher', 'university', 'phd', 'scholar', 'lecturer'],
    'journalist': ['journalist', 'reporter', 'correspondent', 'editor', 'media', 'news anchor'],
    'economist': ['chief economist', 'economist', 'economic analyst', 'macro economist'],
    'investor': ['investor', 'fund manager', 'portfolio manager', 'asset manager', 'investment manager'],
    'banker': ['banker', 'bank executive', 'cfo', 'ceo', 'managing director', 'head of']
}

# Affiliation keywords (PHASE 4)
AFFILIATION_KEYWORDS = {
    'central_bank': ['federal reserve', 'ecb', 'central bank', 'boe', 'boj', 'bank of england', 'bank of japan', 'snb', 'rba'],
    'government': ['government', 'ministry', 'department', 'agency', 'treasury', 'finance ministry'],
    'academic': ['university', 'college', 'institute', 'school', 'research center'],
    'media': ['news', 'media', 'journal', 'publication', 'press', 'newsroom'],
    'financial_institution': ['bank', 'investment', 'asset management', 'investment bank', 'commercial bank'],
    'think_tank': ['think tank', 'institute', 'foundation', 'council', 'center', 'research institute']
}


def normalize_for_matching(text):
    """Normalize text for case-insensitive matching."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', str(text).lower().strip())


def infer_event_type(firm_name: str, firm_type: Optional[str] = None, event_name: str = "") -> str:
    """
    Infer event_type: policy, market, research, academic, other.
    
    Rules:
    - Central banks, BIS, ECB, Fed, BIS IFC → policy
    - Associations (ICMA, IIF, AFME) → market
    - Think tanks (Brookings, CFR, Bruegel, CSIS) → research
    - Universities, CEPR seminars, LSE talks → academic
    - Default → other
    """
    firm_normalized = normalize_for_matching(firm_name)
    event_normalized = normalize_for_matching(event_name)
    
    # Check policy firms
    for policy_firm in POLICY_FIRMS:
        if normalize_for_matching(policy_firm) in firm_normalized:
            return 'policy'
    
    # Check market firms
    for market_firm in MARKET_FIRMS:
        if normalize_for_matching(market_firm) in firm_normalized:
            return 'market'
    
    # Check research firms
    for research_firm in RESEARCH_FIRMS:
        if normalize_for_matching(research_firm) in firm_normalized:
            return 'research'
    
    # Check academic firms
    for academic_firm in ACADEMIC_FIRMS:
        if normalize_for_matching(academic_firm) in firm_normalized:
            return 'academic'
    
    # Check firm_type if available
    if firm_type:
        firm_type_lower = normalize_for_matching(firm_type)
        if 'central bank' in firm_type_lower or 'bank' in firm_type_lower:
            return 'policy'
        elif 'association' in firm_type_lower or 'market' in firm_type_lower:
            return 'market'
        elif 'think tank' in firm_type_lower or 'research' in firm_type_lower:
            return 'research'
        elif 'academic' in firm_type_lower or 'university' in firm_type_lower:
            return 'academic'
    
    # Default
    return 'other'


def infer_signal_level(
    event_type: str,
    firm_name: str,
    event_name: str = "",
    description: str = ""
) -> str:
    """
    Infer signal_level: low, medium, high.
    
    Rules:
    - Policy institutions + named speakers → high
    - Market associations, conferences → medium
    - Academic seminars, generic talks → low
    """
    text_blob = normalize_for_matching(f"{event_name} {description}")
    
    # High signal: policy events with named speakers or important policy events
    if event_type == 'policy':
        # Check for named speakers or important policy keywords
        if any(kw in text_blob for kw in HIGH_SIGNAL_KEYWORDS):
            return 'high'
        # Policy events are generally high signal even without named speakers
        return 'high'
    
    # Medium signal: market associations, conferences
    if event_type == 'market':
        return 'medium'
    
    # Check for conference/summit keywords (medium signal)
    if any(kw in text_blob for kw in MEDIUM_SIGNAL_KEYWORDS):
        return 'medium'
    
    # Low signal: academic, research (unless it's a major conference)
    if event_type in ['academic', 'research']:
        # Major conferences might be medium
        if any(kw in text_blob for kw in ['conference', 'summit', 'forum']):
            return 'medium'
        return 'low'
    
    # Default: medium for other types
    return 'medium'


def calculate_signal_score(
    event_type: str,
    signal_level: str,
    firm_name: str,
    event_name: str = '',
    description: str = '',
    date_time: Optional[str] = None,
    format: str = 'Unknown',
    participant_roles: Optional[Dict] = None,
    intel_type: str = 'event'
) -> int:
    """
    Calculate signal score (0-100) based on multiple factors (PHASE 6).
    
    Returns:
        int: Signal score 0-100
    """
    score = 50  # Base score
    
    # Source authority (event_type already inferred)
    if event_type == 'policy':
        score += 20  # Central banks, policy institutions
    elif event_type == 'market':
        score += 10  # Market associations
    elif event_type in ['research', 'academic']:
        # Major think tanks get boost
        major_think_tanks = ['brookings', 'csis', 'cfr', 'bruegel', 'peterson']
        if any(tank in firm_name.lower() for tank in major_think_tanks):
            score += 15
        else:
            score += 5
    
    # Signal level boost (semantic classification)
    if signal_level == 'high':
        score += 15
    elif signal_level == 'medium':
        score += 5
    # 'low' adds nothing
    
    # Time sensitivity
    if date_time:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(date_time.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            if dt >= now:
                score += 10  # Upcoming events
        except:
            pass
    
    # Format boost
    if format == 'In-person':
        score += 10
    elif format == 'Hybrid':
        score += 5
    # Online/Unknown adds nothing
    
    # Participant roles boost
    if participant_roles:
        roles = participant_roles.get('roles', [])
        if 'central_banker' in roles:
            score += 10
        if 'policymaker' in roles:
            score += 5
        if 'academic' in roles and 'central_banker' in roles:
            score += 5  # Academic + central banker combo
    
    # Intel type boost
    if intel_type == 'outlook':
        score += 5  # Forward-looking perspectives
    elif intel_type == 'signal':
        score += 10  # Policy announcements
    elif intel_type == 'debate':
        score += 3  # Debates are valuable but less direct than signals
    
    # Theme relevance (if macro-focused)
    text_blob = normalize_for_matching(f"{event_name} {description}")
    core_macro_keywords = ['monetary policy', 'fiscal policy', 'interest rate', 'inflation', 'growth']
    if any(kw in text_blob for kw in core_macro_keywords):
        score += 5
    
    # Normalize to 0-100
    return max(0, min(100, score))


def infer_intel_type_for_scrape(event_name: str, description: str = '', date_time: Optional[str] = None) -> str:
    """
    Wrapper for intel_type classification for web scraping (PHASE 1).
    
    This is a convenience wrapper around classify_intel_type() for use in pipeline.
    Returns just the intel_type string (not the tuple).
    
    Args:
        event_name: Event title
        description: Optional description
        date_time: Optional date/time string
    
    Returns:
        str: intel_type ('event', 'briefing', 'outlook', 'webinar', 'note', 'invite', 'debate', 'signal')
    """
    import sys
    from pathlib import Path
    backend_dir = Path(__file__).parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from utils.intel_classifier import classify_intel_type
    
    intel_type, _ = classify_intel_type(
        event_name=event_name,
        description=description,
        date_time=date_time,
        link=''
    )
    return intel_type


def infer_participant_roles(event_name: str, description: str = '', firm_name: str = '') -> Dict:
    """
    Infer participant roles and affiliations from event text (PHASE 4).
    
    Returns:
        {"roles": ["central_banker", "academic"], "affiliations": ["central_bank", "academic"]}
    """
    text_blob = normalize_for_matching(f"{event_name} {description} {firm_name}")
    
    roles = []
    affiliations = []
    
    # Detect roles
    for role, keywords in ROLE_KEYWORDS.items():
        if any(kw in text_blob for kw in keywords):
            roles.append(role)
    
    # Detect affiliations (from source or description)
    for aff, keywords in AFFILIATION_KEYWORDS.items():
        if any(kw in text_blob for kw in keywords):
            affiliations.append(aff)
    
    return {"roles": sorted(list(set(roles))), "affiliations": sorted(list(set(affiliations)))}


def infer_market_scope(tags: List[str], event_name: str = "", description: str = "") -> List[str]:
    """
    Infer market_scope from tags and event text.
    Returns normalized list: rates, fx, credit, equities, macro, geopolitics.
    
    Reuses tag inference logic but normalizes into dedicated semantic field.
    """
    scope_set: Set[str] = set()
    text_blob = normalize_for_matching(f"{event_name} {description}")
    
    # Map tags to market_scope
    for tag in tags:
        if tag in TAG_TO_MARKET_SCOPE:
            scope_set.add(TAG_TO_MARKET_SCOPE[tag])
    
    # Direct keyword matching in text (if tags don't cover it)
    if 'rates' not in scope_set and any(kw in text_blob for kw in ['rate', 'yield', 'treasury', 'bond', 'central bank']):
        scope_set.add('rates')
    
    if 'fx' not in scope_set and any(kw in text_blob for kw in ['fx', 'currency', 'foreign exchange', 'forex']):
        scope_set.add('fx')
    
    if 'credit' not in scope_set and any(kw in text_blob for kw in ['credit', 'spread', 'default', 'high yield']):
        scope_set.add('credit')
    
    if 'equities' not in scope_set and any(kw in text_blob for kw in ['equity', 'stock', 'equities', 's&p', 'nasdaq']):
        scope_set.add('equities')
    
    if 'geopolitics' not in scope_set and any(kw in text_blob for kw in ['geopolitical', 'sanctions', 'trade war', 'election']):
        scope_set.add('geopolitics')
    
    # If nothing matched, default to macro
    if not scope_set:
        scope_set.add('macro')
    
    # Return sorted list for consistency
    return sorted(list(scope_set))


def enrich_event_semantics(
    event: Dict,
    firm_type: Optional[str] = None
) -> Dict:
    """
    Enrich an event dict with semantic fields:
    - event_type
    - signal_level
    - market_scope_json (as JSON string for database storage)
    
    Args:
        event: Event dict with at least 'firm_name', 'event_name', 'tags'
        firm_type: Optional firm_type from source config
    
    Returns:
        dict: Event with semantic fields added
    """
    firm_name = event.get('firm_name', '')
    event_name = event.get('event_name', '')
    description = event.get('description', '')
    tags = event.get('tags', [])
    if not isinstance(tags, list):
        tags = []
    
    # Infer event_type
    event_type = infer_event_type(firm_name, firm_type, event_name)
    event['event_type'] = event_type
    
    # Infer signal_level
    signal_level = infer_signal_level(event_type, firm_name, event_name, description)
    event['signal_level'] = signal_level
    
    # Infer market_scope
    market_scope = infer_market_scope(tags, event_name, description)
    event['market_scope'] = market_scope
    event['market_scope_json'] = json.dumps(market_scope)  # For database storage
    
    # Infer intel_type (Phase 1: support 'debate' and 'signal' types)
    from utils.intel_classifier import classify_intel_type
    date_time = event.get('date_time')
    link = event.get('link', '')
    intel_type, confidence_score = classify_intel_type(
        event_name=event_name,
        description=description,
        date_time=date_time,
        link=link
    )
    event['intel_type'] = intel_type
    event['confidence_score'] = confidence_score
    
    # Infer participant roles (Phase 4)
    participant_roles = infer_participant_roles(event_name, description, firm_name)
    event['participant_roles_json'] = json.dumps(participant_roles) if participant_roles else None
    
    # Calculate signal score (Phase 6)
    signal_score = calculate_signal_score(
        event_type=event.get('event_type', 'other'),
        signal_level=event.get('signal_level', 'medium'),
        firm_name=firm_name,
        event_name=event_name,
        description=description,
        date_time=event.get('date_time'),
        format=event.get('format', 'Unknown'),
        participant_roles=participant_roles if participant_roles.get('roles') or participant_roles.get('affiliations') else None,
        intel_type=intel_type
    )
    event['signal_score'] = signal_score
    
    return event
