"""
Traceability helpers: Answer questions about source status and health.

This module provides functions to answer:
- Why is source X not active?
- Which firms are missing and why?
- Which lane dominates failures?
- Which sources are high-quality but future-poor?
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
import sys

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_sources


def why_source_not_active(source_id: str) -> Dict:
    """
    Answer: Why is source X not active?
    
    Uses source registry as the authoritative source.
    
    Args:
        source_id: Source identifier
    
    Returns:
        Dict with reason and details
    """
    from utils.source_registry import get_source_status
    
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
    
    # Source exists but is inactive
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


def which_firms_missing(bulge_brackets_file: Optional[Path] = None) -> Dict:
    """
    Answer: Which firms are missing and why?
    
    Compares bulge_brackets.json with sources.json to find firms
    that are tracked but not onboarded.
    
    Args:
        bulge_brackets_file: Path to bulge_brackets.json (default: backend/bulge_brackets.json)
    
    Returns:
        Dict with missing firms and reasons
    """
    if bulge_brackets_file is None:
        bulge_brackets_file = backend_dir / "bulge_brackets.json"
    
    if not bulge_brackets_file.exists():
        return {
            'error': 'bulge_brackets.json not found',
            'missing_firms': []
        }
    
    try:
        with open(bulge_brackets_file, 'r') as f:
            bulge_brackets = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {
            'error': 'Error reading bulge_brackets.json',
            'missing_firms': []
        }
    
    sources = get_sources(active_only=False)
    onboarded_firms = {s.get('firm_name', '').lower() for s in sources}
    
    missing = []
    for entry in bulge_brackets:
        firm_name = entry.get('firm_name', '')
        if firm_name.lower() not in onboarded_firms:
            missing.append({
                'firm_name': firm_name,
                'acquisition_status': entry.get('acquisition_status', 'unknown'),
                'lane_candidate': entry.get('lane_candidate', 'unknown'),
                'reason': entry.get('notes', 'No reason provided'),
                'last_discovered': entry.get('last_discovered', 'unknown')
            })
    
    return {
        'missing_count': len(missing),
        'missing_firms': missing
    }


def which_lane_dominates_failures(bulge_brackets_file: Optional[Path] = None) -> Dict:
    """
    Answer: Which lane dominates failures?
    
    Analyzes bulge_brackets.json to see which lanes have the most deferred/failed sources.
    
    Args:
        bulge_brackets_file: Path to bulge_brackets.json
    
    Returns:
        Dict with lane breakdown
    """
    if bulge_brackets_file is None:
        bulge_brackets_file = backend_dir / "bulge_brackets.json"
    
    if not bulge_brackets_file.exists():
        return {'error': 'bulge_brackets.json not found'}
    
    try:
        with open(bulge_brackets_file, 'r') as f:
            bulge_brackets = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {'error': 'Error reading bulge_brackets.json'}
    
    lane_status = {}
    
    for entry in bulge_brackets:
        lane = entry.get('lane_candidate', 'unknown')
        status = entry.get('acquisition_status', 'unknown')
        
        if lane not in lane_status:
            lane_status[lane] = {
                'total': 0,
                'ready': 0,
                'deferred': 0,
                'failed': 0
            }
        
        lane_status[lane]['total'] += 1
        
        if status in ['ready', 'active', 'onboarded']:
            lane_status[lane]['ready'] += 1
        elif status.startswith('deferred'):
            lane_status[lane]['deferred'] += 1
        else:
            lane_status[lane]['failed'] += 1
    
    # Find dominant failure lane
    max_deferred = 0
    dominant_lane = None
    for lane, stats in lane_status.items():
        if stats['deferred'] > max_deferred:
            max_deferred = stats['deferred']
            dominant_lane = lane
    
    return {
        'lane_breakdown': lane_status,
        'dominant_failure_lane': dominant_lane,
        'dominant_failure_count': max_deferred
    }


def which_sources_future_poor(source_stats_file: Optional[Path] = None) -> List[Dict]:
    """
    Answer: Which sources are high-quality but future-poor?
    
    Finds sources with good kept_ratio and dated_ratio but low future_count.
    
    Args:
        source_stats_file: Path to source_stats.json
    
    Returns:
        List of sources with high quality but low future events
    """
    if source_stats_file is None:
        source_stats_file = backend_dir / "source_stats.json"
    
    if not source_stats_file.exists():
        return []
    
    try:
        with open(source_stats_file, 'r') as f:
            stats = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
    
    future_poor = []
    
    for source_id, source_stat in stats.items():
        kept_ratio = source_stat.get('kept_ratio', 0.0)
        dated_ratio = source_stat.get('dated_ratio', 0.0)
        future_count = source_stat.get('future_count', 0)
        
        # High quality: kept_ratio > 0.7 and dated_ratio > 0.7
        # Future poor: future_count < 5
        if kept_ratio > 0.7 and dated_ratio > 0.7 and future_count < 5:
            future_poor.append({
                'source_id': source_id,
                'kept_ratio': kept_ratio,
                'dated_ratio': dated_ratio,
                'future_count': future_count,
                'kept_count': source_stat.get('kept_count', 0),
                'dated_count': source_stat.get('dated_count', 0)
            })
    
    # Sort by future_count ascending
    future_poor.sort(key=lambda x: x['future_count'])
    
    return future_poor


def get_acquisition_summary() -> Dict:
    """
    Get comprehensive acquisition summary.
    
    Answers all traceability questions in one call.
    
    Returns:
        Dict with all traceability information
    """
    return {
        'missing_firms': which_firms_missing(),
        'lane_failures': which_lane_dominates_failures(),
        'future_poor_sources': which_sources_future_poor()
    }
