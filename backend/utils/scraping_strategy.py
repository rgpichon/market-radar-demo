"""
Scraping Strategy: Sector-aware lane selection and tooling decisions.

Maps: sector → institution type → scraping lane → tool

This makes tool choice explicit and readable.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.scraping_lanes import get_lane_info, is_lane_supported


# Sector definitions
SECTORS = {
    'central_bank': {
        'name': 'Central Banks / Policy Forums (TIER A - CORE MACRO SIGNAL HOSTS)',
        'institutions': [
            'ECB', 'European Central Bank', 'Federal Reserve', 'Fed',
            'BIS', 'Bank for International Settlements', 'Bank of England', 'BoE',
            'Bank of Japan', 'BoJ', 'SNB', 'Swiss National Bank',
            'RBA', 'Reserve Bank of Australia', 'RBNZ', 'Reserve Bank of New Zealand'
        ],
        'preferred_lanes': ['rss', 'ics', 'json_api', 'html_simple'],
        'typical_tooling': ['requests', 'feedparser', 'icalendar'],
        'acquisition_priority': 'high',  # Tier A - Core macro signal hosts
        'requires_participant_extraction': True  # Must extract participants
    },
    'association': {
        'name': 'Market Associations (TIER A - CORE MACRO SIGNAL HOSTS)',
        'institutions': [
            'ICMA', 'International Capital Market Association',
            'IIF', 'Institute of International Finance',
            'AFME', 'Association for Financial Markets in Europe',
            'SIFMA', 'ISDA', 'FIA', 'Futures Industry Association',
            'CFA Institute', 'CFA'
        ],
        'preferred_lanes': ['rss', 'html_simple', 'html_complex'],
        'typical_tooling': ['requests', 'feedparser', 'beautifulsoup4'],
        'acquisition_priority': 'high',  # Tier A - Core macro signal hosts
        'requires_participant_extraction': True  # Must extract participants
    },
    'think_tank': {
        'name': 'Think Tanks (TIER A - CORE MACRO SIGNAL HOSTS)',
        'institutions': [
            'Brookings Institution', 'Brookings', 'CSIS',
            'Center for Strategic and International Studies',
            'Bruegel', 'Peterson Institute', 'PIIE',
            'Council on Foreign Relations', 'CFR',
            'Chatham House', 'RAND', 'Heritage Foundation', 'Cato Institute'
        ],
        'preferred_lanes': ['rss', 'html_simple', 'html_complex'],
        'typical_tooling': ['requests', 'feedparser', 'beautifulsoup4'],
        'acquisition_priority': 'high',  # Tier A - Core macro signal hosts
        'requires_participant_extraction': True  # Must extract participants
    },
    'academic': {
        'name': 'Academic Institutions (TIER B - MEDIUM PRIORITY)',
        'institutions': [
            'LSE', 'London School of Economics',
            'CEPR', 'Centre for Economic Policy Research',
            'NBER', 'National Bureau of Economic Research',
            'AEA', 'American Economic Association',
            'University', 'College', 'School of Economics', 'Department of Economics'
        ],
        'preferred_lanes': ['ics', 'html_simple', 'rss'],
        'typical_tooling': ['requests', 'icalendar', 'beautifulsoup4'],
        'acquisition_priority': 'medium',  # Tier B
        'requires_participant_extraction': True  # Should extract participants
    },
    'bulge_bracket': {
        'name': 'Bulge Bracket Banks (DEPRECATED FOR DIRECT ACQUISITION)',
        'institutions': [
            'Goldman Sachs', 'JPMorgan', 'Morgan Stanley', 'Citigroup',
            'Bank of America', 'Barclays', 'Deutsche Bank', 'UBS',
            'BNP Paribas', 'Société Générale', 'Credit Suisse'
        ],
        'preferred_lanes': [],  # Banks are NOT primary sources
        'fallback_lanes': [],  # Do not acquire from bank websites
        'typical_tooling': [],
        'note': 'DEPRECATED: Bank websites are not primary sources. Banks are participants, not publishers. Acquire from macro-signal hosts (associations, think tanks) and infer bank participation via entity matching.',
        'acquisition_priority': 'none',  # Do not acquire directly
        'participation_only': True  # Only detect as participants
    },
    'exchange': {
        'name': 'Exchanges',
        'institutions': [
            'NYSE', 'NASDAQ', 'CME', 'ICE', 'LSE', 'Euronext',
            'Tokyo Stock Exchange', 'Hong Kong Exchange'
        ],
        'preferred_lanes': ['json_api', 'gated', 'html_complex'],
        'typical_tooling': ['requests', 'authentication'],
        'note': 'Many require authentication or have complex structures'
    },
    'regulator': {
        'name': 'Regulators',
        'institutions': [
            'SEC', 'Securities and Exchange Commission',
            'FCA', 'Financial Conduct Authority',
            'ESMA', 'European Securities and Markets Authority',
            'CFTC', 'Commodity Futures Trading Commission'
        ],
        'preferred_lanes': ['html_simple', 'rss', 'json_api'],
        'typical_tooling': ['requests', 'beautifulsoup4', 'feedparser']
    },
    'data_provider': {
        'name': 'Data Providers',
        'institutions': [
            'Moody\'s', 'S&P', 'Bloomberg', 'Refinitiv', 'FactSet'
        ],
        'preferred_lanes': ['gated', 'js_rendered', 'json_api'],
        'typical_tooling': ['authentication', 'playwright'],
        'note': 'Most require authentication or are JS-rendered'
    }
}


def normalize_firm_name(firm_name: str) -> str:
    """Normalize firm name for matching."""
    return re.sub(r'\s+', ' ', str(firm_name).lower().strip())


def identify_sector(firm_name: str, firm_type: Optional[str] = None) -> Optional[str]:
    """
    Identify sector for a firm.
    
    Args:
        firm_name: Firm name
        firm_type: Optional firm type hint
    
    Returns:
        Sector ID or None if not identified
    """
    firm_normalized = normalize_firm_name(firm_name)
    
    # Check firm_type first if provided
    if firm_type:
        firm_type_lower = normalize_firm_name(firm_type)
        if 'central bank' in firm_type_lower or 'bank' in firm_type_lower:
            # Could be central bank or bulge bracket
            if any(bb in firm_normalized for bb in ['goldman', 'jpmorgan', 'morgan stanley', 
                                                     'citi', 'bank of america', 'barclays',
                                                     'deutsche', 'ubs', 'bnp', 'société']):
                return 'bulge_bracket'
            return 'central_bank'
        elif 'association' in firm_type_lower:
            return 'association'
        elif 'think tank' in firm_type_lower or 'research' in firm_type_lower:
            return 'think_tank'
        elif 'academic' in firm_type_lower or 'university' in firm_type_lower:
            return 'academic'
        elif 'regulator' in firm_type_lower:
            return 'regulator'
        elif 'data provider' in firm_type_lower:
            return 'data_provider'
        elif 'exchange' in firm_type_lower:
            return 'exchange'
    
    # Match by firm name
    for sector_id, sector_info in SECTORS.items():
        for institution in sector_info['institutions']:
            if normalize_firm_name(institution) in firm_normalized:
                return sector_id
    
    return None


def recommended_lane_for_firm(firm_name: str, sector: Optional[str] = None, 
                             firm_type: Optional[str] = None) -> Tuple[Optional[str], str]:
    """
    Recommend scraping lane for a firm.
    
    Args:
        firm_name: Firm name
        sector: Optional sector ID
        firm_type: Optional firm type
    
    Returns:
        (recommended_lane, confidence) where confidence is 'high', 'medium', or 'low'
    """
    # Identify sector if not provided
    if not sector:
        sector = identify_sector(firm_name, firm_type)
    
    if not sector:
        # Unknown sector, default to html_simple
        return 'html_simple', 'low'
    
    sector_info = SECTORS.get(sector)
    if not sector_info:
        return 'html_simple', 'low'
    
    # Get preferred lanes
    preferred_lanes = sector_info.get('preferred_lanes', [])
    
    # Return first supported lane
    for lane in preferred_lanes:
        if is_lane_supported(lane):
            return lane, 'high'
    
    # If no supported preferred lanes, check fallback
    fallback_lanes = sector_info.get('fallback_lanes', [])
    for lane in fallback_lanes:
        if is_lane_supported(lane):
            return lane, 'medium'
    
    # If still nothing, return first preferred (even if unsupported)
    if preferred_lanes:
        return preferred_lanes[0], 'low'
    
    # Last resort
    return 'html_simple', 'low'


def fallback_lanes(lane: str) -> List[str]:
    """
    Get fallback lanes if primary lane fails.
    
    Args:
        lane: Primary lane ID
    
    Returns:
        List of fallback lane IDs in order of preference
    """
    lane_info = get_lane_info(lane)
    if not lane_info:
        return ['html_simple']  # Default fallback
    
    # Sector-agnostic fallbacks
    fallback_map = {
        'rss': ['html_simple', 'html_complex'],
        'ics': ['html_simple', 'rss'],
        'html_simple': ['html_complex', 'rss'],
        'html_complex': ['html_simple'],
        'json_api': ['html_simple', 'rss'],
        'js_rendered': ['rss', 'html_simple'],  # Try feeds first
        'gated': ['rss', 'html_simple']  # Try public feeds
    }
    
    return fallback_map.get(lane, ['html_simple'])


def requires_playwright(firm_name: str, sector: Optional[str] = None) -> bool:
    """
    Check if a firm requires Playwright (browser automation).
    
    Args:
        firm_name: Firm name
        sector: Optional sector ID
    
    Returns:
        True if requires Playwright, False otherwise
    """
    lane, _ = recommended_lane_for_firm(firm_name, sector)
    
    if not lane:
        return False
    
    lane_info = get_lane_info(lane)
    if not lane_info:
        return False
    
    return lane_info.get('requires_browser', False)


def get_tooling_for_lane(lane: str) -> List[str]:
    """
    Get required tooling for a lane.
    
    Args:
        lane: Lane ID
    
    Returns:
        List of required tools/packages
    """
    lane_info = get_lane_info(lane)
    if not lane_info:
        return []
    
    return lane_info.get('tooling_required', [])


def get_sector_info(sector_id: str) -> Optional[Dict]:
    """
    Get information about a sector.
    
    Args:
        sector_id: Sector identifier
    
    Returns:
        Sector info dict or None
    """
    return SECTORS.get(sector_id)


def get_all_sectors() -> Dict[str, Dict]:
    """
    Get all sector definitions.
    
    Returns:
        Dict mapping sector_id to sector info
    """
    return SECTORS.copy()
