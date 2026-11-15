"""
Per-source KPIs tracking for operational improvements.

Tracks metrics per source and enables auto-pause/promote based on thresholds.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone
from collections import defaultdict


KPI_FILE = Path(__file__).parent.parent / "source_kpis.json"


def load_kpis() -> Dict[str, Dict]:
    """Load source KPIs from file."""
    if not KPI_FILE.exists():
        return {}
    
    try:
        with open(KPI_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_kpis(kpis: Dict[str, Dict]):
    """Save source KPIs to file."""
    KPI_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(KPI_FILE, 'w') as f:
        json.dump(kpis, f, indent=2)


def update_source_kpis(source_id: str, scrape_stats: Dict, extraction_stats: Optional[Dict] = None):
    """
    Update KPIs for a source after a scrape run.
    
    Args:
        source_id: Source ID
        scrape_stats: Stats from scrape (kept_count, dated_count, etc.)
        extraction_stats: Optional extraction stats (detail_date_hit_rate, etc.)
    """
    kpis = load_kpis()
    
    if source_id not in kpis:
        kpis[source_id] = {
            'runs': [],
            'current_metrics': {},
            'auto_paused': False,
            'auto_promoted': False
        }
    
    # Extract metrics
    kept_count = scrape_stats.get('kept_count', 0)
    dated_count = scrape_stats.get('dated_count', 0)
    undated_count = scrape_stats.get('undated_count', 0)
    future_count = scrape_stats.get('future_count', 0)
    
    dated_ratio = dated_count / kept_count if kept_count > 0 else 0.0
    
    # Event likeness (from extraction stats if available)
    raw_count = extraction_stats.get('raw_count', 0) if extraction_stats else kept_count
    event_likeness_rate = 0.0
    if extraction_stats:
        # Calculate from rejection reasons
        rejected = extraction_stats.get('rejected', {})
        not_event_like = rejected.get('not_event_like', 0)
        if raw_count > 0:
            event_likeness_rate = 1.0 - (not_event_like / raw_count)
    
    # Detail date hit rate
    detail_date_hit_rate = extraction_stats.get('detail_date_hit_rate', 0.0) if extraction_stats else None
    
    # Churn rate (would need to compare with previous run - simplified for now)
    churn_rate = 0.0  # TODO: Implement by comparing event hashes between runs
    
    # Add run record
    run_record = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'kept_count': kept_count,
        'dated_count': dated_count,
        'undated_count': undated_count,
        'future_count': future_count,
        'dated_ratio': dated_ratio,
        'event_likeness_rate': event_likeness_rate,
        'detail_date_hit_rate': detail_date_hit_rate,
        'churn_rate': churn_rate
    }
    
    kpis[source_id]['runs'].append(run_record)
    
    # Keep only last 10 runs
    if len(kpis[source_id]['runs']) > 10:
        kpis[source_id]['runs'] = kpis[source_id]['runs'][-10:]
    
    # Update current metrics (average of last 3 runs)
    recent_runs = kpis[source_id]['runs'][-3:]
    if recent_runs:
        kpis[source_id]['current_metrics'] = {
            'avg_kept_count': sum(r['kept_count'] for r in recent_runs) / len(recent_runs),
            'avg_dated_ratio': sum(r['dated_ratio'] for r in recent_runs) / len(recent_runs),
            'avg_event_likeness_rate': sum(r['event_likeness_rate'] for r in recent_runs) / len(recent_runs),
            'avg_detail_date_hit_rate': sum(r['detail_date_hit_rate'] or 0 for r in recent_runs) / len([r for r in recent_runs if r['detail_date_hit_rate'] is not None]) if any(r['detail_date_hit_rate'] is not None for r in recent_runs) else None,
            'avg_future_count': sum(r['future_count'] for r in recent_runs) / len(recent_runs)
        }
    
    save_kpis(kpis)


def evaluate_auto_pause_promote(source_id: str, source_config: Dict) -> Dict:
    """
    Evaluate if source should be auto-paused or promoted based on KPIs.
    
    Returns:
        {
            'action': 'pause'|'promote'|None,
            'reason': str,
            'metrics': dict
        }
    """
    kpis = load_kpis()
    
    if source_id not in kpis:
        return {'action': None, 'reason': 'No KPI data yet', 'metrics': {}}
    
    metrics = kpis[source_id]['current_metrics']
    if not metrics:
        return {'action': None, 'reason': 'Insufficient run history', 'metrics': {}}
    
    # Thresholds
    MIN_KEPT_COUNT = 3
    MIN_DATED_RATIO = 0.7
    MIN_EVENT_LIKENESS = 0.5
    MIN_FUTURE_COUNT = 1
    
    # Auto-pause conditions (all must be true for N consecutive runs)
    if (metrics['avg_kept_count'] < MIN_KEPT_COUNT or
        metrics['avg_dated_ratio'] < MIN_DATED_RATIO or
        metrics['avg_event_likeness_rate'] < MIN_EVENT_LIKENESS or
        metrics['avg_future_count'] < MIN_FUTURE_COUNT):
        
        # Check if consistently below threshold (last 3 runs)
        recent_runs = kpis[source_id]['runs'][-3:]
        if len(recent_runs) >= 3:
            all_below = all(
                r['kept_count'] < MIN_KEPT_COUNT or
                r['dated_ratio'] < MIN_DATED_RATIO or
                r['event_likeness_rate'] < MIN_EVENT_LIKENESS or
                r['future_count'] < MIN_FUTURE_COUNT
                for r in recent_runs
            )
            
            if all_below:
                return {
                    'action': 'pause',
                    'reason': f"Below thresholds: kept={metrics['avg_kept_count']:.1f}, dated={metrics['avg_dated_ratio']:.1%}, likeness={metrics['avg_event_likeness_rate']:.1%}, future={metrics['avg_future_count']:.1f}",
                    'metrics': metrics
                }
    
    # Auto-promote conditions (exceeds thresholds consistently)
    if (metrics['avg_kept_count'] >= MIN_KEPT_COUNT * 2 and
        metrics['avg_dated_ratio'] >= MIN_DATED_RATIO and
        metrics['avg_event_likeness_rate'] >= MIN_EVENT_LIKENESS * 1.2 and
        metrics['avg_future_count'] >= MIN_FUTURE_COUNT * 2):
        
        recent_runs = kpis[source_id]['runs'][-3:]
        if len(recent_runs) >= 3:
            all_above = all(
                r['kept_count'] >= MIN_KEPT_COUNT * 2 and
                r['dated_ratio'] >= MIN_DATED_RATIO and
                r['event_likeness_rate'] >= MIN_EVENT_LIKENESS * 1.2 and
                r['future_count'] >= MIN_FUTURE_COUNT * 2
                for r in recent_runs
            )
            
            if all_above:
                return {
                    'action': 'promote',
                    'reason': f"Exceeds thresholds: kept={metrics['avg_kept_count']:.1f}, dated={metrics['avg_dated_ratio']:.1%}, likeness={metrics['avg_event_likeness_rate']:.1%}, future={metrics['avg_future_count']:.1f}",
                    'metrics': metrics
                }
    
    return {'action': None, 'reason': 'Within acceptable range', 'metrics': metrics}


def get_source_kpi_summary(source_id: str) -> Dict:
    """Get KPI summary for a source."""
    kpis = load_kpis()
    
    if source_id not in kpis:
        return {}
    
    return {
        'runs_count': len(kpis[source_id]['runs']),
        'current_metrics': kpis[source_id]['current_metrics'],
        'auto_paused': kpis[source_id].get('auto_paused', False),
        'auto_promoted': kpis[source_id].get('auto_promoted', False)
    }
