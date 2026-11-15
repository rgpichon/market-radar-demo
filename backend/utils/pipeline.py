"""
Single deterministic pipeline for processing events from a source.

This is the ONE choke point where all filtering, enrichment, and validation happens.
Pipeline stages (in order):
1. Extract (adapter)
2. Normalize (EventRaw -> EventNormalized)
3. Events-only filter
4. Postprocess rules
5. Semantic inference
6. Final validation
7. Compute run_stats
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.contracts import normalize_event
from utils.events_only import should_reject_as_article
from utils.postprocess import apply_postprocess
from utils.semantics import enrich_event_semantics
from utils.enrich import enrich_event
from utils.json_utils import ensure_list, ensure_dict


def run_source_pipeline(source_cfg: Dict) -> Dict:
    """
    Run the complete pipeline for a single source.
    
    Args:
        source_cfg: Source configuration dict with:
            - id: source_id
            - url: source URL
            - adapter_type: adapter type
            - firm_name: firm name
            - default_tags_json: default tags
            - enforce_events_only: bool
            - postprocess_rules: optional postprocess rules
            - firm_type: optional firm type for semantics
            - ... (adapter-specific config)
    
    Returns:
        {
            'raw_events': List[EventRaw],  # From adapter
            'kept_events': List[EventNormalized],  # After all filters
            'run_stats': {
                'raw_count': int,
                'kept_count': int,
                'dated_count': int,
                'undated_count': int,
                'future_count': int,
                'kept_ratio': float,
                'dated_ratio': float,
                'rejected': Dict[str, int]  # rejection reasons
            },
            'diagnostics': Dict  # Error info, extraction stats, etc.
        }
    """
    # Initialize result structure
    result = {
        'raw_events': [],
        'kept_events': [],
        'run_stats': {
            'raw_count': 0,
            'kept_count': 0,
            'dated_count': 0,
            'undated_count': 0,
            'future_count': 0,
            'kept_ratio': 0.0,
            'dated_ratio': 0.0,
            'rejected': {}
        },
        'diagnostics': {}
    }
    
    # Stage 1: Extract (adapter)
    raw_events, extraction_stats, diagnostics = _extract_events(source_cfg)
    result['raw_events'] = raw_events
    result['diagnostics'] = diagnostics
    if extraction_stats:
        result['diagnostics']['extraction_stats'] = extraction_stats
    
    raw_count = len(raw_events)
    result['run_stats']['raw_count'] = raw_count
    
    if raw_count == 0:
        # No events extracted, return early
        return result
    
    # Track rejections
    rejected = {}
    
    # Stage 2: Normalize each raw event
    normalized_events = []
    for raw_event in raw_events:
        # Add source_id to raw event if not present
        if 'source_id' not in raw_event:
            raw_event['source_id'] = source_cfg.get('id', '')
        
        normalized, rejection_reason = normalize_event(raw_event, source_cfg)
        if normalized is None:
            rejected[rejection_reason or 'normalization_failed'] = rejected.get(rejection_reason or 'normalization_failed', 0) + 1
            continue
        normalized_events.append(normalized)
    
    # Stage 3: Events-only filter
    enforce_events_only = source_cfg.get('enforce_events_only', True)
    events_after_filter = []
    for event in normalized_events:
        title = event.get('event_name', '')
        link = event.get('link', '')
        if should_reject_as_article(title, link, enforce_events_only):
            rejected['article_like'] = rejected.get('article_like', 0) + 1
            continue
        events_after_filter.append(event)
    
    # Stage 4: Postprocess rules
    events_after_postprocess = []
    for event in events_after_filter:
        processed = apply_postprocess(event, source_cfg)
        if processed is None:
            # Get rejection reason for logging
            from utils.postprocess import get_rejection_reason
            reason = get_rejection_reason(event, source_cfg) or 'postprocess_rejected'
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        events_after_postprocess.append(processed)
    
    # Stage 5: Semantic inference
    firm_type = source_cfg.get('firm_type')
    events_with_semantics = []
    for event in events_after_postprocess:
        # Enrich with format and tags (if not already done)
        if 'format' not in event or not event.get('format') or event.get('format') == 'Unknown':
            event = enrich_event(event, extra_text=event.get('raw_date_text', ''))
        
        # Enrich with semantics
        event = enrich_event_semantics(event, firm_type=firm_type)
        
        # Ensure intel_type is set (PHASE 1 - explicit integration per README)
        # Note: enrich_event_semantics already sets intel_type, but this ensures it's always set
        if 'intel_type' not in event or not event.get('intel_type'):
            from utils.semantics import infer_intel_type_for_scrape
            event['intel_type'] = infer_intel_type_for_scrape(
                event.get('event_name', ''),
                event.get('description', ''),
                event.get('date_time')
            )
        
        events_with_semantics.append(event)
    
    # Stage 5.5: Institutional participation inference (for macro-signal sources)
    # 
    # Macro-signal events are relevant ONLY if institutions appear as participants.
    # Participation can be inferred from:
    #   - explicit speaker lists (via detail_fetch)
    #   - panel participants (via detail_fetch)
    #   - event titles/descriptions (fallback inference)
    #
    # Banks are participants, not publishers. This stage infers institutional
    # participation via entity matching on speakers, panelists, and event content.
    #
    firm_type = source_cfg.get('firm_type', '')
    macro_signal_types = ['Association', 'Think Tank', 'Central Bank', 'Research Network']
    is_macro_signal = source_cfg.get('macro_signal_mode', False) or firm_type in macro_signal_types
    
    if is_macro_signal:
        from utils.entity_match import extract_bank_participants_with_evidence
        for event in events_with_semantics:
            # Skip if already has bank_participants_json (from detail_fetch - preferred method)
            if event.get('bank_participants_json'):
                continue
            
            # Fallback: Extract from title and description
            # This is secondary to detail_fetch participant extraction
            title = event.get('event_name', '')
            description = event.get('description', '') or event.get('raw_date_text', '')
            combined_text = f"{title} {description}".strip()
            
            if combined_text:
                matched_banks, evidence_path = extract_bank_participants_with_evidence(
                    combined_text, method='title_description'
                )
                if matched_banks:
                    event['bank_participants_json'] = matched_banks
    
    # Stage 6: Final validation
    kept_events = []
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    for event in events_with_semantics:
        # Final checks
        event_name = event.get('event_name', '')
        link = event.get('link', '')
        
        # Reject if title or link is empty after all processing
        if not event_name or not link:
            rejected['empty_after_processing'] = rejected.get('empty_after_processing', 0) + 1
            continue
        
        kept_events.append(event)
    
    result['kept_events'] = kept_events
    
    # Stage 7: Compute run_stats
    kept_count = len(kept_events)
    dated_count = 0
    undated_count = 0
    future_count = 0
    
    for event in kept_events:
        date_time = event.get('date_time')
        if date_time:
            dated_count += 1
            try:
                # Parse ISO string
                if isinstance(date_time, str):
                    if date_time.endswith('Z'):
                        date_time = date_time[:-1] + '+00:00'
                    dt = datetime.fromisoformat(date_time)
                else:
                    dt = date_time
                
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                
                if dt >= today_start:
                    future_count += 1
            except (ValueError, TypeError, AttributeError):
                pass
        else:
            undated_count += 1
    
    # Calculate ratios
    kept_ratio = kept_count / raw_count if raw_count > 0 else 0.0
    dated_ratio = dated_count / kept_count if kept_count > 0 else 0.0
    
    result['run_stats'] = {
        'raw_count': raw_count,
        'kept_count': kept_count,
        'dated_count': dated_count,
        'undated_count': undated_count,
        'future_count': future_count,
        'kept_ratio': round(kept_ratio, 3),
        'dated_ratio': round(dated_ratio, 3),
        'rejected': rejected
    }
    
    # Validate invariants
    assert raw_count >= kept_count, "raw_count must be >= kept_count"
    assert dated_count + undated_count == kept_count, "dated_count + undated_count must equal kept_count"
    assert future_count <= dated_count, "future_count must be <= dated_count"
    assert 0 <= kept_ratio <= 1, "kept_ratio must be in [0, 1]"
    assert 0 <= dated_ratio <= 1, "dated_ratio must be in [0, 1]"
    
    return result


def _extract_events(source_cfg: Dict) -> Tuple[List[Dict], Optional[Dict], Dict]:
    """
    Extract events using the appropriate adapter.
    
    Returns:
        (raw_events, extraction_stats, diagnostics)
    """
    import requests
    from bs4 import BeautifulSoup
    
    # Check if Playwright is available
    try:
        from adapters.playwright_adapter import PLAYWRIGHT_AVAILABLE
    except ImportError:
        PLAYWRIGHT_AVAILABLE = False
    
    adapter_type = source_cfg.get('adapter_type')
    source_url = source_cfg.get('url', '')
    diagnostics = {
        'adapter_type': adapter_type,
        'url': source_url
    }
    
    raw_events = []
    extraction_stats = None
    
    try:
        if adapter_type == 'rss':
            from adapters.rss_feed import extract_events as extract_rss
            # RSS adapter needs to be updated to return EventRaw
            events, stats = extract_rss(source_url, source_cfg, return_stats=True)
            raw_events = _convert_to_event_raw(events, source_cfg.get('id', ''))
            extraction_stats = stats
            
        elif adapter_type == 'ics':
            from adapters.ics_calendar import extract_events as extract_ics
            events, stats = extract_ics(source_url, source_cfg, return_stats=True)
            raw_events = _convert_to_event_raw(events, source_cfg.get('id', ''))
            extraction_stats = stats
            
        elif adapter_type == 'json_api':
            from adapters.json_api import fetch_and_extract as extract_json_api
            events, stats = extract_json_api(source_cfg, return_stats=True)
            raw_events = _convert_to_event_raw(events, source_cfg.get('id', ''))
            extraction_stats = stats
            
        elif adapter_type == 'json_ld':
            from utils.retry_handler import retry_request, PermanentError, RetryableError
            from utils.rate_limiter import get_rate_limiter
            
            # Get timeout config from source
            timeout_config = ensure_dict(source_cfg.get('timeout_config', {}))
            timeout_seconds = timeout_config.get('timeout_seconds', 15)  # Default 15s
            
            # Get rate limit config and apply rate limiting
            rate_limit_config = ensure_dict(source_cfg.get('rate_limit_config', {}))
            max_rps = rate_limit_config.get('max_requests_per_second', 1.0)
            delay = rate_limit_config.get('delay_between_requests', 1.0)
            
            limiter = get_rate_limiter(max_requests_per_second=max_rps, delay_between_requests=delay)
            limiter.wait_if_needed(source_url)
            
            # Get retry config from source
            retry_config = ensure_dict(source_cfg.get('retry_config', {}))
            max_attempts = retry_config.get('max_attempts', 3)
            backoff_multiplier = retry_config.get('backoff_multiplier', 2.0)
            initial_delay = retry_config.get('initial_delay', 1.0)
            
            # Get custom headers from source config if provided (for json_ld adapter)
            default_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            custom_headers = ensure_dict(source_cfg.get('custom_headers', {}))
            headers = {**default_headers, **custom_headers}  # Custom headers override defaults
            
            try:
                response = retry_request(
                    requests.get,
                    max_attempts=max_attempts,
                    backoff_multiplier=backoff_multiplier,
                    initial_delay=initial_delay,
                    url=source_url,
                    timeout=timeout_seconds,
                    headers=headers,
                    allow_redirects=True
                )
                html = response.text
                diagnostics['status_code'] = response.status_code
                diagnostics['final_url'] = response.url
                diagnostics['retry_success'] = True
            except PermanentError as e:
                diagnostics['error'] = f"Permanent error: {e}"
                diagnostics['error_type'] = 'permanent'
                diagnostics['retry_attempts'] = 1  # Only one attempt for permanent errors
                return [], None, diagnostics
            except RetryableError as e:
                diagnostics['error'] = f"Retryable error after retries: {e}"
                diagnostics['error_type'] = 'retryable'
                diagnostics['retry_attempts'] = max_attempts
                diagnostics['retry_success'] = False
                return [], None, diagnostics
            
            from adapters.json_ld import extract_events as extract_json_ld
            events = extract_json_ld(html, source_cfg)
            raw_events = _convert_to_event_raw(events, source_cfg.get('id', ''))
            extraction_stats = {'raw': len(raw_events), 'kept': len(raw_events), 'rejected': {}}
            
        elif adapter_type == 'html_list':
            from utils.retry_handler import retry_request, PermanentError, RetryableError
            from utils.rate_limiter import get_rate_limiter
            
            # Get timeout config from source
            timeout_config = ensure_dict(source_cfg.get('timeout_config', {}))
            timeout_seconds = timeout_config.get('timeout_seconds', 15)  # Default 15s
            
            # Get rate limit config and apply rate limiting
            rate_limit_config = ensure_dict(source_cfg.get('rate_limit_config', {}))
            max_rps = rate_limit_config.get('max_requests_per_second', 1.0)
            delay = rate_limit_config.get('delay_between_requests', 1.0)
            
            limiter = get_rate_limiter(max_requests_per_second=max_rps, delay_between_requests=delay)
            limiter.wait_if_needed(source_url)
            
            # Get retry config from source
            retry_config = ensure_dict(source_cfg.get('retry_config', {}))
            max_attempts = retry_config.get('max_attempts', 3)
            backoff_multiplier = retry_config.get('backoff_multiplier', 2.0)
            initial_delay = retry_config.get('initial_delay', 1.0)
            
            # Get custom headers from source config if provided
            default_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            custom_headers = ensure_dict(source_cfg.get('custom_headers', {}))
            headers = {**default_headers, **custom_headers}  # Custom headers override defaults
            
            try:
                response = retry_request(
                    requests.get,
                    max_attempts=max_attempts,
                    backoff_multiplier=backoff_multiplier,
                    initial_delay=initial_delay,
                    url=source_url,
                    timeout=timeout_seconds,
                    headers=headers,
                    allow_redirects=True
                )
                html = response.text
                diagnostics['status_code'] = response.status_code
                diagnostics['final_url'] = response.url
                diagnostics['retry_success'] = True
            except PermanentError as e:
                diagnostics['error'] = f"Permanent error: {e}"
                diagnostics['error_type'] = 'permanent'
                diagnostics['retry_attempts'] = 1  # Only one attempt for permanent errors
                return [], None, diagnostics
            except RetryableError as e:
                diagnostics['error'] = f"Retryable error after retries: {e}"
                diagnostics['error_type'] = 'retryable'
                diagnostics['retry_attempts'] = max_attempts
                diagnostics['retry_success'] = False
                return [], None, diagnostics
            
            detail_fetch = ensure_dict(source_cfg.get('detail_fetch'))
            if detail_fetch.get('enabled', False):
                from adapters.html_list import extract_events_with_detail_fetch
                events, stats = extract_events_with_detail_fetch(html, source_cfg)
            else:
                from adapters.html_list import extract_events as extract_html_list
                events, stats = extract_html_list(html, source_cfg, return_stats=True)
            
            raw_events = _convert_to_event_raw(events, source_cfg.get('id', ''))
            extraction_stats = stats
            
            # Check for JS-rendered page and try Playwright fallback if needed
            if len(raw_events) == 0 and len(html) > 10000:
                html_lower = html.lower()
                js_indicators = [
                    'enable javascript', 'javascript required', 'please enable javascript',
                    'noscript', 'react-root', 'ng-app', 'data-reactroot'
                ]
                js_detected = any(indicator in html_lower for indicator in js_indicators)
                
                if js_detected:
                    soup = BeautifulSoup(html, 'html.parser')
                    selectors = ensure_dict(source_cfg.get('selectors_json'))
                    potential_items = soup.select(selectors.get('item_selector', 'article, .card, .item'))
                    if len(potential_items) == 0:
                        diagnostics['is_js_rendered'] = True
                        diagnostics['js_detection'] = 'auto_detected'
                        diagnostics['suggested_adapter_type'] = 'playwright'  # Suggest switching to Playwright
                        
                        # Try Playwright as fallback (if available)
                        try:
                            from adapters.playwright_adapter import PLAYWRIGHT_AVAILABLE, extract_events_playwright
                            if PLAYWRIGHT_AVAILABLE:
                                diagnostics['playwright_fallback_attempted'] = True
                                playwright_events, playwright_stats = extract_events_playwright(
                                    source_cfg, return_stats=True
                                )
                                if playwright_events:
                                    raw_events = _convert_to_event_raw(playwright_events, source_cfg.get('id', ''))
                                    extraction_stats = playwright_stats
                                    diagnostics['fallback_method'] = 'playwright'
                                    diagnostics['fallback_success'] = True
                                    diagnostics['playwright_fallback_success'] = True
                                    diagnostics['method_used'] = 'playwright_fallback'
                                else:
                                    diagnostics['fallback_method'] = 'playwright'
                                    diagnostics['fallback_success'] = False
                                    diagnostics['playwright_fallback_success'] = False
                            else:
                                diagnostics['playwright_fallback_attempted'] = False
                                diagnostics['playwright_not_available'] = True
                        except Exception as e:
                            diagnostics['fallback_error'] = str(e)
                            diagnostics['playwright_fallback_error'] = str(e)
                            diagnostics['fallback_method'] = 'playwright'
                            diagnostics['fallback_success'] = False
                            diagnostics['playwright_fallback_success'] = False
        
        elif adapter_type == 'playwright':
            from adapters.playwright_adapter import extract_events_playwright
            events, stats = extract_events_playwright(source_cfg, return_stats=True)
            raw_events = _convert_to_event_raw(events, source_cfg.get('id', ''))
            extraction_stats = stats
            # Note: HTML is rendered by Playwright, no need to fetch separately
            
            # Check if Playwright was available
            if not PLAYWRIGHT_AVAILABLE:
                diagnostics['error'] = 'Playwright not installed'
                diagnostics['error_type'] = 'playwright_not_available'
        
        elif adapter_type == 'third_party_calendar':
            from adapters.third_party_calendar import extract_events as extract_third_party
            calendar_config = ensure_dict(source_cfg.get('calendar_config', {}))
            events, stats = extract_third_party(calendar_config, source_cfg, return_stats=True)
            # Third-party calendar adapter returns EventRaw directly
            raw_events = events
            extraction_stats = stats
        
        elif adapter_type == 'email':
            from adapters.email_event import extract_events as extract_email
            # Email adapter expects eml_path in source_config
            eml_path = source_cfg.get('eml_path')
            if eml_path:
                from pathlib import Path
                eml_path = Path(eml_path)
                events = extract_email(eml_path, source_cfg)
                raw_events = events
                extraction_stats = {'raw': len(events), 'kept': len(events), 'rejected': {}}
            else:
                raw_events = []
                extraction_stats = {'raw': 0, 'kept': 0, 'rejected': {}}
        
        else:
            diagnostics['error'] = f"Unknown adapter type: {adapter_type}"
            return [], None, diagnostics
            
    except requests.RequestException as e:
        status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        diagnostics['status_code'] = status_code
        diagnostics['error'] = f"Request error: {str(e)}"
        diagnostics['error_type'] = type(e).__name__
        return [], None, diagnostics
    except Exception as e:
        diagnostics['error'] = f"Error: {str(e)}"
        diagnostics['error_type'] = type(e).__name__
        return [], None, diagnostics
    
    return raw_events, extraction_stats, diagnostics


def _convert_to_event_raw(events: List[Dict], source_id: str) -> List[Dict]:
    """
    Convert adapter output to EventRaw format.
    
    Adapters currently return enriched events. We need to extract just the raw data.
    This is a temporary bridge until adapters are updated to return EventRaw directly.
    """
    raw_events = []
    for event in events:
        raw = {
            'source_id': source_id,
            'event_name': event.get('event_name', ''),
            'link': event.get('link', ''),
        }
        
        # Date: prefer date_time, fallback to date_text
        if 'date_time' in event:
            raw['date_time'] = event.get('date_time')
        if 'raw_date_text' in event:
            raw['date_text'] = event.get('raw_date_text')
        elif 'date_time' not in event:
            # If no date_time, try to extract from any date field
            raw['date_text'] = ''
        
        # Optional fields
        if 'location' in event:
            raw['location'] = event.get('location')
        if 'speakers' in event:
            raw['speakers'] = event.get('speakers')
        if 'tags' in event:
            raw['tags'] = event.get('tags', [])
        if 'extra' in event:
            raw['extra'] = event.get('extra')
        
        raw_events.append(raw)
    
    return raw_events
