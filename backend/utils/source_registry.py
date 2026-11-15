"""
Source Registry: Control plane for source lifecycle management.

This module maintains a registry that answers:
- Why is source X not active?
- What is the acquisition status?
- What is the validation status?
- What is the next action?

The registry is the single source of truth for source state.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone
import sys

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_sources
from utils.lanes import infer_lane_from_source, is_lane_supported
from utils.scraping_strategy import identify_sector, recommended_lane_for_firm


REGISTRY_FILE = backend_dir / "source_registry.json"


def load_registry() -> Dict[str, Dict]:
    """
    Load source registry.
    
    Returns:
        Dict mapping source_id to registry entry
    """
    if not REGISTRY_FILE.exists():
        return {}
    
    try:
        with open(REGISTRY_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_registry(registry: Dict[str, Dict]):
    """Save source registry."""
    try:
        with open(REGISTRY_FILE, 'w') as f:
            json.dump(registry, f, indent=2)
    except IOError as e:
        raise Exception(f"Error saving source registry: {e}")


def build_registry_from_sources() -> Dict[str, Dict]:
    """
    Build registry from sources.json.
    
    This initializes the registry with all sources from sources.json.
    Reads directly from sources.json to get all fields including failure_class.
    """
    # Read directly from sources.json to get all fields
    sources_file = backend_dir / "sources.json"
    if sources_file.exists():
        with open(sources_file, 'r') as f:
            sources = json.load(f)
    else:
        sources = []
    
    # Load existing registry to preserve failure_class
    existing_registry = load_registry()
    registry = {}
    
    for source in sources:
        source_id = source.get('id')
        if not source_id:
            continue
        
        firm_name = source.get('firm_name', '')
        firm_type = source.get('firm_type')
        sector = identify_sector(firm_name, firm_type)
        lane = infer_lane_from_source(source)
        active = source.get('active', 1) == 1
        
        # Determine acquisition status (macro-signal terminology)
        if active:
            # Check source type for macro-signal classification
            firm_type = source.get('firm_type', '')
            macro_signal_types = ['Association', 'Think Tank', 'Central Bank', 'Research Network']
            if firm_type in macro_signal_types:
                acquisition_status = 'active_macro_signal'
            elif lane == 'third_party_calendar':
                acquisition_status = 'active_third_party'
            else:
                acquisition_status = 'active'
        else:
            acquisition_status = source.get('acquisition_status', 'inactive')
            if not acquisition_status or acquisition_status == 'active':
                # Check failure class for terminal states
                if failure_class == 'press_release_only':
                    acquisition_status = 'rejected_press_only'
                elif failure_class == 'no_events':
                    acquisition_status = 'rejected_no_events'
                elif failure_class == 'js_rendered':
                    acquisition_status = 'rejected_js_rendered'
                elif failure_class == 'gated_login':
                    acquisition_status = 'rejected_gated'
                elif failure_class in ['no_coverage', 'partial_coverage', 'stale_data', 'format_incompatible']:
                    acquisition_status = f'failed_{failure_class}'
                else:
                    acquisition_status = 'inactive'
        
        # Determine validation status
        validation_status = 'unknown'
        if active:
            validation_status = 'validated'  # Assumed if active
        else:
            comment = source.get('comment', '')
            if 'error' in comment.lower() or '404' in comment or '403' in comment:
                validation_status = 'failed'
            elif 'disabled' in comment.lower():
                validation_status = 'disabled'
            else:
                validation_status = 'not_validated'
        
        # Determine next action
        next_action = None
        if not active:
            if not is_lane_supported(lane):
                next_action = f"Lane '{lane}' not supported - defer"
            elif 'error' in (comment or '').lower():
                next_action = "Fix URL or selectors"
            else:
                next_action = "Re-validate and enable if passes quality gates"
        
        # Extract failure classification if present (from source config or existing registry)
        failure_class = source.get('failure_class')
        failure_evidence = source.get('failure_evidence', '')
        recommended_next_action = source.get('recommended_next_action')
        
        # If not in source, check existing registry first
        if not failure_class and source_id in existing_registry:
            failure_class = existing_registry[source_id].get('failure_class')
            if not failure_evidence:
                failure_evidence = existing_registry[source_id].get('failure_evidence', '')
            if not recommended_next_action:
                recommended_next_action = existing_registry[source_id].get('recommended_next_action')
        
        # If inactive and no failure_class, try to infer from comment
        if not active and not failure_class:
            # First check existing registry
            if source_id in registry:
                failure_class = registry[source_id].get('failure_class')
                if not failure_evidence:
                    failure_evidence = registry[source_id].get('failure_evidence', '')
                if not recommended_next_action:
                    recommended_next_action = registry[source_id].get('recommended_next_action')
            
            # If still no failure_class, infer from comment
            if not failure_class:
                comment_lower = (source.get('comment', '') or '').lower()
                if 'js' in comment_lower or 'playwright' in comment_lower:
                    failure_class = 'js_rendered'
                    recommended_next_action = 'playwright'
                elif '403' in comment_lower or 'forbidden' in comment_lower or 'blocked' in comment_lower:
                    failure_class = 'blocked'
                    recommended_next_action = 'third_party_proxy'
                elif 'press release' in comment_lower or 'article' in comment_lower:
                    failure_class = 'press_release_only'
                    recommended_next_action = 'rss_search'
                elif '404' in comment_lower or 'not found' in comment_lower:
                    failure_class = 'no_events'
                    recommended_next_action = 'abandon'
                elif 'login' in comment_lower or 'auth' in comment_lower or 'gated' in comment_lower:
                    failure_class = 'gated_login'
                    recommended_next_action = 'rss_search'
        
        # Use recommended_next_action from source or inferred
        if not recommended_next_action:
            recommended_next_action = next_action
        
        # Ensure recommended_next_action is set based on failure_class
        if not recommended_next_action and failure_class:
            # Map failure classes to recommended actions
            action_map = {
                'press_release_only': 'abandon',
                'no_events': 'abandon',
                'js_rendered': 'deferred_requires_manual_work',
                'gated_login': 'deferred_requires_manual_work',
                'no_coverage': 'try_alternative_calendar',
                'partial_coverage': 'combine_sources',
                'stale_data': 'find_fresher_source',
                'format_incompatible': 'refine_selectors',
                'blocked': 'find_public_source'
            }
            recommended_next_action = action_map.get(failure_class, 'abandon')
        
        registry[source_id] = {
            'source_id': source_id,
            'firm_name': firm_name,
            'sector': sector,
            'lane': lane,
            'acquisition_status': acquisition_status,
            'validation_status': validation_status,
            'active': active,
            'last_checked': source.get('discovery_timestamp') or datetime.now(timezone.utc).isoformat(),
            'failure_reason': source.get('comment', '') if not active else None,
            'failure_class': failure_class,
            'failure_evidence': failure_evidence,
            'recommended_next_action': recommended_next_action,
            'next_action': recommended_next_action,  # Keep for backward compatibility
            'url': source.get('url', '')
        }
    
    return registry


def sync_registry():
    """
    Sync registry with sources.json.
    
    Ensures registry is up-to-date with sources.json.
    """
    registry = load_registry()
    new_registry = build_registry_from_sources()
    
    # Merge: keep existing entries, update with new
    for source_id, entry in new_registry.items():
        if source_id in registry:
            # Update existing
            existing = registry[source_id]
            existing.update(entry)
            existing['last_synced'] = datetime.now(timezone.utc).isoformat()
        else:
            # New entry
            entry['last_synced'] = datetime.now(timezone.utc).isoformat()
            registry[source_id] = entry
    
    save_registry(registry)
    return registry


def get_source_status(source_id: str) -> Optional[Dict]:
    """
    Get complete status for a source.
    
    Args:
        source_id: Source identifier
    
    Returns:
        Registry entry or None if not found
    """
    registry = load_registry()
    
    # Sync if registry is empty or source not found
    if not registry or source_id not in registry:
        registry = sync_registry()
    
    return registry.get(source_id)


def why_source_not_active(source_id: str) -> Dict:
    """
    Answer: Why is source X not active?
    
    Args:
        source_id: Source identifier
    
    Returns:
        Dict with reason and details
    """
    status = get_source_status(source_id)
    
    if not status:
        return {
            'found': False,
            'reason': 'Source not found in registry'
        }
    
    if status.get('active'):
        return {
            'found': True,
            'active': True,
            'reason': 'Source is active'
        }
    
    # Source is inactive
    return {
        'found': True,
        'active': False,
        'acquisition_status': status.get('acquisition_status'),
        'validation_status': status.get('validation_status'),
        'lane': status.get('lane'),
        'failure_reason': status.get('failure_reason'),
        'next_action': status.get('next_action'),
        'reason': status.get('failure_reason') or f"Status: {status.get('acquisition_status')}"
    }


def get_all_inactive_sources() -> List[Dict]:
    """
    Get all inactive sources with reasons.
    
    Returns:
        List of inactive source entries
    """
    registry = sync_registry()
    
    inactive = []
    for source_id, entry in registry.items():
        if not entry.get('active'):
            inactive.append(entry)
    
    return sorted(inactive, key=lambda x: x.get('firm_name', ''))


def get_sources_by_lane(lane: str) -> List[Dict]:
    """
    Get all sources in a specific lane.
    
    Args:
        lane: Lane identifier
    
    Returns:
        List of source entries in that lane
    """
    registry = sync_registry()
    
    sources = []
    for source_id, entry in registry.items():
        if entry.get('lane') == lane:
            sources.append(entry)
    
    return sorted(sources, key=lambda x: x.get('firm_name', ''))
