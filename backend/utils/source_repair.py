"""
Source repair playbooks.

Each playbook analyzes a source's degradation and returns:
- patch: dict of config changes to apply to sources.json
- repair_actions: list of scripts/commands to run
- why: explanation string
"""
from typing import Dict, List, Optional, Tuple
from pathlib import Path


def playbook_dates_on_detail(
    source: Dict,
    evidence: Dict,
    degradation_class: str
) -> Tuple[Dict, List[str], str]:
    """
    Playbook A: Enable/enhance detail enrichment for date extraction.
    
    Trigger: kept_count > 0 but dated_ratio low, OR detail_enrich previously improved dated_ratio.
    """
    patch = {}
    actions = []
    why = "Low dated_ratio suggests dates are on detail pages, not list page."
    
    # Check if detail_fetch already exists
    current_detail = source.get('detail_fetch', {})
    if not current_detail.get('enabled', False):
        # Enable detail_fetch
        patch['detail_fetch'] = {
            'enabled': True,
            'max': 15,  # Tuned for date extraction
            'stop_after_first_valid': True,
            'harvest_ics': True,
            'date_selector': 'script[type="application/ld+json"], time[datetime], meta[itemprop="startDate"], meta[property*="date"], .date, .event-date, [class*="date"]',
            'date_attr': 'datetime',
            'priority_order': ['ics', 'jsonld', 'time_datetime', 'meta_itemprop', 'meta_property', 'class_date']
        }
        why += " Enabling detail_fetch with ICS harvest priority."
    else:
        # Enhance existing config
        enhanced = current_detail.copy()
        enhanced['harvest_ics'] = True
        enhanced['max'] = max(enhanced.get('max', 10), 15)  # Increase if too low
        if 'priority_order' not in enhanced:
            enhanced['priority_order'] = ['ics', 'jsonld', 'time_datetime', 'meta_itemprop', 'meta_property', 'class_date']
        patch['detail_fetch'] = enhanced
        why += " Enhancing existing detail_fetch config."
    
    # Recommend running detail enrichment validator
    actions.append(
        f"Run detail enrichment validator: "
        f"python -m backend.scripts.promote_partial_sources --sources backend/sources.json "
        f"--only-status partial_needs_detail --max-sources 1 --sampling-mode date_hint_priority "
        f"--min-sample-ok 8 --max-detail 15"
    )
    
    return patch, actions, why


def playbook_ics_backed(
    source: Dict,
    evidence: Dict,
    degradation_class: str
) -> Tuple[Dict, List[str], str]:
    """
    Playbook B: Enable ICS calendar harvesting.
    
    Trigger: detail enrichment finds ICS links frequently, OR ICS harvester reports high hit rate.
    """
    patch = {}
    actions = []
    why = "ICS links detected on detail pages - prefer ICS harvesting."
    
    detail_fetch = source.get('detail_fetch', {})
    if not detail_fetch.get('enabled', False):
        patch['detail_fetch'] = {
            'enabled': True,
            'max': 20,
            'harvest_ics': True,
            'stop_after_first_valid': True
        }
    else:
        enhanced = detail_fetch.copy()
        enhanced['harvest_ics'] = True
        patch['detail_fetch'] = enhanced
    
    # Note: ICS harvester is already integrated in detail_enrich.py
    # Just ensure harvest_ics flag is set
    actions.append("ICS harvesting will be used automatically when detail_fetch.harvest_ics=true")
    
    return patch, actions, why


def playbook_embedded_json(
    source: Dict,
    evidence: Dict,
    degradation_class: str
) -> Tuple[Dict, List[str], str]:
    """
    Playbook C: Enable embedded JSON extraction (Next.js / script JSON).
    
    Trigger: JS data detector finds structured JSON, OR HTML is sparse but has __NEXT_DATA__.
    """
    patch = {}
    actions = []
    why = "Structured JSON detected in page - enable embedded JSON extraction."
    
    # Add extract_embedded_json flag (if adapter supports it)
    # For now, this is handled by structured_metadata_extractor, but we can add a flag
    # to prioritize it
    detail_fetch = source.get('detail_fetch', {})
    if detail_fetch.get('enabled'):
        enhanced = detail_fetch.copy()
        # Ensure JSON-LD is in priority order
        if 'priority_order' in enhanced:
            if 'jsonld' not in enhanced['priority_order']:
                enhanced['priority_order'].insert(0, 'jsonld')
        else:
            enhanced['priority_order'] = ['jsonld', 'ics', 'time_datetime', 'meta_itemprop']
        patch['detail_fetch'] = enhanced
    else:
        # Enable detail_fetch with JSON-LD priority
        patch['detail_fetch'] = {
            'enabled': True,
            'max': 15,
            'priority_order': ['jsonld', 'ics', 'time_datetime']
        }
    
    actions.append("JSON-LD extraction is handled by structured_metadata_extractor (already integrated)")
    
    return patch, actions, why


def playbook_selector_drift(
    source: Dict,
    evidence: Dict,
    degradation_class: str
) -> Tuple[Dict, List[str], str]:
    """
    Playbook D: Regenerate selectors using autoparser.
    
    Trigger: Prior snapshots show good performance then sudden drop, HTML still accessible.
    """
    patch = {}
    actions = []
    why = "Selector drift detected - HTML structure likely changed, regenerate selectors."
    
    url = source.get('url', '')
    if not url:
        return patch, actions, "No URL available for selector regeneration"
    
    # Action: run autoparser
    actions.append(
        f"Run autoparser: python -m backend.scripts.test_autoparser_on_sources "
        f"--source {source.get('id')} --apply"
    )
    
    # Note: autoparser will update selectors_json in sources.json
    # We don't pre-populate patch here - let autoparser write it
    
    why += f" Autoparser will regenerate selectors for {url}"
    
    return patch, actions, why


def playbook_rate_limited(
    source: Dict,
    evidence: Dict,
    degradation_class: str
) -> Tuple[Dict, List[str], str]:
    """
    Playbook E: Handle rate-limited / transient network issues.
    
    Trigger: error_class indicates transient network (timeouts, 429, 503).
    """
    patch = {}
    actions = []
    why = "Transient network errors detected - adjust crawl budget and retry strategy."
    
    # Note: host_throttle.py already handles per-host backoff
    # We can add a comment or metadata, but no config patch needed for selectors
    
    # Recommend using cache-only mode for next run
    actions.append(
        f"Next scrape run should use --use-cache-only flag to avoid rate limits"
    )
    actions.append(
        f"Consider reducing --max-new-fetches for this source's host"
    )
    
    # Store recommendation in comment (not a config field, but visible)
    current_comment = source.get('comment', '')
    if 'rate_limited' not in current_comment.lower():
        patch['comment'] = (current_comment + " [Rate-limited: use cache-only mode]").strip()
    
    why += " No selector changes needed - adjust crawl budget instead."
    
    return patch, actions, why


def playbook_hard_block(
    source: Dict,
    evidence: Dict,
    degradation_class: str
) -> Tuple[Dict, List[str], str]:
    """
    Playbook F: Handle hard block / login required.
    
    Trigger: Repeated 403 bot wall or 401 login.
    """
    patch = {}
    actions = []
    why = "Hard block detected (403/401) - mark source as deferred/inactive."
    
    # Mark as inactive
    patch['active'] = 0
    
    # Set failure_class if not already set
    if not source.get('failure_class'):
        patch['failure_class'] = 'blocked_hard' if '403' in str(evidence.get('error_evidence', '')) else 'gated_login'
    
    # Update comment
    current_comment = source.get('comment', '')
    block_reason = 'Bot wall (403)' if '403' in str(evidence.get('error_evidence', '')) else 'Login required (401)'
    patch['comment'] = (current_comment + f" [Blocked: {block_reason}]").strip()
    
    actions.append("Source marked inactive - consider alternative acquisition method (email/third-party)")
    
    why += f" Source deactivated due to {block_reason}."
    
    return patch, actions, why


# Playbook registry
PLAYBOOKS = {
    'dates_on_detail': playbook_dates_on_detail,
    'ics_backed': playbook_ics_backed,
    'embedded_json': playbook_embedded_json,
    'selector_drift': playbook_selector_drift,
    'rate_limited': playbook_rate_limited,
    'hard_block': playbook_hard_block
}


def select_playbook(
    source: Dict,
    degradation_result: Dict,
    evidence: Optional[Dict] = None
) -> Tuple[Dict, List[str], str]:
    """
    Select and execute appropriate playbook based on degradation result.
    
    Returns:
        (patch, repair_actions, why)
    """
    if not degradation_result.get('degraded'):
        return {}, [], "No degradation detected - no repair needed"
    
    playbook_name = degradation_result.get('recommended_playbook')
    if not playbook_name:
        return {}, [], "Degradation detected but no playbook recommended"
    
    playbook_func = PLAYBOOKS.get(playbook_name)
    if not playbook_func:
        return {}, [], f"Unknown playbook: {playbook_name}"
    
    if evidence is None:
        evidence = {}
    
    try:
        patch, actions, why = playbook_func(source, evidence, degradation_result.get('degradation_class'))
        return patch, actions, why
    except Exception as e:
        return {}, [], f"Playbook {playbook_name} failed: {str(e)}"
