#!/usr/bin/env python3
"""
Newsletter Subscription Decision Engine

Deterministic decision-making for newsletter subscription based on quality,
feasibility, and governance rules.
"""
import json
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timezone, timedelta
from pathlib import Path


def check_governance_block(newsletter_id: str) -> Tuple[bool, Optional[str]]:
    """
    Centralized governance check (MANDATORY PREFLIGHT).
    
    Returns:
        (is_blocked, reason) - True if target should be skipped
    """
    from backend.db import is_paused_or_cooldown
    return is_paused_or_cooldown(newsletter_id)


def filter_targets_by_governance(targets: List[Dict], allowed_statuses: List[str] = None) -> List[Dict]:
    """
    Filter targets by governance rules.
    
    Args:
        targets: List of target dicts
        allowed_statuses: Optional list of allowed decision_status values
    
    Returns:
        Filtered list of targets that pass governance checks
    """
    if allowed_statuses is None:
        allowed_statuses = ['auto_subscribe', 'manual_review']
    
    filtered = []
    for target in targets:
        target_id = target.get('id')
        if not target_id:
            continue
        
        # Check pause/cooldown
        is_blocked, reason = check_governance_block(target_id)
        if is_blocked:
            continue
        
        # Check decision status if allowed_statuses specified
        if allowed_statuses:
            from backend.db import get_decision
            decision = get_decision(target_id)
            if decision:
                if decision.get('decision_status') not in allowed_statuses:
                    continue
        
        filtered.append(target)
    
    return filtered


def filter_newsletter_targets(
    targets: List[Dict],
    priority: Optional[str] = None,
    include_statuses: Optional[List[str]] = None,
    exclude_statuses: Optional[List[str]] = None,
    enforce_governance: bool = True
) -> Tuple[List[Dict], Dict]:
    """
    Canonical target filtering function.
    
    Args:
        targets: List of newsletter target dicts
        priority: Filter by priority ('p0', 'p1', 'p2', or None for all)
        include_statuses: Only include targets with these statuses (e.g., ['subscribed', 'confirmed'])
        exclude_statuses: Exclude targets with these statuses (e.g., ['rejected', 'paused'])
        enforce_governance: If True, exclude paused/cooldown/rejected targets
    
    Returns:
        Tuple of (filtered_targets, breakdown_dict)
        breakdown_dict contains:
            - total_loaded
            - after_priority_filter
            - after_status_filter
            - after_governance_filter
            - blocked_count
            - blocked_reasons (dict of reason -> count)
            - status_counts (dict of status -> count)
    """
    from backend.db import get_decision, is_paused_or_cooldown
    from collections import Counter
    
    breakdown = {
        'total_loaded': len(targets),
        'after_priority_filter': 0,
        'after_status_filter': 0,
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


# Decision statuses
STATUS_AUTO_SUBSCRIBE = 'auto_subscribe'
STATUS_MANUAL_REVIEW = 'manual_review'
STATUS_REJECTED = 'rejected'
STATUS_PAUSED = 'paused'
STATUS_COOLDOWN = 'cooldown'

# Recommended actions
ACTION_ATTEMPT_SUBSCRIPTION = 'attempt_subscription'
ACTION_OPEN_SIGNUP_PAGE = 'open_signup_page'
ACTION_AWAIT_OPT_IN = 'await_opt_in'
ACTION_ABANDON = 'abandon'
ACTION_DO_NOTHING = 'do_nothing'

# Decision thresholds (explicit, documented)
THRESHOLD_AUTO_SUBSCRIBE = 70  # Quality score >= 70 → auto_subscribe
THRESHOLD_MANUAL_REVIEW = 40   # 40 <= score < 70 → manual_review
THRESHOLD_REJECT = 40          # score < 40 → rejected

# Failure thresholds
MAX_CONSECUTIVE_FAILURES = 3   # N failures → auto-pause
COOLDOWN_HOURS = 24            # Cooldown period after temporary blocks


def evaluate_decision(
    newsletter_id: str,
    quality_score: int,
    quality_features: Dict,
    feasibility: str,
    consecutive_failures: int = 0,
    last_failure_type: Optional[str] = None,
    paused: bool = False,
    paused_reason: Optional[str] = None,
    cooldown_until: Optional[str] = None,
    current_status: Optional[str] = None
) -> Dict:
    """
    Evaluate subscription decision for a newsletter target.
    
    Args:
        newsletter_id: Target ID
        quality_score: Newsletter quality score (0-100)
        quality_features: Dict with macro_keyword_density, event_keywords, etc.
        feasibility: 'feasible_http_post' | 'requires_manual' | 'captcha_blocked' | etc.
        consecutive_failures: Number of consecutive subscription failures
        last_failure_type: Type of last failure ('captcha', 'timeout', 'blocked', etc.)
        paused: Whether target is manually paused
        paused_reason: Reason for pause
        cooldown_until: ISO datetime string for cooldown expiration
        current_status: Current decision status (for audit trail)
    
    Returns:
        Decision record dict with all required fields
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    
    # Rule 1: Check pause (hard block)
    if paused:
        return {
            'newsletter_id': newsletter_id,
            'decision_status': STATUS_PAUSED,
            'decision_score': quality_score,
            'decision_reason': f'Manually paused: {paused_reason or "No reason provided"}',
            'decision_features_json': json.dumps(quality_features),
            'recommended_next_action': ACTION_DO_NOTHING,
            'last_evaluated_at': now_iso,
            'evidence_path': None,
            'consecutive_failures': consecutive_failures,
            'last_failure_type': last_failure_type,
            'paused': True,
            'paused_reason': paused_reason,
            'cooldown_until': cooldown_until
        }
    
    # Rule 2: Check cooldown (hard block)
    if cooldown_until:
        try:
            cooldown_dt = datetime.fromisoformat(cooldown_until.replace('Z', '+00:00'))
            if now < cooldown_dt:
                return {
                    'newsletter_id': newsletter_id,
                    'decision_status': STATUS_COOLDOWN,
                    'decision_score': quality_score,
                    'decision_reason': f'Cooldown until {cooldown_until}',
                    'decision_features_json': json.dumps(quality_features),
                    'recommended_next_action': ACTION_DO_NOTHING,
                    'last_evaluated_at': now_iso,
                    'evidence_path': None,
                    'consecutive_failures': consecutive_failures,
                    'last_failure_type': last_failure_type,
                    'paused': False,
                    'paused_reason': None,
                    'cooldown_until': cooldown_until
                }
        except (ValueError, AttributeError):
            pass  # Invalid cooldown, continue evaluation
    
    # Rule 3: Auto-pause on consecutive failures
    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        cooldown_until_new = (now + timedelta(hours=COOLDOWN_HOURS)).isoformat()
        return {
            'newsletter_id': newsletter_id,
            'decision_status': STATUS_PAUSED,
            'decision_score': quality_score,
            'decision_reason': f'Auto-paused: {consecutive_failures} consecutive failures (last: {last_failure_type})',
            'decision_features_json': json.dumps(quality_features),
            'recommended_next_action': ACTION_DO_NOTHING,
            'last_evaluated_at': now_iso,
            'evidence_path': None,
            'consecutive_failures': consecutive_failures,
            'last_failure_type': last_failure_type,
            'paused': True,
            'paused_reason': f'{consecutive_failures} consecutive failures',
            'cooldown_until': cooldown_until_new
        }
    
    # Rule 4: Terminal states cannot be auto-upgraded (GOVERNANCE)
    # Once rejected or manually paused, only explicit human action can change
    terminal_states = [STATUS_REJECTED]
    if current_status in terminal_states and paused:
        # Terminal state + manual pause: do not auto-upgrade
        return {
            'newsletter_id': newsletter_id,
            'decision_status': STATUS_PAUSED,
            'decision_score': quality_score,
            'decision_reason': f'Terminal state (manual pause): {paused_reason or "No reason"}',
            'decision_features_json': json.dumps(quality_features),
            'recommended_next_action': ACTION_DO_NOTHING,
            'last_evaluated_at': now_iso,
            'evidence_path': None,
            'consecutive_failures': consecutive_failures,
            'last_failure_type': last_failure_type,
            'paused': True,
            'paused_reason': paused_reason,
            'cooldown_until': cooldown_until
        }
    
    # Rule 5: Quality-based decision (only if not paused/cooldown)
    if quality_score >= THRESHOLD_AUTO_SUBSCRIBE:
        # High quality → auto_subscribe (if feasible)
        if feasibility in ['feasible_http_post', 'requires_manual']:
            action = ACTION_ATTEMPT_SUBSCRIPTION if feasibility == 'feasible_http_post' else ACTION_OPEN_SIGNUP_PAGE
            reason = f'High quality score ({quality_score}), {quality_features.get("explanation", "strong signals")}'
            return {
                'newsletter_id': newsletter_id,
                'decision_status': STATUS_AUTO_SUBSCRIBE,
                'decision_score': quality_score,
                'decision_reason': reason,
                'decision_features_json': json.dumps(quality_features),
                'recommended_next_action': action,
                'last_evaluated_at': now_iso,
                'evidence_path': None,
                'consecutive_failures': consecutive_failures,
                'last_failure_type': last_failure_type,
                'paused': False,
                'paused_reason': None,
                'cooldown_until': None
            }
        else:
            # High quality but blocked → manual review
            reason = f'High quality ({quality_score}) but blocked: {feasibility}'
            return {
                'newsletter_id': newsletter_id,
                'decision_status': STATUS_MANUAL_REVIEW,
                'decision_score': quality_score,
                'decision_reason': reason,
                'decision_features_json': json.dumps(quality_features),
                'recommended_next_action': ACTION_OPEN_SIGNUP_PAGE,
                'last_evaluated_at': now_iso,
                'evidence_path': None,
                'consecutive_failures': consecutive_failures,
                'last_failure_type': last_failure_type,
                'paused': False,
                'paused_reason': None,
                'cooldown_until': None
            }
    
    elif quality_score >= THRESHOLD_MANUAL_REVIEW:
        # Medium quality → manual review
        reason = f'Medium quality score ({quality_score}), requires human evaluation'
        return {
            'newsletter_id': newsletter_id,
            'decision_status': STATUS_MANUAL_REVIEW,
            'decision_score': quality_score,
            'decision_reason': reason,
            'decision_features_json': json.dumps(quality_features),
            'recommended_next_action': ACTION_OPEN_SIGNUP_PAGE,
            'last_evaluated_at': now_iso,
            'evidence_path': None,
            'consecutive_failures': consecutive_failures,
            'last_failure_type': last_failure_type,
            'paused': False,
            'paused_reason': None,
            'cooldown_until': None
        }
    
    else:
        # Low quality → rejected
        reason = f'Low quality score ({quality_score}), insufficient macro-signal content'
        return {
            'newsletter_id': newsletter_id,
            'decision_status': STATUS_REJECTED,
            'decision_score': quality_score,
            'decision_reason': reason,
            'decision_features_json': json.dumps(quality_features),
            'recommended_next_action': ACTION_ABANDON,
            'last_evaluated_at': now_iso,
            'evidence_path': None,
            'consecutive_failures': consecutive_failures,
            'last_failure_type': last_failure_type,
            'paused': False,
            'paused_reason': None,
            'cooldown_until': None
        }


def load_decision_data(newsletter_id: str) -> Tuple[Optional[Dict], Optional[Dict], Optional[str]]:
    """
    Load quality stats, sender stats, and feasibility for a newsletter.
    
    Returns:
        (quality_data, sender_data, feasibility)
    """
    from backend.db import get_db
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Load quality stats
    cursor.execute("""
        SELECT emails_seen, intel_items_extracted, rejection_rate, quality_score
        FROM newsletter_quality
        WHERE newsletter_id = ?
    """, (newsletter_id,))
    quality_row = cursor.fetchone()
    quality_data = dict(quality_row) if quality_row else None
    
    # Load sender stats (aggregate)
    cursor.execute("""
        SELECT 
            SUM(emails_seen) as total_emails_seen,
            SUM(intel_items_extracted) as total_intel_items,
            AVG(rejection_rate) as avg_rejection_rate
        FROM sender_stats
        WHERE newsletter_id = ?
    """, (newsletter_id,))
    sender_row = cursor.fetchone()
    sender_data = dict(sender_row) if sender_row else None
    
    # Load feasibility from newsletter_targets.json
    import json
    from pathlib import Path
    backend_dir = Path(__file__).parent.parent.parent
    targets_path = backend_dir / 'backend' / 'newsletter_targets.json'
    feasibility = 'unknown'
    if targets_path.exists():
        with open(targets_path) as f:
            targets_data = json.load(f)
            for target in targets_data.get('targets', []):
                if target.get('id') == newsletter_id:
                    acq = target.get('acquisition', {})
                    feasibility = acq.get('automation_feasibility', 'unknown')
                    break
    
    conn.close()
    return quality_data, sender_data, feasibility


def compute_decision_features(
    quality_data: Optional[Dict],
    sender_data: Optional[Dict],
    feasibility: str
) -> Dict:
    """
    Compute structured decision features for explanation.
    
    Returns:
        Dict with macro_keyword_density, event_keywords, rejection_rate, etc.
    """
    features = {
        'macro_keyword_density': 0.0,
        'event_keywords': 0,
        'rejection_rate': 0.0,
        'historical_yield': 0.0,
        'feasibility': feasibility,
        'explanation': 'No data available'
    }
    
    if quality_data:
        emails_seen = quality_data.get('emails_seen', 0)
        intel_items = quality_data.get('intel_items_extracted', 0)
        rejection_rate = quality_data.get('rejection_rate', 0.0)
        quality_score = quality_data.get('quality_score', 0)
        
        features['rejection_rate'] = round(rejection_rate, 3)
        features['historical_yield'] = round(intel_items / emails_seen, 3) if emails_seen > 0 else 0.0
        features['quality_score'] = quality_score
        
        # Build explanation
        parts = []
        if quality_score >= 70:
            parts.append('high quality')
        elif quality_score >= 40:
            parts.append('medium quality')
        else:
            parts.append('low quality')
        
        if emails_seen > 0:
            parts.append(f'{intel_items}/{emails_seen} intel items')
        
        if rejection_rate < 0.2:
            parts.append('low rejection rate')
        elif rejection_rate > 0.8:
            parts.append('high rejection rate')
        
        features['explanation'] = ', '.join(parts) if parts else 'insufficient data'
    
    return features


def upsert_decision(decision: Dict, previous_decision: Optional[Dict] = None):
    """
    Upsert decision record and create audit log entry.
    
    Enforces idempotency: if decision unchanged, no DB writes.
    
    GUARDRAIL: This function should ONLY be called from evaluate_decisions.py.
    No other script should mutate newsletter_decisions table directly.
    Failure tracking (consecutive_failures) is allowed via record_subscription_failure().
    
    Args:
        decision: Decision record dict
        previous_decision: Previous decision (for audit trail)
    """
    from backend.db import get_db
    
    # Check idempotency: if decision unchanged, skip write
    if previous_decision:
        prev_status = previous_decision.get('decision_status')
        prev_score = previous_decision.get('decision_score')
        prev_reason = previous_decision.get('decision_reason')
        
        curr_status = decision.get('decision_status')
        curr_score = decision.get('decision_score')
        curr_reason = decision.get('decision_reason')
        
        # If all key fields unchanged, skip write (idempotent)
        if (prev_status == curr_status and 
            prev_score == curr_score and 
            prev_reason == curr_reason):
            return  # No change, skip DB write
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Upsert decision
    cursor.execute("""
        INSERT OR REPLACE INTO newsletter_decisions
        (newsletter_id, decision_status, decision_score, decision_reason,
         decision_features_json, recommended_next_action, last_evaluated_at,
         evidence_path, consecutive_failures, last_failure_type,
         paused, paused_reason, cooldown_until)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        decision['newsletter_id'],
        decision['decision_status'],
        decision['decision_score'],
        decision['decision_reason'],
        decision['decision_features_json'],
        decision['recommended_next_action'],
        decision['last_evaluated_at'],
        decision.get('evidence_path'),
        decision.get('consecutive_failures', 0),
        decision.get('last_failure_type'),
        1 if decision.get('paused') else 0,
        decision.get('paused_reason'),
        decision.get('cooldown_until')
    ))
    
    # Create audit log entry ONLY if status changed (idempotent)
    if previous_decision and previous_decision.get('decision_status') != decision['decision_status']:
        cursor.execute("""
            INSERT INTO decision_audit_log
            (newsletter_id, previous_status, new_status, previous_score, new_score,
             reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            decision['newsletter_id'],
            previous_decision.get('decision_status'),
            decision['decision_status'],
            previous_decision.get('decision_score'),
            decision['decision_score'],
            decision['decision_reason'],
            decision['last_evaluated_at']
        ))
    
    conn.commit()
    conn.close()


def evaluate_all_targets(dry_run: bool = False) -> Dict:
    """
    Evaluate decisions for all newsletter targets.
    
    Returns:
        Summary dict with counts by status
    """
    import json
    from pathlib import Path
    
    backend_dir = Path(__file__).parent.parent.parent
    targets_path = backend_dir / 'backend' / 'newsletter_targets.json'
    
    if not targets_path.exists():
        return {'error': 'newsletter_targets.json not found'}
    
    with open(targets_path) as f:
        targets_data = json.load(f)
    
    targets = targets_data.get('targets', [])
    summary = {
        'auto_subscribe': 0,
        'manual_review': 0,
        'rejected': 0,
        'paused': 0,
        'cooldown': 0,
        'total': len(targets)
    }
    
    for target in targets:
        newsletter_id = target.get('id')
        if not newsletter_id:
            continue
        
        # Load current decision
        from backend.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT decision_status, decision_score, paused, paused_reason, cooldown_until,
                   consecutive_failures, last_failure_type
            FROM newsletter_decisions
            WHERE newsletter_id = ?
        """, (newsletter_id,))
        prev_row = cursor.fetchone()
        previous_decision = dict(prev_row) if prev_row else None
        conn.close()
        
        # Load quality data
        quality_data, sender_data, feasibility = load_decision_data(newsletter_id)
        
        # Compute quality score (use existing or default)
        quality_score = 50
        quality_features = {}
        if quality_data:
            quality_score = quality_data.get('quality_score', 50)
            quality_features = compute_decision_features(quality_data, sender_data, feasibility)
        else:
            # No quality data yet, use default
            quality_features = compute_decision_features(None, None, feasibility)
        
        # Get governance flags from target
        acq = target.get('acquisition', {})
        paused = target.get('status') == 'paused' or (previous_decision and previous_decision.get('paused'))
        paused_reason = target.get('notes') if paused else None
        cooldown_until = previous_decision.get('cooldown_until') if previous_decision else None
        consecutive_failures = previous_decision.get('consecutive_failures', 0) if previous_decision else 0
        last_failure_type = previous_decision.get('last_failure_type') if previous_decision else None
        
        # Enforce terminal states: rejected or manually paused cannot be auto-upgraded
        if previous_decision:
            prev_status = previous_decision.get('decision_status')
            is_manually_paused = paused and target.get('status') == 'paused'
            if prev_status == STATUS_REJECTED and is_manually_paused:
                # Terminal: do not re-evaluate, keep existing decision
                summary[prev_status] = summary.get(prev_status, 0) + 1
                continue
        
        # Evaluate decision
        decision = evaluate_decision(
            newsletter_id=newsletter_id,
            quality_score=quality_score,
            quality_features=quality_features,
            feasibility=feasibility,
            consecutive_failures=consecutive_failures,
            last_failure_type=last_failure_type,
            paused=paused,
            paused_reason=paused_reason,
            cooldown_until=cooldown_until,
            current_status=previous_decision.get('decision_status') if previous_decision else None
        )
        
        # Update summary
        status = decision['decision_status']
        summary[status] = summary.get(status, 0) + 1
        
        # Upsert decision (unless dry-run)
        if not dry_run:
            upsert_decision(decision, previous_decision)
    
    return summary
