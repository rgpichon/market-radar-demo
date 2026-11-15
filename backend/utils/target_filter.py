#!/usr/bin/env python3
"""
Canonical Newsletter Target Filtering

Single source of truth for filtering newsletter targets by priority, status, and governance.
"""
from typing import Dict, List, Optional, Tuple
from collections import Counter
from pathlib import Path
import sys
import json

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.db import get_decision, is_paused_or_cooldown


def load_newsletter_targets() -> Optional[Dict]:
    """Load newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    if not targets_path.exists():
        return None
    try:
        with open(targets_path) as f:
            return json.load(f)
    except Exception:
        return None


def filter_newsletter_targets(
    targets: List[Dict],
    priority: Optional[str] = None,
    include_statuses: Optional[List[str]] = None,
    exclude_statuses: Optional[List[str]] = None,
    enforce_governance: bool = True,
    acquisition_mode: Optional[str] = None
) -> Tuple[List[Dict], Dict]:
    """
    Canonical target filtering function.
    
    Args:
        targets: List of newsletter target dicts
        priority: Filter by priority ('p0', 'p1', 'p2', or None for all)
        include_statuses: Only include targets with these statuses (e.g., ['subscribed', 'confirmed'])
        exclude_statuses: Exclude targets with these statuses (e.g., ['rejected', 'paused'])
        enforce_governance: If True, exclude paused/cooldown/rejected targets
        acquisition_mode: Filter by acquisition_mode ('newsletter', 'events_portal', 'both', or None for all)
    
    Returns:
        Tuple of (filtered_targets, breakdown_dict)
        breakdown_dict contains:
            - total_loaded
            - after_priority_filter
            - after_status_filter
            - after_acquisition_mode_filter
            - after_governance_filter
            - blocked_count
            - blocked_reasons (dict of reason -> count)
            - status_counts (dict of status -> count)
    """
    breakdown = {
        'total_loaded': len(targets),
        'after_priority_filter': 0,
        'after_status_filter': 0,
        'after_acquisition_mode_filter': 0,
        'after_governance_filter': 0,
        'blocked_count': 0,
        'blocked_reasons': Counter(),
        'status_counts': Counter()
    }
    
    filtered = []
    blocked_reasons = Counter()
    status_counts = Counter()
    
    for target in targets:
        target_id = target.get('id')
        if not target_id:
            continue
        
        # Count status
        status = target.get('status', 'unknown')
        status_counts[status] += 1
        
        # Priority filter
        if priority:
            target_priority = target.get('priority', '')
            if target_priority != priority:
                continue
        
        breakdown['after_priority_filter'] += 1
        
        # Status include filter
        if include_statuses:
            if status not in include_statuses:
                continue
        
        # Status exclude filter
        if exclude_statuses:
            if status in exclude_statuses:
                continue
        
        breakdown['after_status_filter'] += 1
        
        # Acquisition mode filter
        if acquisition_mode:
            target_mode = target.get('acquisition_mode', 'both')
            # 'both' matches any mode, otherwise must match exactly
            if acquisition_mode != 'both' and target_mode != acquisition_mode and target_mode != 'both':
                continue
        
        breakdown['after_acquisition_mode_filter'] += 1
        
        # Governance filter
        if enforce_governance:
            # Check pause/cooldown
            is_blocked, block_reason = is_paused_or_cooldown(target_id)
            if is_blocked:
                breakdown['blocked_count'] += 1
                blocked_reasons[block_reason or 'unknown'] += 1
                continue
            
            # Check decision status (rejected is terminal)
            decision = get_decision(target_id)
            if decision:
                decision_status = decision.get('decision_status', '')
                if decision_status == 'rejected':
                    breakdown['blocked_count'] += 1
                    blocked_reasons['rejected'] += 1
                    continue
        
        breakdown['after_governance_filter'] += 1
        filtered.append(target)
    
    breakdown['blocked_reasons'] = dict(blocked_reasons)
    breakdown['status_counts'] = dict(status_counts)
    
    return filtered, breakdown
