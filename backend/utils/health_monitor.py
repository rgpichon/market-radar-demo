"""
Source health monitoring with trend analysis.

Tracks historical stats and detects degradation patterns.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta


def load_health_history(source_id: str, history_file: Optional[Path] = None) -> List[Dict]:
    """
    Load health history for a source.
    
    Args:
        source_id: Source identifier
        history_file: Path to health history file
    
    Returns:
        List of historical stat dicts
    """
    if history_file is None:
        history_file = Path(__file__).parent.parent / "source_health_history.json"
    
    if not history_file.exists():
        return []
    
    try:
        with open(history_file) as f:
            all_history = json.load(f)
        return all_history.get(source_id, [])
    except Exception:
        return []


def save_health_snapshot(source_id: str, stats: Dict, history_file: Optional[Path] = None):
    """
    Save health snapshot for a source.
    
    Args:
        source_id: Source identifier
        stats: Current stats dict
        history_file: Path to health history file
    """
    if history_file is None:
        history_file = Path(__file__).parent.parent / "source_health_history.json"
    
    # Load existing history
    if history_file.exists():
        try:
            with open(history_file) as f:
                all_history = json.load(f)
        except Exception:
            all_history = {}
    else:
        all_history = {}
    
    # Add snapshot
    if source_id not in all_history:
        all_history[source_id] = []
    
    snapshot = {
        'timestamp': datetime.utcnow().isoformat(),
        'kept_ratio': stats.get('kept_ratio', 0.0),
        'dated_ratio': stats.get('dated_ratio', 0.0),
        'raw_count': stats.get('raw_count', 0),
        'future_count': stats.get('future_count', 0)
    }
    
    all_history[source_id].append(snapshot)
    
    # Keep only last 30 days of history
    cutoff = datetime.utcnow() - timedelta(days=30)
    all_history[source_id] = [
        s for s in all_history[source_id]
        if datetime.fromisoformat(s['timestamp']) > cutoff
    ]
    
    # Save
    with open(history_file, 'w') as f:
        json.dump(all_history, f, indent=2)


def detect_selector_breakage(source_id: str, current_stats: Dict, history_file: Optional[Path] = None) -> Optional[Dict]:
    """
    Detect selector breakage (sudden drop in kept_ratio or raw_count).
    
    Args:
        source_id: Source identifier
        current_stats: Current stats dict
        history_file: Path to health history file
    
    Returns:
        Dict with breakage info if detected, None otherwise
    """
    history = load_health_history(source_id, history_file)
    
    if len(history) < 3:
        return None  # Not enough history
    
    # Calculate average of last 5 snapshots
    recent = history[-5:]
    avg_kept_ratio = sum(s['kept_ratio'] for s in recent) / len(recent)
    avg_raw_count = sum(s['raw_count'] for s in recent) / len(recent)
    
    current_kept_ratio = current_stats.get('kept_ratio', 0.0)
    current_raw_count = current_stats.get('raw_count', 0)
    
    # Check for >50% drop
    kept_ratio_drop = (avg_kept_ratio - current_kept_ratio) / avg_kept_ratio if avg_kept_ratio > 0 else 0
    raw_count_drop = (avg_raw_count - current_raw_count) / avg_raw_count if avg_raw_count > 0 else 0
    
    if kept_ratio_drop > 0.5 or raw_count_drop > 0.5:
        return {
            'breakage_detected': True,
            'kept_ratio_drop': kept_ratio_drop,
            'raw_count_drop': raw_count_drop,
            'avg_kept_ratio': avg_kept_ratio,
            'current_kept_ratio': current_kept_ratio,
            'avg_raw_count': avg_raw_count,
            'current_raw_count': current_raw_count
        }
    
    return None


def detect_trend(source_id: str, history_file: Optional[Path] = None) -> Dict:
    """
    Detect trend (gradual degradation vs stable).
    
    Args:
        source_id: Source identifier
        history_file: Path to health history file
    
    Returns:
        Dict with trend analysis
    """
    history = load_health_history(source_id, history_file)
    
    if len(history) < 7:
        return {'trend': 'insufficient_data'}
    
    # Compare first half vs second half
    mid = len(history) // 2
    first_half = history[:mid]
    second_half = history[mid:]
    
    first_avg_kept = sum(s['kept_ratio'] for s in first_half) / len(first_half)
    second_avg_kept = sum(s['kept_ratio'] for s in second_half) / len(second_half)
    
    change = second_avg_kept - first_avg_kept
    
    if change < -0.1:
        return {'trend': 'degrading', 'change': change}
    elif change > 0.1:
        return {'trend': 'improving', 'change': change}
    else:
        return {'trend': 'stable', 'change': change}
