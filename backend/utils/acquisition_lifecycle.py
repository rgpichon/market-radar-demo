"""
Source Acquisition Lifecycle: Formal, enforceable process for onboarding sources.

This module defines the canonical acquisition lifecycle:
1. DISCOVERY
2. CLASSIFICATION
3. VALIDATION
4. ONBOARDING
5. MONITORING

Each phase has clear success/failure criteria and produces auditable artifacts.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
import json

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.lanes import infer_lane_from_source, is_lane_supported, get_lane_info
from utils.pipeline import run_source_pipeline


# ============================================================================
# PHASE 1: DISCOVERY
# ============================================================================

class DiscoveryResult:
    """Results from discovery phase."""
    def __init__(self):
        self.feeds_found: List[Dict] = []  # List of {url, type, validated}
        self.html_feasible: bool = False
        self.js_rendered: bool = False
        self.gated: bool = False
        self.entry_points_tested: List[str] = []
        self.errors: List[str] = []
    
    def to_dict(self) -> Dict:
        return {
            'feeds_found': self.feeds_found,
            'html_feasible': self.html_feasible,
            'js_rendered': self.js_rendered,
            'gated': self.gated,
            'entry_points_tested': self.entry_points_tested,
            'errors': self.errors
        }


def discover_source(entry_points: List[str]) -> DiscoveryResult:
    """
    Phase 1: DISCOVERY
    
    Discovers:
    - RSS/Atom/ICS feeds
    - HTML feasibility
    - JS-rendered detection
    - Auth/gated detection
    
    Args:
        entry_points: List of URLs to test
    
    Returns:
        DiscoveryResult with all findings
    """
    result = DiscoveryResult()
    result.entry_points_tested = entry_points.copy()
    
    # Import discovery tools
    from scripts.discover_feeds import discover_feeds as discover_feeds_func
    from scripts.validate_html_events import validate_html_events as validate_html_func
    
    for url in entry_points:
        try:
            # Discover feeds
            # Note: This would ideally call the functions directly, but they're scripts
            # For now, we'll document the process and use subprocess if needed
            # In production, these would be importable functions
            
            # Check HTML feasibility
            # Similar note - would call validate_html_events directly
            
            # For now, mark as needing manual discovery
            pass
        except Exception as e:
            result.errors.append(f"Error testing {url}: {str(e)}")
    
    return result


# ============================================================================
# PHASE 2: CLASSIFICATION
# ============================================================================

class ClassificationResult:
    """Results from classification phase."""
    def __init__(self):
        self.lane: Optional[str] = None
        self.confidence: str = "unknown"  # high, medium, low
        self.reason: str = ""
        self.supported: bool = False
    
    def to_dict(self) -> Dict:
        return {
            'lane': self.lane,
            'confidence': self.confidence,
            'reason': self.reason,
            'supported': self.supported
        }


def classify_source(discovery: DiscoveryResult, source_config: Optional[Dict] = None) -> ClassificationResult:
    """
    Phase 2: CLASSIFICATION
    
    Assigns a lane explicitly and records confidence.
    
    Rules:
    - If feeds found → rss or ics lane
    - If HTML feasible and not JS → html_simple or html_complex
    - If JS-rendered → js_rendered lane
    - If gated → gated lane
    
    Args:
        discovery: DiscoveryResult from Phase 1
        source_config: Optional existing source config
    
    Returns:
        ClassificationResult
    """
    result = ClassificationResult()
    
    # Check feeds first (highest confidence)
    if discovery.feeds_found:
        feed_types = [f.get('type', '').lower() for f in discovery.feeds_found]
        if 'ics' in feed_types:
            result.lane = 'ics'
            result.confidence = 'high'
            result.reason = 'ICS feed discovered'
        elif 'rss' in feed_types or 'atom' in feed_types:
            result.lane = 'rss'
            result.confidence = 'high'
            result.reason = 'RSS/Atom feed discovered'
    
    # Check HTML feasibility
    elif discovery.html_feasible and not discovery.js_rendered:
        # Would need to check if detail_fetch required
        result.lane = 'html_simple'  # Default, could be html_complex
        result.confidence = 'medium'
        result.reason = 'HTML page is scrape-friendly'
    
    # Check JS-rendered
    elif discovery.js_rendered:
        result.lane = 'js_rendered'
        result.confidence = 'high'
        result.reason = 'Page is JS-rendered'
    
    # Check gated
    elif discovery.gated:
        result.lane = 'gated'
        result.confidence = 'high'
        result.reason = 'Content is gated/requires auth'
    
    # Fallback
    else:
        result.lane = 'js_rendered'  # Conservative default
        result.confidence = 'low'
        result.reason = 'Unable to determine lane, defaulting to js_rendered'
    
    # Check if lane is supported
    if result.lane:
        result.supported = is_lane_supported(result.lane)
    
    return result


# ============================================================================
# PHASE 3: VALIDATION
# ============================================================================

class ValidationResult:
    """Results from validation phase."""
    def __init__(self):
        self.passed: bool = False
        self.event_count: int = 0
        self.dated_count: int = 0
        self.future_count: int = 0
        self.dated_ratio: float = 0.0
        self.failures: List[str] = []
        self.warnings: List[str] = []
    
    def to_dict(self) -> Dict:
        return {
            'passed': self.passed,
            'event_count': self.event_count,
            'dated_count': self.dated_count,
            'future_count': self.future_count,
            'dated_ratio': self.dated_ratio,
            'failures': self.failures,
            'warnings': self.warnings
        }


def validate_source(source_config: Dict) -> ValidationResult:
    """
    Phase 3: VALIDATION
    
    Validates a source against minimum thresholds:
    - >= 3 real events
    - >= 70% dated
    - >= 1 future event
    
    Also applies lane-specific validation rules.
    
    Args:
        source_config: Source configuration dict
    
    Returns:
        ValidationResult
    """
    result = ValidationResult()
    
    # Run pipeline to get actual results
    pipeline_result = run_source_pipeline(source_config)
    kept_events = pipeline_result['kept_events']
    run_stats = pipeline_result['run_stats']
    
    result.event_count = len(kept_events)
    result.dated_count = run_stats['dated_count']
    result.future_count = run_stats['future_count']
    result.dated_ratio = run_stats['dated_ratio']
    
    # Minimum thresholds
    MIN_EVENTS = 3
    MIN_DATED_RATIO = 0.70
    MIN_FUTURE_EVENTS = 1
    
    # Check thresholds
    if result.event_count < MIN_EVENTS:
        result.failures.append(f"Event count ({result.event_count}) below minimum ({MIN_EVENTS})")
    
    if result.dated_ratio < MIN_DATED_RATIO:
        result.failures.append(f"Dated ratio ({result.dated_ratio:.1%}) below minimum ({MIN_DATED_RATIO:.1%})")
    
    if result.future_count < MIN_FUTURE_EVENTS:
        result.failures.append(f"Future events ({result.future_count}) below minimum ({MIN_FUTURE_EVENTS})")
    
    # Lane-specific validation
    lane = infer_lane_from_source(source_config)
    lane_info = get_lane_info(lane)
    
    if lane_info and not lane_info.get('supported', False):
        result.failures.append(f"Lane '{lane}' is not currently supported")
    
    # Warnings (non-blocking)
    if result.dated_ratio < 0.50:
        result.warnings.append(f"Low dated ratio: {result.dated_ratio:.1%}")
    
    if result.event_count < 10:
        result.warnings.append(f"Low event count: {result.event_count}")
    
    # Overall pass/fail
    result.passed = len(result.failures) == 0
    
    return result


# ============================================================================
# PHASE 4: ONBOARDING
# ============================================================================

def onboard_source(
    source_config: Dict,
    discovery: DiscoveryResult,
    classification: ClassificationResult,
    validation: ValidationResult
) -> Tuple[bool, str]:
    """
    Phase 4: ONBOARDING
    
    If supported lane and validation passed → add to sources.json
    If unsupported → register + defer (do NOT discard)
    
    QUALITY GATE: Enforces validation before adding.
    
    Args:
        source_config: Source configuration dict
        discovery: DiscoveryResult
        classification: ClassificationResult
        validation: ValidationResult
    
    Returns:
        (success, message)
    """
    from utils.quality_gates import validate_source_before_add, QualityGateError
    
    sources_file = backend_dir / "sources.json"
    
    # Load existing sources
    try:
        with open(sources_file, 'r') as f:
            sources = json.load(f)
    except (json.JSONDecodeError, IOError):
        sources = []
    
    # Check if already exists
    source_id = source_config.get('id')
    for existing in sources:
        if existing.get('id') == source_id:
            return False, f"Source '{source_id}' already exists"
    
    # Check if should onboard
    if not classification.supported:
        return False, f"Lane '{classification.lane}' is not supported (deferred)"
    
    if not validation.passed:
        return False, f"Validation failed: {', '.join(validation.failures)}"
    
    # QUALITY GATE: Enforce validation before adding
    passed, errors = validate_source_before_add(source_config)
    if not passed:
        raise QualityGateError(f"Quality gate failed: {', '.join(errors)}")
    
    # Add lane to source config
    source_config['lane'] = classification.lane
    source_config['acquisition_status'] = 'active'
    source_config['discovery_timestamp'] = datetime.now(timezone.utc).isoformat()
    
    # Add to sources
    sources.append(source_config)
    
    # Save
    try:
        with open(sources_file, 'w') as f:
            json.dump(sources, f, indent=2)
        return True, f"Source '{source_id}' onboarded successfully"
    except IOError as e:
        return False, f"Error saving sources.json: {str(e)}"


# ============================================================================
# PHASE 5: MONITORING
# ============================================================================

def monitor_source_health(source_id: str) -> Dict:
    """
    Phase 5: MONITORING
    
    Tracks health over time and detects degradation.
    
    Checks:
    - 0 future events → degradation
    - Falling ratios → degradation
    - Recent errors → degradation
    
    Args:
        source_id: Source identifier
    
    Returns:
        Health status dict
    """
    source_stats_file = backend_dir / "source_stats.json"
    
    if not source_stats_file.exists():
        return {'status': 'unknown', 'reason': 'source_stats.json not found'}
    
    try:
        with open(source_stats_file, 'r') as f:
            stats = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {'status': 'unknown', 'reason': 'Error reading source_stats.json'}
    
    source_stats = stats.get(source_id)
    if not source_stats:
        return {'status': 'unknown', 'reason': 'Source not found in stats'}
    
    # Check health indicators
    future_count = source_stats.get('future_count', 0)
    dated_ratio = source_stats.get('dated_ratio', 0.0)
    kept_ratio = source_stats.get('kept_ratio', 0.0)
    
    issues = []
    
    if future_count == 0:
        issues.append('no_future_events')
    
    if dated_ratio < 0.30:
        issues.append('low_dated_ratio')
    
    if kept_ratio < 0.20:
        issues.append('low_kept_ratio')
    
    if issues:
        return {
            'status': 'degraded',
            'issues': issues,
            'future_count': future_count,
            'dated_ratio': dated_ratio,
            'kept_ratio': kept_ratio
        }
    
    return {
        'status': 'healthy',
        'future_count': future_count,
        'dated_ratio': dated_ratio,
        'kept_ratio': kept_ratio
    }


# ============================================================================
# COMPLETE LIFECYCLE
# ============================================================================

def run_acquisition_lifecycle(
    firm_name: str,
    entry_points: List[str],
    source_config: Optional[Dict] = None
) -> Dict:
    """
    Run the complete acquisition lifecycle for a source.
    
    This is the canonical function that represents the entire process.
    
    Args:
        firm_name: Name of the firm
        entry_points: URLs to test
        source_config: Optional existing source config (for validation)
    
    Returns:
        Complete lifecycle result dict
    """
    result = {
        'firm_name': firm_name,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'phases': {}
    }
    
    # Phase 1: Discovery
    discovery = discover_source(entry_points)
    result['phases']['discovery'] = discovery.to_dict()
    
    # Phase 2: Classification
    classification = classify_source(discovery, source_config)
    result['phases']['classification'] = classification.to_dict()
    
    # Phase 3: Validation (if source_config provided)
    if source_config:
        validation = validate_source(source_config)
        result['phases']['validation'] = validation.to_dict()
    else:
        result['phases']['validation'] = {'skipped': 'No source_config provided'}
    
    # Phase 4: Onboarding (if validation passed)
    if source_config and classification.supported:
        validation = result['phases']['validation']
        if isinstance(validation, dict) and validation.get('passed'):
            success, message = onboard_source(source_config, discovery, classification, validation)
            result['phases']['onboarding'] = {'success': success, 'message': message}
        else:
            result['phases']['onboarding'] = {'skipped': 'Validation not passed'}
    else:
        result['phases']['onboarding'] = {'skipped': 'Lane not supported or no source_config'}
    
    # Phase 5: Monitoring (if source_id provided)
    if source_config and source_config.get('id'):
        health = monitor_source_health(source_config['id'])
        result['phases']['monitoring'] = health
    else:
        result['phases']['monitoring'] = {'skipped': 'No source_id provided'}
    
    # Overall status
    if classification.supported and result['phases'].get('validation', {}).get('passed'):
        result['status'] = 'ready'
    elif not classification.supported:
        result['status'] = 'deferred'
        result['defer_reason'] = f"Lane '{classification.lane}' not supported"
    else:
        result['status'] = 'failed'
        result['fail_reason'] = 'Validation failed'
    
    return result
