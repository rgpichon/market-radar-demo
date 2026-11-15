"""
Source degradation detection with deterministic rules.

Detects degradation patterns from time-series health snapshots.
"""
from typing import Dict, List, Optional
from datetime import datetime, timezone
import statistics


# Default thresholds (tweakable constants)
KEPT_COUNT_DROP_THRESHOLD = 0.4  # latest < 0.4 * median(last 5 non-zero)
DATED_RATIO_DROP_THRESHOLD_ABS = 0.25  # latest < median - 0.25
DATED_RATIO_DROP_THRESHOLD_MIN = 0.6  # AND latest < 0.6
FUTURE_COUNT_DROP_THRESHOLD = 0.4  # latest < 0.4 * median(last 5)
FLAT_ZERO_EVENTS_RUNS = 2  # consecutive runs with kept_count == 0
BASELINE_WINDOW = 5  # Use last N non-zero snapshots for baseline


def get_trailing_median(values: List[float], window: int = BASELINE_WINDOW) -> Optional[float]:
    """Compute median of last N non-zero values."""
    non_zero = [v for v in values if v is not None and v > 0]
    if not non_zero:
        return None
    recent = non_zero[-window:] if len(non_zero) >= window else non_zero
    return statistics.median(recent)


def detect_degradation(
    snapshots: List[Dict],
    latest: Dict,
    expected_baselines: Optional[Dict] = None
) -> Dict:
    """
    Detect degradation from health snapshots.
    
    Args:
        snapshots: List of historical snapshots (oldest first, or newest first - we'll handle)
        latest: Latest snapshot dict
        expected_baselines: Optional pre-computed baselines (for efficiency)
    
    Returns:
        {
            degraded: bool,
            degradation_class: str | None,
            evidence: str,
            recommended_playbook: str | None
        }
    """
    if not snapshots or not latest:
        return {
            'degraded': False,
            'degradation_class': None,
            'evidence': 'insufficient_data',
            'recommended_playbook': None
        }
    
    # Ensure snapshots are sorted newest-first (for easier processing)
    # If they come oldest-first, reverse
    if len(snapshots) > 1:
        first_ts = snapshots[0].get('ts_utc', '')
        last_ts = snapshots[-1].get('ts_utc', '')
        if first_ts < last_ts:
            snapshots = list(reversed(snapshots))
    
    # Extract metrics from snapshots
    kept_counts = [s.get('kept_count') for s in snapshots if s.get('kept_count') is not None]
    dated_ratios = [s.get('dated_ratio') for s in snapshots if s.get('dated_ratio') is not None]
    future_counts = [s.get('future_count') for s in snapshots if s.get('future_count') is not None]
    error_classes = [s.get('error_class') for s in snapshots if s.get('error_class')]
    
    latest_kept = latest.get('kept_count', 0) or 0
    latest_dated_ratio = latest.get('dated_ratio', 0.0) or 0.0
    latest_future = latest.get('future_count', 0) or 0
    latest_error = latest.get('error_class')
    
    # Check flat_zero_events first (simplest)
    if latest_kept == 0:
        # Check if previous run was also zero
        if len(snapshots) >= 1:
            prev = snapshots[0] if snapshots else None
            if prev and prev.get('kept_count', 0) == 0:
                return {
                    'degraded': True,
                    'degradation_class': 'flat_zero_events',
                    'evidence': f'kept_count=0 for 2+ consecutive runs',
                    'recommended_playbook': 'selector_drift'  # Most likely cause
                }
    
    # Check error-based degradation
    if latest_error:
        error_counts = {}
        for ec in error_classes[-7:]:  # Last 7 runs
            if ec:
                error_counts[ec] = error_counts.get(ec, 0) + 1
        
        # Transient network errors
        transient_errors = {'deferred_transient_network', 'timeout', '429', '503'}
        if latest_error in transient_errors or any(ec in transient_errors for ec in error_classes[-3:]):
            if error_counts.get('deferred_transient_network', 0) >= 2:
                return {
                    'degraded': True,
                    'degradation_class': 'spike_errors_transient',
                    'evidence': f'error_class={latest_error} dominates recent runs',
                    'recommended_playbook': 'rate_limited'
                }
        
        # Hard blocks
        blocked_errors = {'blocked_hard', '403', '401', 'gated_login'}
        if latest_error in blocked_errors:
            recent_blocked = sum(1 for ec in error_classes[-3:] if ec in blocked_errors)
            if recent_blocked >= 2:
                return {
                    'degraded': True,
                    'degradation_class': 'spike_errors_blocked',
                    'evidence': f'error_class={latest_error} repeated',
                    'recommended_playbook': 'hard_block'
                }
    
    # Check kept_count drop
    if kept_counts:
        baseline_kept = get_trailing_median(kept_counts)
        if baseline_kept and baseline_kept > 0:
            if latest_kept < KEPT_COUNT_DROP_THRESHOLD * baseline_kept:
                return {
                    'degraded': True,
                    'degradation_class': 'drop_kept_count',
                    'evidence': f'kept_count dropped: {latest_kept} < {KEPT_COUNT_DROP_THRESHOLD * baseline_kept:.1f} (baseline: {baseline_kept:.1f})',
                    'recommended_playbook': 'selector_drift'
                }
    
    # Check dated_ratio drop
    if dated_ratios:
        baseline_dated = get_trailing_median(dated_ratios)
        if baseline_dated is not None:
            drop_abs = baseline_dated - latest_dated_ratio
            if drop_abs >= DATED_RATIO_DROP_THRESHOLD_ABS and latest_dated_ratio < DATED_RATIO_DROP_THRESHOLD_MIN:
                return {
                    'degraded': True,
                    'degradation_class': 'drop_dated_ratio',
                    'evidence': f'dated_ratio dropped: {latest_dated_ratio:.2%} < {baseline_dated:.2%} - {DATED_RATIO_DROP_THRESHOLD_ABS:.2%} (baseline: {baseline_dated:.2%})',
                    'recommended_playbook': 'dates_on_detail'
                }
    
    # Check future_count drop
    if future_counts:
        baseline_future = get_trailing_median(future_counts)
        if baseline_future and baseline_future > 0:
            if latest_future < FUTURE_COUNT_DROP_THRESHOLD * baseline_future:
                return {
                    'degraded': True,
                    'degradation_class': 'drop_future_count',
                    'evidence': f'future_count dropped: {latest_future} < {FUTURE_COUNT_DROP_THRESHOLD * baseline_future:.1f} (baseline: {baseline_future:.1f})',
                    'recommended_playbook': 'dates_on_detail'
                }
    
    # No degradation detected
    return {
        'degraded': False,
        'degradation_class': None,
        'evidence': 'metrics within acceptable range',
        'recommended_playbook': None
    }
