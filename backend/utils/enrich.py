"""
Event enrichment utilities for inferring format and tags.
All rule-based, no ML.
"""

import re


# Format keywords (lowercase)
FORMAT_KEYWORDS = {
    'online': ['online', 'webinar', 'webcast', 'zoom', 'virtual', 'livestream', 'live stream', 'teams meeting'],
    'in-person': ['in-person', 'in person', 'at the ', 'auditorium', 'room ', 'campus', 'venue:', 'location:', 'address:'],
    'hybrid': ['hybrid', 'in-person and online', 'online and in-person']
}

# Tag keywords (lowercase) - easily extensible
# Phase 2: Expanded with macroeconomic secondary theme tags
TAG_KEYWORDS = {
    'Macro': ['macro', 'growth', 'inflation', 'recession', 'gdp', 'economic outlook', 'fiscal', 'monetary policy'],
    'Rates': ['rates', 'yield', 'curve', 'central bank', 'fed ', 'ecb ', 'interest rate', 'treasury', 'bonds'],
    'FX': ['fx', 'foreign exchange', 'currency', 'currencies', 'dollar', 'euro', 'yen', 'sterling', 'renminbi', 'forex'],
    'Credit': ['credit', 'spreads', 'default', 'high yield', 'investment grade', 'corporate bonds', 'leveraged'],
    'Equity': ['equities', 'equity', 'stock market', 'stocks', 'nasdaq', 's&p ', 'earnings'],
    'China': ['china', 'beijing', 'shanghai', 'chinese', 'renminbi', 'yuan', 'asia pacific'],
    'AI': ['ai', 'artificial intelligence', 'machine learning', 'ml ', 'gpt', 'llm', 'automation'],
    'Climate': ['climate', 'esg', 'sustainable', 'green', 'carbon', 'net zero', 'environmental'],
    'Geopolitics': ['geopolitics', 'geopolitical', 'sanctions', 'trade war', 'tariff', 'election', 'political'],
    'Regulation': ['regulation', 'regulatory', 'compliance', 'basel', 'mifid', 'sec ', 'dodd-frank'],
    'FinTech': ['fintech', 'blockchain', 'crypto', 'digital assets', 'payments', 'defi'],
    'Real Estate': ['real estate', 'property', 'housing', 'mortgage', 'reit'],
    'Commodities': ['commodities', 'commodity', 'oil', 'gold', 'copper', 'energy', 'metals'],
    'Insurance': ['insurance', 'reinsurance', 'underwriting', 'actuarial'],
    'Banking': ['banking', 'bank ', 'banks', 'lending', 'deposits', 'retail banking'],
    # Phase 2: Secondary macroeconomic theme tags
    'Monetary Policy': ['monetary policy', 'monetary', 'fomc', 'ecb governing council', 'rate decision', 'forward guidance', 'quantitative easing', 'qe', 'tapering'],
    'Fiscal Policy': ['fiscal policy', 'fiscal', 'government spending', 'budget', 'deficit', 'surplus', 'stimulus', 'austerity'],
    'Trade': ['trade', 'trade war', 'tariff', 'trade agreement', 'wto', 'free trade', 'protectionism', 'trade dispute'],
    'Sanctions': ['sanctions', 'sanction', 'embargo', 'trade restrictions', 'economic sanctions'],
    'Elections': ['election', 'elections', 'political', 'campaign', 'vote', 'referendum', 'ballot'],
}


def normalize_for_matching(text):
    """Normalize text for keyword matching."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', str(text).lower().strip())


def infer_format(event_name, link="", description=""):
    """
    Infer event format (Online/In-person/Hybrid/Unknown) from text.
    
    Args:
        event_name: Event title
        link: Event URL
        description: Optional additional text
    
    Returns:
        str: One of 'Online', 'In-person', 'Hybrid', 'Unknown'
    """
    # Combine all text for matching
    text_blob = normalize_for_matching(f"{event_name} {link} {description}")
    
    if not text_blob:
        return "Unknown"
    
    # Check hybrid first (most specific)
    for keyword in FORMAT_KEYWORDS['hybrid']:
        if keyword in text_blob:
            return "Hybrid"
    
    # Check both online and in-person indicators
    has_online = any(kw in text_blob for kw in FORMAT_KEYWORDS['online'])
    has_inperson = any(kw in text_blob for kw in FORMAT_KEYWORDS['in-person'])
    
    if has_online and has_inperson:
        return "Hybrid"
    elif has_online:
        return "Online"
    elif has_inperson:
        return "In-person"
    
    return "Unknown"


def infer_tags_with_confidence(event_name, link="", description="", existing_tags=None):
    """
    Infer tags with confidence scores (high/medium/low).
    
    Returns:
        List of tuples: [(tag, confidence), ...] where confidence is 'high', 'medium', or 'low'
    """
    # Combine all text for matching
    text_blob = normalize_for_matching(f"{event_name} {link} {description}")
    
    # Start with existing tags (assume high confidence if already there)
    result = []
    seen = set()
    
    if existing_tags:
        for tag in existing_tags:
            result.append((tag, 'high'))
            seen.add(tag.lower())
    
    if not text_blob:
        return result
    
    # Find matching tags with confidence scoring
    for tag, keywords in TAG_KEYWORDS.items():
        if tag.lower() in seen:
            continue
        
        matches = 0
        for keyword in keywords:
            if keyword in text_blob:
                matches += 1
        
        if matches > 0:
            # Confidence scoring:
            # High: 2+ keyword matches OR keyword appears multiple times
            # Medium: 1 keyword match
            if matches >= 2:
                confidence = 'high'
            elif matches == 1:
                # Check if keyword appears multiple times in text
                keyword_count = text_blob.count(list(keywords)[0])
                confidence = 'high' if keyword_count >= 2 else 'medium'
            else:
                confidence = 'medium'
            
            result.append((tag, confidence))
            seen.add(tag.lower())
            break  # Only add tag once
    
    return result


def infer_tags(event_name, link="", description="", existing_tags=None):
    """
    Infer tags from event text using keyword matching (backward compatible).
    Merges with existing tags, deduplicates, preserves order.
    
    Args:
        event_name: Event title
        link: Event URL  
        description: Optional additional text
        existing_tags: List of existing tags to merge with
    
    Returns:
        list: Deduplicated list of tags
    """
    tags_with_confidence = infer_tags_with_confidence(event_name, link, description, existing_tags)
    # Extract just tags for backward compatibility
    return [tag for tag, _ in tags_with_confidence]


def enrich_event(event, extra_text=""):
    """
    Enrich an event dict with format and enhanced tags.
    
    Args:
        event: Event dict with at least 'event_name', 'link', 'tags'
        extra_text: Optional extra text for matching (e.g., date_text)
    
    Returns:
        dict: Event with 'format' added and 'tags' enhanced
    """
    event_name = event.get('event_name', '')
    link = event.get('link', '')
    existing_tags = event.get('tags', [])
    
    # Infer format
    event['format'] = infer_format(event_name, link, extra_text)
    
    # Infer and merge tags (keyword-based)
    event['tags'] = infer_tags(event_name, link, extra_text, existing_tags)
    
    # Extract additional granular topics using simple NLP (PRIORITY 2, Phase 1)
    try:
        from utils.topic_extraction import extract_topics_simple
        # Combine extra_text with description if available
        description = event.get('description', '')
        full_description = f"{extra_text} {description}".strip()
        nlp_topics = extract_topics_simple(event_name, full_description, event.get('tags', []))
        if nlp_topics:
            # Merge NLP topics with existing tags
            existing_tag_set = set(t.lower() for t in event['tags'])
            for topic in nlp_topics:
                if topic.lower() not in existing_tag_set:
                    event['tags'].append(topic)
                    existing_tag_set.add(topic.lower())
    except ImportError:
        # Topic extraction not available, skip
        pass
    except Exception as e:
        # Log error but don't fail enrichment
        print(f"[enrich_event] Error in NLP topic extraction: {e}")
        pass
    
    return event
