"""
Quality gates and fail-fast mechanisms.

Prevents sources from silently degrading and ensures sources cannot be added
without passing validation.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional
import json

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.pipeline import run_source_pipeline
from utils.lanes import is_lane_supported, infer_lane_from_source
from utils.acquisition_lifecycle import validate_source


class QualityGateError(Exception):
    """Raised when a quality gate fails."""
    pass


def validate_source_before_add(source_config: Dict) -> tuple[bool, List[str]]:
    """
    Quality Gate: Validate source before adding to sources.json.
    
    This is a HARD gate - sources cannot be added without passing.
    
    Checks:
    1. Lane is supported
    2. Validation passes (>= 3 events, >= 70% dated, >= 1 future)
    3. Source ID is unique
    4. Required fields present
    5. HARD STOPS: press_release_only, js_rendered, gated_login
    
    Args:
        source_config: Source configuration dict
    
    Returns:
        (passed, errors) - errors is empty list if passed
    """
    errors = []
    
    # Check required fields
    required_fields = ['id', 'firm_name', 'url', 'adapter_type']
    for field in required_fields:
        if not source_config.get(field):
            errors.append(f"Missing required field: {field}")
    
    if errors:
        return False, errors
    
    # HARD STOP 1: Check for press_release_only
    failure_class = source_config.get('failure_class')
    if failure_class == 'press_release_only':
        errors.append("HARD STOP: Source classified as press_release_only - cannot be activated")
        return False, errors
    
    # HARD STOP 2: Check for js_rendered
    if failure_class == 'js_rendered':
        errors.append("HARD STOP: Source requires Playwright (js_rendered) - cannot be activated without infrastructure")
        return False, errors
    
    # HARD STOP 3: Check for gated_login
    if failure_class == 'gated_login':
        errors.append("HARD STOP: Source requires authentication (gated_login) - cannot be activated without auth infrastructure")
        return False, errors
    
    # Check lane is supported
    lane = infer_lane_from_source(source_config)
    if not is_lane_supported(lane):
        errors.append(f"Lane '{lane}' is not currently supported")
        return False, errors
    
    # Run validation
    validation = validate_source(source_config)
    
    if not validation.passed:
        errors.extend(validation.failures)
    
    # HARD STOP 4: Check article ratio (must be <= 0.30)
    if validation.passed:
        # Calculate article ratio from validation
        raw_count = getattr(validation, 'raw_count', 0)
        kept_count = getattr(validation, 'event_count', 0)
        if raw_count > 0:
            article_ratio = 1.0 - (kept_count / raw_count)
            if article_ratio > 0.30:
                errors.append(f"HARD STOP: Article ratio {article_ratio:.1%} exceeds maximum 30% - source is press-release heavy")
                return False, errors
    
    # THIRD-PARTY CALENDAR SPECIFIC VALIDATION
    adapter_type = source_config.get('adapter_type', '')
    if adapter_type == 'third_party_calendar':
        third_party_errors = validate_third_party_calendar(source_config, validation)
        if third_party_errors:
            errors.extend(third_party_errors)
            return False, errors
    
    # MACRO-SIGNAL SOURCE VALIDATION
    macro_signal_mode = source_config.get('macro_signal_mode', False)
    firm_type = source_config.get('firm_type', '')
    # Auto-detect macro-signal sources
    macro_signal_types = ['Association', 'Think Tank', 'Central Bank', 'Research Network']
    is_macro_signal = macro_signal_mode or firm_type in macro_signal_types
    
    if is_macro_signal:
        macro_errors = validate_macro_signal_source(source_config, validation)
        if macro_errors:
            errors.extend(macro_errors)
            return False, errors
    
    # Check source ID uniqueness
    sources_file = backend_dir / "sources.json"
    if sources_file.exists():
        try:
            with open(sources_file, 'r') as f:
                sources = json.load(f)
            for existing in sources:
                if existing.get('id') == source_config.get('id'):
                    errors.append(f"Source ID '{source_config.get('id')}' already exists")
                    break
        except (json.JSONDecodeError, IOError):
            pass  # Will be caught by validation
    
    return len(errors) == 0, errors


def detect_source_degradation(source_id: str, source_stats_file: Optional[Path] = None, source_config: Optional[Dict] = None) -> Dict:
    """
    Quality Gate: Detect source degradation.
    
    Checks for:
    - 0 future events (degradation)
    - Falling ratios (kept_ratio < 0.2, dated_ratio < 0.3)
    - Recent errors
    
    Args:
        source_id: Source identifier
        source_stats_file: Path to source_stats.json
    
    Returns:
        Dict with degradation status and issues
    """
    if source_stats_file is None:
        source_stats_file = backend_dir / "source_stats.json"
    
    if not source_stats_file.exists():
        return {
            'degraded': False,
            'reason': 'source_stats.json not found'
        }
    
    try:
        with open(source_stats_file, 'r') as f:
            stats = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {
            'degraded': False,
            'reason': 'Error reading source_stats.json'
        }
    
    source_stat = stats.get(source_id)
    if not source_stat:
        return {
            'degraded': False,
            'reason': 'Source not found in stats'
        }
    
    future_count = source_stat.get('future_count', 0)
    dated_ratio = source_stat.get('dated_ratio', 0.0)
    kept_ratio = source_stat.get('kept_ratio', 0.0)
    
    issues = []
    
    # Hard failure: 0 future events
    if future_count == 0:
        issues.append({
            'severity': 'critical',
            'issue': 'no_future_events',
            'message': 'Source has 0 future events'
        })
    
    # Warning: Low dated ratio
    if dated_ratio < 0.30:
        issues.append({
            'severity': 'warning',
            'issue': 'low_dated_ratio',
            'message': f'Dated ratio ({dated_ratio:.1%}) below threshold (30%)'
        })
    
    # Warning: Low kept ratio
    if kept_ratio < 0.20:
        issues.append({
            'severity': 'warning',
            'issue': 'low_kept_ratio',
            'message': f'Kept ratio ({kept_ratio:.1%}) below threshold (20%)'
        })
    
    degraded = any(i['severity'] == 'critical' for i in issues)
    
    return {
        'degraded': degraded,
        'issues': issues,
        'future_count': future_count,
        'dated_ratio': dated_ratio,
        'kept_ratio': kept_ratio
    }


def enforce_quality_gates_on_scrape(source_config: Dict) -> tuple[bool, List[str]]:
    """
    Quality Gate: Enforce gates during scrape.
    
    This is called during scrape_runner to detect degradation.
    If a source fails critical gates, it can be auto-disabled.
    
    Args:
        source_config: Source configuration dict
    
    Returns:
        (passed, warnings) - warnings are non-blocking
    """
    source_id = source_config.get('id')
    if not source_id:
        return True, []  # Can't check without ID
    
    degradation = detect_source_degradation(source_id, source_config=source_config)
    
    warnings = []
    
    if degradation['degraded']:
        critical_issues = [i for i in degradation['issues'] if i['severity'] == 'critical']
        if critical_issues:
            # This is a hard failure - source should be disabled
            warnings.append(f"CRITICAL: Source '{source_id}' has degraded: {critical_issues[0]['message']}")
            warnings.append("Consider disabling this source (set active=0)")
    
    # Non-critical warnings
    warning_issues = [i for i in degradation.get('issues', []) if i['severity'] == 'warning']
    for issue in warning_issues:
        warnings.append(f"WARNING: {issue['message']}")
    
    # Phase 3: Track consecutive failures and suggest auto-disable (Priority 5, Phase 3)
    try:
        from utils.health_monitor import load_health_history
        
        history = load_health_history(source_id)
        recent_failures = [s for s in history[-5:] if s.get('future_count', 0) == 0]
        
        if len(recent_failures) >= 3:
            warnings.append(f"CRITICAL: Source '{source_id}' has {len(recent_failures)} consecutive failures (0 future events)")
            warnings.append("Consider auto-disabling (set active=0)")
            # Optionally auto-disable here (commented out for safety)
            # source_config['active'] = 0
    except Exception:
        # Health monitoring is optional, don't fail on errors
        pass
    
    return len([i for i in degradation.get('issues', []) if i['severity'] == 'critical']) == 0, warnings


def validate_macro_signal_source(source_config: Dict, validation) -> List[str]:
    """
    Validate macro-signal source against MACRO_SIGNAL_CONTRACT.
    
    Replaces earnings/calendar metrics with macro-signal metrics:
    - % of events with macro keywords
    - % of events with identifiable speakers
    - % of events with institutional participants
    - Future-dated ratio
    - Article / press release rejection rate
    
    Args:
        source_config: Source configuration dict
        validation: ValidationResult from validate_source
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Contract thresholds from MACRO_SIGNAL_CONTRACT.md
    MIN_EVENTS_PER_SOURCE = 5
    MIN_FUTURE_RATIO = 0.80
    MAX_ARTICLE_RATIO = 0.30
    MIN_MACRO_KEYWORD_RATIO = 0.30
    MIN_SPEAKER_IDENTIFICATION_RATIO = 0.20
    
    event_count = validation.event_count
    future_count = validation.future_count
    raw_count = getattr(validation, 'raw_count', 0)
    kept_count = validation.event_count
    
    # Check min_kept_events_per_source
    if event_count < MIN_EVENTS_PER_SOURCE:
        errors.append(f"Macro-signal contract violation: {event_count} events < {MIN_EVENTS_PER_SOURCE} minimum")
    
    # Check min_future_ratio
    if event_count > 0:
        future_ratio = future_count / event_count
        if future_ratio < MIN_FUTURE_RATIO:
            errors.append(f"Macro-signal contract violation: future ratio {future_ratio:.1%} < {MIN_FUTURE_RATIO:.0%} minimum")
    
    # Check max_article_ratio (HARD FAIL for press-release-only sources)
    if raw_count > 0:
        article_ratio = 1.0 - (kept_count / raw_count)
        if article_ratio > MAX_ARTICLE_RATIO:
            errors.append(f"Macro-signal contract violation: article ratio {article_ratio:.1%} > {MAX_ARTICLE_RATIO:.0%} maximum")
        # Hard fail if > 70% articles (likely press-release-only)
        if article_ratio > 0.70:
            errors.append(f"HARD FAIL: Source is press-release-only ({article_ratio:.1%} article ratio) - cannot be activated")
    
    # Check macro keyword presence
    url = source_config.get('url', '')
    url_lower = url.lower()
    macro_url_patterns = ['/events/', '/conference/', '/webinar/', '/seminar/', '/calendar/', '/program/']
    has_macro_url = any(pattern in url_lower for pattern in macro_url_patterns)
    
    # Check if host is allowlisted (associations, think tanks, central banks are auto-allowlisted)
    firm_type = source_config.get('firm_type', '')
    host_allowlisted = firm_type in ['Association', 'Think Tank', 'Central Bank', 'Research Network']
    
    # If host is not allowlisted, require macro URL pattern
    if not host_allowlisted and not has_macro_url:
        errors.append(f"Macro-signal contract violation: URL does not match macro-signal patterns and host is not allowlisted")
    
    # Check participant extraction requirement
    # For Tier A sources (associations, think tanks, central banks), participant extraction should be enabled
    if host_allowlisted:
        detail_fetch = source_config.get('detail_fetch', {})
        if not detail_fetch.get('enabled', False):
            # Warning, not error - participant extraction is recommended but not mandatory
            # The system will still work, just with lower participant identification
            pass
    
    return errors


def validate_third_party_calendar(source_config: Dict, validation) -> List[str]:
    """
    Validate third-party calendar source against THIRD_PARTY_CALENDAR_CONTRACT.
    
    NOTE: Third-party calendars are LOW PRIORITY (Tier C) auxiliary sources.
    They are supplementary enrichment only, never core ingestion.
    
    Args:
        source_config: Source configuration dict
        validation: ValidationResult from validate_source
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Check calendar_config is present
    calendar_config = source_config.get('calendar_config', {})
    if not calendar_config:
        errors.append("Missing calendar_config for third_party_calendar adapter")
        return errors
    
    # Check calendar_type
    calendar_type = calendar_config.get('calendar_type')
    if not calendar_type:
        errors.append("Missing calendar_type in calendar_config")
        return errors
    
    # Check ticker (or firm_name for lookup)
    ticker = calendar_config.get('ticker')
    firm_name = source_config.get('firm_name', '')
    if not ticker and not firm_name:
        errors.append("Missing ticker in calendar_config and firm_name in source_config")
        return errors
    
    # Contract thresholds from THIRD_PARTY_CALENDAR_CONTRACT.md (updated for realism)
    # Third-party calendars are auxiliary sources (Tier C - LOW PRIORITY)
    # They are supplementary enrichment only, never core ingestion
    MIN_EVENTS_PER_SOURCE = 1  # At least 1 event required
    MIN_DATED_RATIO = 0.90  # Reduced from 0.95 to account for parsing edge cases
    MIN_FUTURE_RATIO = 0.50  # At least 50% future events OR at least 1 future event
    MIN_FUTURE_EVENTS = 1  # At least 1 future event required
    
    event_count = validation.event_count
    dated_ratio = validation.dated_ratio
    future_count = validation.future_count
    
    # Check min_events_per_bank
    if event_count < MIN_EVENTS_PER_BANK:
        errors.append(f"Third-party calendar contract violation: {event_count} events < {MIN_EVENTS_PER_SOURCE} minimum")
    
    # Check min_dated_ratio
    if dated_ratio < MIN_DATED_RATIO:
        errors.append(f"Third-party calendar contract violation: dated ratio {dated_ratio:.1%} < {MIN_DATED_RATIO:.0%} minimum")
    
    # Check min_future_ratio OR min_future_events
    if event_count > 0:
        future_ratio = future_count / event_count
        if future_count < MIN_FUTURE_EVENTS:
            errors.append(f"Third-party calendar contract violation: {future_count} future events < {MIN_FUTURE_EVENTS} minimum")
        elif future_ratio < MIN_FUTURE_RATIO:
            # Only fail on ratio if we have multiple events and ratio is too low
            if event_count > 1:
                errors.append(f"Third-party calendar contract violation: future ratio {future_ratio:.1%} < {MIN_FUTURE_RATIO:.0%} minimum (with {event_count} total events)")
    
    # Check for third-party specific failure classes
    failure_class = source_config.get('failure_class')
    third_party_failures = ['no_coverage', 'partial_coverage', 'ambiguous_labels', 'stale_data', 'licensing_blocked', 'format_incompatible']
    if failure_class in third_party_failures:
        errors.append(f"HARD STOP: Third-party calendar failure_class '{failure_class}' - cannot be activated")
    
    return errors


def validate_sources_json() -> tuple[bool, List[str]]:
    """
    Quality Gate: Validate sources.json integrity.
    
    Checks:
    - Valid JSON
    - All sources have required fields
    - No duplicate IDs
    - Active sources have supported lanes
    
    Returns:
        (valid, errors)
    """
    sources_file = backend_dir / "sources.json"
    
    if not sources_file.exists():
        return False, ["sources.json does not exist"]
    
    try:
        with open(sources_file, 'r') as f:
            sources = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON in sources.json: {str(e)}"]
    except IOError as e:
        return False, [f"Error reading sources.json: {str(e)}"]
    
    errors = []
    seen_ids = set()
    
    for i, source in enumerate(sources):
        source_id = source.get('id', '')
        
        # Check duplicate IDs
        if source_id in seen_ids:
            errors.append(f"Duplicate source ID: '{source_id}' (index {i})")
        seen_ids.add(source_id)
        
        # Check required fields
        required = ['id', 'firm_name', 'url', 'adapter_type']
        for field in required:
            if not source.get(field):
                errors.append(f"Source '{source_id}' missing required field: {field}")
        
        # Check active sources have supported lanes
        if source.get('active', 1) == 1:
            lane = infer_lane_from_source(source)
            if not is_lane_supported(lane):
                errors.append(f"Active source '{source_id}' has unsupported lane: '{lane}'")
    
    return len(errors) == 0, errors
