"""
Source lanes: categorization of sources by acquisition strategy.

Each source belongs to exactly ONE lane, which determines:
- How it's acquired (adapter type, complexity)
- What tools/processes are needed
- Whether it's currently supported
"""
from typing import Dict, Optional


# Lane definitions
LANES = {
    'html_simple': {
        'name': 'HTML Simple',
        'description': 'Simple HTML list pages with stable selectors',
        'adapter_type': 'html_list',
        'supported': True,
        'requires': []
    },
    'html_complex': {
        'name': 'HTML Complex',
        'description': 'HTML pages requiring detail fetching or complex selectors',
        'adapter_type': 'html_list',
        'supported': True,
        'requires': ['detail_fetch']
    },
    'rss': {
        'name': 'RSS/Atom Feed',
        'description': 'Structured RSS or Atom feeds',
        'adapter_type': 'rss',
        'supported': True,
        'requires': []
    },
    'ics': {
        'name': 'iCalendar Feed',
        'description': 'ICS calendar feeds',
        'adapter_type': 'ics',
        'supported': True,
        'requires': []
    },
    'json_api': {
        'name': 'JSON API',
        'description': 'Structured JSON API endpoints',
        'adapter_type': 'json_api',
        'supported': True,
        'requires': []
    },
    'js_rendered': {
        'name': 'JavaScript Rendered',
        'description': 'Single-page applications requiring browser automation',
        'adapter_type': 'playwright',
        'supported': True,
        'requires': ['playwright']
    },
    'gated': {
        'name': 'Gated Content',
        'description': 'Requires email/login/registration to access',
        'adapter_type': None,
        'supported': False,
        'requires': ['authentication']
    }
}


def infer_lane_from_source(source_cfg: Dict) -> str:
    """
    Infer the lane for a source based on its configuration.
    
    Args:
        source_cfg: Source configuration dict
    
    Returns:
        Lane ID (str)
    """
    adapter_type = source_cfg.get('adapter_type', '')
    
    # Direct mapping from adapter_type
    if adapter_type == 'rss':
        return 'rss'
    elif adapter_type == 'ics':
        return 'ics'
    elif adapter_type == 'json_api':
        return 'json_api'
    elif adapter_type == 'html_list':
        # Check if detail_fetch is enabled
        detail_fetch = source_cfg.get('detail_fetch', {})
        if isinstance(detail_fetch, dict) and detail_fetch.get('enabled', False):
            return 'html_complex'
        else:
            return 'html_simple'
    elif adapter_type == 'json_ld':
        return 'html_simple'  # JSON-LD is embedded in HTML
    elif adapter_type == 'playwright':
        return 'js_rendered'
    elif adapter_type == 'third_party_calendar':
        return 'third_party_calendar'
    
    # Default: try to infer from other signals
    # If source has acquisition_status, use that
    acquisition_status = source_cfg.get('acquisition_status', '')
    if acquisition_status == 'js_rendered':
        return 'js_rendered'
    elif acquisition_status == 'gated':
        return 'gated'
    
    # Default fallback
    return 'html_simple'


def get_lane_info(lane_id: str) -> Optional[Dict]:
    """
    Get information about a lane.
    
    Args:
        lane_id: Lane identifier
    
    Returns:
        Lane info dict or None if not found
    """
    return LANES.get(lane_id)


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


def get_all_lanes() -> Dict[str, Dict]:
    """
    Get all lane definitions.
    
    Returns:
        Dict mapping lane_id to lane info
    """
    return LANES.copy()
