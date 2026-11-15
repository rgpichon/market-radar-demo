"""
Selector adaptation and recovery.

Tries fallback selectors and learns from successful patterns.
"""
from typing import Dict, List, Optional
from bs4 import BeautifulSoup


def try_fallback_selectors(html: str, primary_selector: str, fallback_selectors: List[str]) -> Optional[List]:
    """
    Try primary selector, then fallback selectors.
    
    Args:
        html: HTML content
        primary_selector: Primary CSS selector
        fallback_selectors: List of fallback selectors to try
    
    Returns:
        List of matched elements or None
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Try primary selector
    elements = soup.select(primary_selector)
    if elements:
        return elements
    
    # Try fallback selectors
    for fallback in fallback_selectors:
        elements = soup.select(fallback)
        if elements:
            return elements
    
    return None


def suggest_selectors_based_on_pattern(firm_type: str, adapter_type: str) -> Dict[str, List[str]]:
    """
    Suggest selectors based on successful patterns from similar sources.
    
    Args:
        firm_type: Firm type (e.g., 'Think Tank', 'Association')
        adapter_type: Adapter type (e.g., 'html_list')
    
    Returns:
        Dict with suggested selectors
    """
    # Load successful selector patterns from sources.json
    # Match by firm_type and adapter_type
    # Return common selector patterns
    
    # Placeholder - would load from sources.json and analyze patterns
    # For now, return common patterns
    common_patterns = {
        'item_selector': ['.event-item', '.event', '.event-list > li', 'article.event', '.card.event'],
        'title_selector': ['h3', 'h2', '.title', '.event-title', 'a'],
        'link_selector': ['a', '.event-link', 'a.overlay-link'],
        'date_selector': ['.date', '.event-date', 'time', 'time[datetime]']
    }
    
    return common_patterns
