"""
Scraping Lanes: Canonical definition of all supported acquisition methods.

This is the SINGLE SOURCE OF TRUTH for scraping lanes.
All other modules reference this file for lane definitions.
"""
from typing import Dict, List, Optional
from enum import Enum


class LaneReliability(Enum):
    """Reliability level for a scraping lane."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LaneMaintenanceCost(Enum):
    """Maintenance cost for a scraping lane."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Canonical lane definitions
SCRAPING_LANES = {
    'rss': {
        'name': 'RSS/Atom Feed',
        'description': 'Structured RSS 2.0 or Atom 1.0 feeds',
        'typical_institutions': [
            'Central banks',
            'Policy institutions',
            'Associations',
            'Think tanks',
            'News organizations'
        ],
        'tooling_required': ['requests', 'feedparser'],
        'reliability': LaneReliability.HIGH.value,
        'maintenance_cost': LaneMaintenanceCost.LOW.value,
        'supported': True,
        'requires_browser': False,
        'expected_quality': {
            'date_coverage': 0.90,  # Typically 90%+ have dates
            'structure_consistency': 0.95,  # Very consistent structure
            'uptime': 0.98  # Feeds are usually stable
        }
    },
    'ics': {
        'name': 'iCalendar Feed',
        'description': 'ICS calendar files or feeds',
        'typical_institutions': [
            'Universities',
            'Academic institutions',
            'Conference organizers',
            'Event management platforms'
        ],
        'tooling_required': ['requests', 'icalendar'],
        'reliability': LaneReliability.HIGH.value,
        'maintenance_cost': LaneMaintenanceCost.LOW.value,
        'supported': True,
        'requires_browser': False,
        'expected_quality': {
            'date_coverage': 1.00,  # ICS always has dates
            'structure_consistency': 0.98,  # Standard format
            'uptime': 0.95
        }
    },
    'html_simple': {
        'name': 'HTML Simple',
        'description': 'Simple HTML list pages with stable CSS selectors',
        'typical_institutions': [
            'Associations',
            'Think tanks',
            'Policy institutions',
            'Smaller organizations'
        ],
        'tooling_required': ['requests', 'beautifulsoup4'],
        'reliability': LaneReliability.MEDIUM.value,
        'maintenance_cost': LaneMaintenanceCost.MEDIUM.value,
        'supported': True,
        'requires_browser': False,
        'expected_quality': {
            'date_coverage': 0.60,  # Varies by source
            'structure_consistency': 0.70,  # Can break with site updates
            'uptime': 0.90
        }
    },
    'html_complex': {
        'name': 'HTML Complex',
        'description': 'HTML pages requiring detail fetching or complex selectors',
        'typical_institutions': [
            'Larger organizations',
            'Institutions with dynamic content',
            'Sites with pagination'
        ],
        'tooling_required': ['requests', 'beautifulsoup4'],
        'reliability': LaneReliability.MEDIUM.value,
        'maintenance_cost': LaneMaintenanceCost.HIGH.value,
        'supported': True,
        'requires_browser': False,
        'expected_quality': {
            'date_coverage': 0.70,  # Better after detail fetch
            'structure_consistency': 0.65,  # More complex = more fragile
            'uptime': 0.85
        }
    },
    'json_api': {
        'name': 'JSON API',
        'description': 'Structured JSON API endpoints',
        'typical_institutions': [
            'Modern organizations',
            'Data providers',
            'Platforms with public APIs',
            'Research institutions'
        ],
        'tooling_required': ['requests'],
        'reliability': LaneReliability.HIGH.value,
        'maintenance_cost': LaneMaintenanceCost.LOW.value,
        'supported': True,
        'requires_browser': False,
        'expected_quality': {
            'date_coverage': 0.85,  # APIs usually include dates
            'structure_consistency': 0.95,  # Very consistent
            'uptime': 0.95
        }
    },
    'js_rendered': {
        'name': 'JavaScript Rendered',
        'description': 'Single-page applications requiring browser automation',
        'typical_institutions': [
            'Bulge bracket banks',
            'Modern corporate websites',
            'React/Angular/Vue applications',
            'Heavy client-side rendering'
        ],
        'tooling_required': ['playwright', 'selenium'],
        'reliability': LaneReliability.LOW.value,
        'maintenance_cost': LaneMaintenanceCost.HIGH.value,
        'supported': False,
        'requires_browser': True,
        'defer_reason': 'Requires Playwright infrastructure',
        'expected_quality': {
            'date_coverage': 0.70,  # If implemented
            'structure_consistency': 0.60,  # JS apps change frequently
            'uptime': 0.80  # Browser automation is fragile
        }
    },
    'gated': {
        'name': 'Gated Content',
        'description': 'Requires authentication, email registration, or login',
        'typical_institutions': [
            'Premium data providers',
            'Membership organizations',
            'Exchanges (some)',
            'Private research platforms'
        ],
        'tooling_required': ['requests', 'authentication'],
        'reliability': LaneReliability.LOW.value,
        'maintenance_cost': LaneMaintenanceCost.HIGH.value,
        'supported': False,
        'requires_browser': False,
        'defer_reason': 'Requires authentication infrastructure',
        'expected_quality': {
            'date_coverage': 0.80,  # If accessible
            'structure_consistency': 0.70,
            'uptime': 0.75  # Auth can break
        }
    },
    'earnings_calendar': {
        'name': 'Earnings Calendar',
        'description': 'Quarterly earnings calls, capital markets days, investor days published via exchange calendars or earnings aggregators',
        'typical_institutions': [
            'Publicly traded banks',
            'Financial institutions',
            'Corporations with investor relations'
        ],
        'tooling_required': ['requests', 'beautifulsoup4'],
        'reliability': LaneReliability.MEDIUM.value,
        'maintenance_cost': LaneMaintenanceCost.MEDIUM.value,
        'supported': False,
        'requires_browser': False,
        'defer_reason': 'Requires earnings calendar source discovery and integration',
        'can_satisfy_bank_contract': True,
        'typical_failure_modes': [
            'calendar_not_found',
            'calendar_format_incompatible',
            'events_not_future_dated',
            'insufficient_event_types'
        ],
        'expected_quality': {
            'date_coverage': 1.00,  # Earnings calendars always have dates
            'structure_consistency': 0.85,  # Exchange calendars are standardized
            'uptime': 0.90
        }
    },
    'ir_aggregator': {
        'name': 'IR Aggregator Platform',
        'description': 'Centralized investor relations platforms used by banks (e.g., Nasdaq IR, Q4 Inc, Notified)',
        'typical_institutions': [
            'Publicly traded banks',
            'Corporations using IR platforms'
        ],
        'tooling_required': ['requests', 'api_client'],
        'reliability': LaneReliability.MEDIUM.value,
        'maintenance_cost': LaneMaintenanceCost.MEDIUM.value,
        'supported': False,
        'requires_browser': False,
        'defer_reason': 'Requires IR platform API access or structured data extraction',
        'can_satisfy_bank_contract': True,
        'typical_failure_modes': [
            'platform_requires_auth',
            'no_public_api',
            'platform_not_detected',
            'events_not_publicly_listed'
        ],
        'expected_quality': {
            'date_coverage': 0.95,  # IR platforms typically have dates
            'structure_consistency': 0.90,  # Platform APIs are consistent
            'uptime': 0.85  # Platform changes can break
        }
    },
    'third_party_calendar': {
        'name': 'Third-Party Calendar',
        'description': 'External calendars that list bank events (exchange earnings calendars, economic calendars, industry associations)',
        'typical_institutions': [
            'Banks listed on exchanges',
            'Financial institutions',
            'Events covered by industry calendars'
        ],
        'tooling_required': ['requests', 'beautifulsoup4'],
        'reliability': LaneReliability.MEDIUM.value,
        'maintenance_cost': LaneMaintenanceCost.MEDIUM.value,
        'supported': True,
        'requires_browser': False,
        'can_satisfy_bank_contract': True,
        'typical_failure_modes': [
            'no_coverage',
            'partial_coverage',
            'ambiguous_labels',
            'stale_data',
            'licensing_blocked',
            'format_incompatible'
        ],
        'expected_quality': {
            'date_coverage': 0.95,  # Third-party calendars usually have dates
            'structure_consistency': 0.75,  # Varies by source
            'uptime': 0.85
        }
    },
    'transcript_registry': {
        'name': 'Transcript Registry',
        'description': 'Earnings calls and events often appear in transcript registries, sometimes with future schedules (documentation only, not yet implemented)',
        'typical_institutions': [
            'Publicly traded banks',
            'Corporations with earnings calls'
        ],
        'tooling_required': ['requests', 'beautifulsoup4'],
        'reliability': LaneReliability.LOW.value,
        'maintenance_cost': LaneMaintenanceCost.HIGH.value,
        'supported': False,
        'requires_browser': False,
        'defer_reason': 'Documentation only - transcript registries are typically post-event, future schedules rare',
        'can_satisfy_bank_contract': False,  # Usually post-event, not future-dated
        'typical_failure_modes': [
            'transcripts_post_event_only',
            'no_future_schedules',
            'registry_not_public',
            'format_incompatible'
        ],
        'expected_quality': {
            'date_coverage': 0.80,  # If dates available
            'structure_consistency': 0.70,
            'uptime': 0.80
        }
    }
}


def get_lane_info(lane_id: str) -> Optional[Dict]:
    """
    Get information about a scraping lane.
    
    Args:
        lane_id: Lane identifier
    
    Returns:
        Lane info dict or None if not found
    """
    return SCRAPING_LANES.get(lane_id)


def is_lane_supported(lane_id: str) -> bool:
    """
    Check if a lane is currently supported.
    
    Args:
        lane_id: Lane identifier
    
    Returns:
        True if supported, False otherwise
    """
    lane_info = get_lane_info(lane_id)
    if not lane_info:
        return False
    return lane_info.get('supported', False)


def lane_requires_browser(lane_id: str) -> bool:
    """
    Check if a lane requires browser automation.
    
    Args:
        lane_id: Lane identifier
    
    Returns:
        True if requires browser, False otherwise
    """
    lane_info = get_lane_info(lane_id)
    if not lane_info:
        return False
    return lane_info.get('requires_browser', False)


def lane_expected_quality(lane_id: str) -> Optional[Dict]:
    """
    Get expected quality metrics for a lane.
    
    Args:
        lane_id: Lane identifier
    
    Returns:
        Dict with quality metrics or None
    """
    lane_info = get_lane_info(lane_id)
    if not lane_info:
        return None
    return lane_info.get('expected_quality')


def get_all_lanes() -> Dict[str, Dict]:
    """
    Get all lane definitions.
    
    Returns:
        Dict mapping lane_id to lane info
    """
    return SCRAPING_LANES.copy()


def get_supported_lanes() -> List[str]:
    """
    Get list of all supported lane IDs.
    
    Returns:
        List of lane IDs that are currently supported
    """
    return [lane_id for lane_id, info in SCRAPING_LANES.items() 
            if info.get('supported', False)]


def get_unsupported_lanes() -> List[str]:
    """
    Get list of all unsupported lane IDs with reasons.
    
    Returns:
        List of dicts with lane_id and defer_reason
    """
    return [
        {
            'lane_id': lane_id,
            'name': info.get('name'),
            'defer_reason': info.get('defer_reason', 'Not supported')
        }
        for lane_id, info in SCRAPING_LANES.items()
        if not info.get('supported', False)
    ]
