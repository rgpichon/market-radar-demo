"""
Simple topic extraction using phrase patterns and entity recognition.
No external NLP library required - uses regex and keyword patterns.
Future: Can enhance with spaCy for more sophisticated extraction.
"""
import re
from typing import List, Dict


# Important phrases to extract (2-3 word economic/financial phrases)
IMPORTANT_PHRASES = [
    # Monetary Policy
    r'\b(monetary policy|interest rate|rate decision|forward guidance|quantitative easing|qe|tapering|fomc|ecb governing council)\b',
    # Fiscal Policy
    r'\b(fiscal policy|government spending|budget deficit|fiscal stimulus|austerity|debt ceiling)\b',
    # Trade & Geopolitics
    r'\b(trade war|trade dispute|tariff|sanctions|embargo|geopolitical risk|trade agreement)\b',
    # Economic Indicators
    r'\b(inflation target|gdp growth|unemployment rate|labor market|economic outlook|recession risk)\b',
    # Market Structure
    r'\b(yield curve|credit spread|default risk|liquidity crisis|market volatility)\b',
    # Regional
    r'\b(china policy|european union|brexit|us china relations|nato)\b',
]


def extract_important_phrases(text: str) -> List[str]:
    """
    Extract important 2-3 word phrases from text using pattern matching.
    
    Args:
        text: Event title or description
        
    Returns:
        List of extracted phrases (normalized)
    """
    if not text:
        return []
    
    text_lower = text.lower()
    found_phrases = []
    
    for pattern in IMPORTANT_PHRASES:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        for match in matches:
            # Normalize phrase
            phrase = re.sub(r'\s+', ' ', match.strip())
            if phrase and phrase not in found_phrases:
                found_phrases.append(phrase)
    
    return found_phrases


def extract_named_entities(text: str) -> Dict[str, List[str]]:
    """
    Extract named entities (organizations, locations, policy terms).
    Simple pattern-based approach (no NLP library).
    
    Args:
        text: Event title or description
        
    Returns:
        Dict with keys: 'organizations', 'locations', 'policy_terms'
    """
    entities = {
        'organizations': [],
        'locations': [],
        'policy_terms': []
    }
    
    if not text:
        return entities
    
    text_lower = text.lower()
    
    # Common organization patterns
    org_patterns = [
        r'\b(federal reserve|fed|ecb|bank of england|boe|bank of japan|boj)\b',
        r'\b(imf|world bank|oecd|bis|g7|g20)\b',
        r'\b(icma|iif|afme|sifma|fia)\b',
    ]
    
    for pattern in org_patterns:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        entities['organizations'].extend([m.title() for m in matches])
    
    # Common location patterns
    location_patterns = [
        r'\b(united states|us|usa|united kingdom|uk|european union|eu)\b',
        r'\b(china|beijing|shanghai|japan|tokyo|germany|berlin|france|paris)\b',
    ]
    
    for pattern in location_patterns:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        entities['locations'].extend([m.title() for m in matches])
    
    # Deduplicate
    for key in entities:
        entities[key] = list(set(entities[key]))
    
    return entities


def extract_topics_simple(event_name: str, description: str = '', existing_tags: List[str] = None) -> List[str]:
    """
    Extract granular topics using simple phrase extraction.
    
    This is a lightweight approach that doesn't require NLP libraries.
    Future: Can enhance with spaCy for better extraction.
    
    Args:
        event_name: Event title
        description: Event description
        existing_tags: Already inferred tags from keyword matching
        
    Returns:
        List of additional granular topics
    """
    if not existing_tags:
        existing_tags = []
    
    # Combine text
    full_text = f"{event_name} {description}".strip()
    if not full_text:
        return []
    
    # Extract important phrases
    phrases = extract_important_phrases(full_text)
    
    # Extract named entities
    entities = extract_named_entities(full_text)
    
    # Convert to topic tags (normalize and format)
    topics = []
    existing_tag_set = set(t.lower() for t in existing_tags)
    
    # Add phrases as topics (capitalize properly)
    for phrase in phrases:
        # Convert "monetary policy" -> "Monetary Policy"
        topic = ' '.join(word.capitalize() for word in phrase.split())
        if topic.lower() not in existing_tag_set and topic not in topics:
            topics.append(topic)
            existing_tag_set.add(topic.lower())
    
    # Add organizations as topics (if not already covered)
    for org in entities['organizations']:
        if org.lower() not in existing_tag_set and org not in topics:
            topics.append(org)
            existing_tag_set.add(org.lower())
    
    # Add policy terms as topics (if policy_terms were extracted)
    # Note: policy_terms extraction not implemented in simple approach
    # Can be added later if needed
    
    return topics
