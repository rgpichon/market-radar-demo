"""
Location parsing and normalization utilities (PRIORITY 2, Phase 3).
"""
import re
from typing import Dict, Optional, Tuple


# Common country patterns for extraction
COUNTRY_PATTERNS = [
    r'\b(United States|USA|US)\b',
    r'\b(United Kingdom|UK|Britain|Great Britain)\b',
    r'\b(Netherlands|The Netherlands|Holland)\b',
    r'\b(Germany|Deutschland)\b',
    r'\b(France)\b',
    r'\b(Italy|Italia)\b',
    r'\b(Spain|España)\b',
    r'\b(Switzerland|Schweiz|Suisse)\b',
    r'\b(Belgium|België|Belgique)\b',
    r'\b(Austria|Österreich)\b',
    r'\b(Sweden|Sverige)\b',
    r'\b(Norway|Norge)\b',
    r'\b(Denmark|Danmark)\b',
    r'\b(Finland|Suomi)\b',
    r'\b(Poland|Polska)\b',
    r'\b(Czech Republic|Czechia)\b',
    r'\b(Hungary|Magyarország)\b',
    r'\b(Japan|Nihon)\b',
    r'\b(China|People\'s Republic of China|PRC)\b',
    r'\b(Singapore)\b',
    r'\b(Hong Kong)\b',
    r'\b(Australia)\b',
    r'\b(Canada)\b',
    r'\b(Brazil|Brasil)\b',
    r'\b(Mexico|México)\b',
    r'\b(India)\b',
    r'\b(South Korea|Korea|Republic of Korea)\b',
]

# Common city patterns (major financial centers)
CITY_PATTERNS = [
    r'\b(New York|NYC|New York City)\b',
    r'\b(London)\b',
    r'\b(Amsterdam)\b',
    r'\b(Frankfurt)\b',
    r'\b(Paris)\b',
    r'\b(Milan|Milano)\b',
    r'\b(Madrid)\b',
    r'\b(Zurich|Zürich)\b',
    r'\b(Brussels|Bruxelles)\b',
    r'\b(Vienna|Wien)\b',
    r'\b(Stockholm)\b',
    r'\b(Oslo)\b',
    r'\b(Copenhagen|København)\b',
    r'\b(Warsaw|Warszawa)\b',
    r'\b(Prague|Praha)\b',
    r'\b(Budapest)\b',
    r'\b(Tokyo)\b',
    r'\b(Beijing|Peking)\b',
    r'\b(Shanghai)\b',
    r'\b(Singapore)\b',
    r'\b(Hong Kong)\b',
    r'\b(Sydney)\b',
    r'\b(Melbourne)\b',
    r'\b(Toronto)\b',
    r'\b(Montreal|Montréal)\b',
    r'\b(São Paulo|Sao Paulo)\b',
    r'\b(Mexico City|Ciudad de México)\b',
    r'\b(Mumbai|Bombay)\b',
    r'\b(Seoul)\b',
]


def normalize_country(country: str) -> str:
    """Normalize country name to standard form."""
    if not country:
        return country
    
    country_lower = country.lower()
    
    # Normalize common variations
    normalizations = {
        'usa': 'United States',
        'us': 'United States',
        'uk': 'United Kingdom',
        'britain': 'United Kingdom',
        'great britain': 'United Kingdom',
        'holland': 'Netherlands',
        'the netherlands': 'Netherlands',
        'deutschland': 'Germany',
        'espana': 'Spain',
        'españa': 'Spain',
        'schweiz': 'Switzerland',
        'suisse': 'Switzerland',
        'belgie': 'Belgium',
        'belgique': 'Belgium',
        'osterreich': 'Austria',
        'sverige': 'Sweden',
        'norge': 'Norway',
        'danmark': 'Denmark',
        'suomi': 'Finland',
        'polska': 'Poland',
        'czechia': 'Czech Republic',
        'magyarorszag': 'Hungary',
        'magyarország': 'Hungary',
        'nihon': 'Japan',
        'prc': 'China',
        'brasil': 'Brazil',
        'mexico': 'Mexico',
        'méxico': 'Mexico',
        'korea': 'South Korea',
        'republic of korea': 'South Korea',
    }
    
    for key, value in normalizations.items():
        if country_lower == key or country_lower == key.lower():
            return value
    
    # Return capitalized if not found
    return country.strip()


def normalize_city(city: str) -> str:
    """Normalize city name to standard form."""
    if not city:
        return city
    
    city_lower = city.lower()
    
    # Normalize common variations
    normalizations = {
        'nyc': 'New York',
        'new york city': 'New York',
        'bruxelles': 'Brussels',
        'wien': 'Vienna',
        'kobenhavn': 'Copenhagen',
        'københavn': 'Copenhagen',
        'warszawa': 'Warsaw',
        'praha': 'Prague',
        'peking': 'Beijing',
        'sao paulo': 'São Paulo',
        'ciudad de mexico': 'Mexico City',
        'bombay': 'Mumbai',
        'zurich': 'Zürich',
    }
    
    for key, value in normalizations.items():
        if city_lower == key or city_lower == key.lower():
            return value
    
    # Return capitalized if not found
    return city.strip()


def parse_location(location_text: str) -> Dict[str, Optional[str]]:
    """
    Parse location text to extract city and country.
    
    Args:
        location_text: Raw location string (e.g., "Amsterdam, The Netherlands" or "Leonardo Royal Hotel Amsterdam, Amsterdam, The Netherlands")
    
    Returns:
        Dict with keys: 'city', 'country'
    """
    if not location_text:
        return {'city': None, 'country': None}
    
    location_text = location_text.strip()
    
    # Try to extract country first (usually at the end)
    country = None
    for pattern in COUNTRY_PATTERNS:
        match = re.search(pattern, location_text, re.IGNORECASE)
        if match:
            country = match.group(1)
            # Remove country from text for city extraction
            location_text = location_text[:match.start()].strip()
            break
    
    # Try to extract city
    city = None
    for pattern in CITY_PATTERNS:
        match = re.search(pattern, location_text, re.IGNORECASE)
        if match:
            city = match.group(1)
            break
    
    # If no city found via patterns, try common patterns
    if not city:
        # Look for city before comma (common format: "City, Country")
        parts = location_text.split(',')
        if len(parts) > 0:
            potential_city = parts[0].strip()
            # If it looks like a city name (not too long, not all caps, etc.)
            if len(potential_city) < 50 and not potential_city.isupper():
                city = potential_city
    
    # Normalize
    if city:
        city = normalize_city(city)
    if country:
        country = normalize_country(country)
    
    return {
        'city': city,
        'country': country
    }


def normalize_location(location_text: str) -> str:
    """
    Normalize location format for consistent display.
    
    Args:
        location_text: Raw location string
    
    Returns:
        Normalized location string
    """
    if not location_text:
        return location_text
    
    # Parse and reconstruct
    parsed = parse_location(location_text)
    
    parts = []
    if parsed['city']:
        parts.append(parsed['city'])
    if parsed['country']:
        parts.append(parsed['country'])
    
    if parts:
        return ', '.join(parts)
    
    # If parsing failed, return original (cleaned)
    return location_text.strip()
