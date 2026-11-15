"""
Reusable source operations for Wave-1 repair.

Extracts core functionality from existing scripts so wave1_repair_sources.py can import and call.
"""
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

from utils.pipeline import run_source_pipeline
from utils.html_autoparser import parse_html_autoparser
from utils.detail_enrich import validate_detail_enrichment


def test_source_and_return_metrics(
    source: Dict,
    dry_run: bool = False
) -> Dict:
    """
    Test a source and return metrics.
    
    Returns:
        {
            'kept_count': int,
            'dated_count': int,
            'undated_count': int,
            'dated_ratio': float,
            'future_count': int,
            'error_class': str | None,
            'error_evidence': str | None,
            'run_stats': Dict
        }
    """
    try:
        result = run_source_pipeline(source)
        run_stats = result.get('run_stats', {})
        
        return {
            'kept_count': run_stats.get('kept_count', 0),
            'dated_count': run_stats.get('dated_count', 0),
            'undated_count': run_stats.get('undated_count', 0),
            'dated_ratio': run_stats.get('dated_ratio', 0.0),
            'future_count': run_stats.get('future_count', 0),
            'error_class': None,  # Extract from diagnostics if available
            'error_evidence': None,
            'run_stats': run_stats
        }
    except Exception as e:
        return {
            'kept_count': 0,
            'dated_count': 0,
            'undated_count': 0,
            'dated_ratio': 0.0,
            'future_count': 0,
            'error_class': 'extraction_error',
            'error_evidence': str(e)[:200],
            'run_stats': {}
        }


def autoparser_generation(
    url: str,
    dry_run: bool = False,
    host_budget=None
) -> Dict:
    """
    Generate selectors using autoparser.
    
    Returns:
        {
            'success': bool,
            'selectors_json': Dict | None,
            'detail_fetch_patch': Dict | None,
            'sample_events': List[Dict],
            'tier': str,
            'detected_mode': str
        }
    """
    if dry_run:
        # In dry-run, try to use cache
        from utils.detail_enrich import fetch_with_cache
        fetched, accessibility = fetch_with_cache(url, dry_run=True, use_cache_only=True)
        if not fetched:
            return {
                'success': False,
                'selectors_json': None,
                'detail_fetch_patch': None,
                'sample_events': [],
                'tier': 'C',
                'detected_mode': 'no_events',
                'error': f'Cannot fetch in dry-run: {accessibility}'
            }
        html = fetched['html']
        final_url = fetched.get('final_url', url)
    else:
        # Check host budget
        if host_budget:
            try:
                sleep_seconds = host_budget.acquire(url)
                if sleep_seconds > 0:
                    import time
                    time.sleep(sleep_seconds)
            except Exception as e:
                return {
                    'success': False,
                    'selectors_json': None,
                    'detail_fetch_patch': None,
                    'sample_events': [],
                    'tier': 'C',
                    'detected_mode': 'no_events',
                    'error': f'Host budget exceeded: {str(e)}'
                }
        
        # Fetch HTML
        try:
            response = requests.get(
                url,
                timeout=(10, 20),
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                allow_redirects=True
            )
            response.raise_for_status()
            html = response.text
            final_url = response.url
            
            # Record result in host budget
            if host_budget:
                host_budget.record_result(url, status_code=response.status_code)
        except requests.exceptions.RequestException as e:
            status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            if host_budget:
                host_budget.record_result(url, status_code=status_code, error_class='deferred_transient_network')
            return {
                'success': False,
                'selectors_json': None,
                'detail_fetch_patch': None,
                'sample_events': [],
                'tier': 'C',
                'detected_mode': 'no_events',
                'error': f'Fetch failed: {str(e)}'
            }
    
    # Run autoparser
    try:
        result = parse_html_autoparser(url, html, final_url)
        return {
            'success': True,
            'selectors_json': result.get('selectors_json', {}),
            'detail_fetch_patch': result.get('detail_fetch_patch'),
            'sample_events': result.get('sample_events', []),
            'tier': result.get('tier', 'C'),
            'detected_mode': result.get('detected_mode', 'unknown')
        }
    except Exception as e:
        return {
            'success': False,
            'selectors_json': None,
            'detail_fetch_patch': None,
            'sample_events': [],
            'tier': 'C',
            'detected_mode': 'no_events',
            'error': f'Autoparser failed: {str(e)}'
        }


def detail_enrichment_validator(
    list_url: str,
    selectors_json: Dict,
    firm_name: str,
    max_detail: int = 25,
    dry_run: bool = False,
    use_cache_only: bool = False,
    max_new_fetches: Optional[int] = None,
    sampling_mode: str = 'adaptive',
    min_sample_ok: int = 8,
    host_budget=None
) -> Dict:
    """
    Run detail enrichment validator.
    
    Wrapper around validate_detail_enrichment with host_budget support.
    """
    # Note: validate_detail_enrichment already accepts host_budget parameter
    # but we need to wire it through fetch_with_retries
    # For now, pass it and let detail_enrich handle it
    return validate_detail_enrichment(
        list_url=list_url,
        selectors_json=selectors_json,
        firm_name=firm_name,
        max_detail=max_detail,
        dry_run=dry_run,
        use_cache_only=use_cache_only,
        max_new_fetches=max_new_fetches,
        sampling_mode=sampling_mode,
        min_sample_ok=min_sample_ok,
        host_budget=host_budget
    )


def apply_patch_to_source(source: Dict, patch: Dict) -> Dict:
    """
    Apply patch to source config (returns new dict, doesn't modify original).
    
    Only updates relevant fields (selectors, detail_fetch, flags).
    """
    updated = source.copy()
    
    for key, value in patch.items():
        if key == 'detail_fetch' and isinstance(value, dict):
            # Merge detail_fetch config
            current = updated.get('detail_fetch', {})
            if isinstance(current, dict):
                current = current.copy()
            else:
                current = {}
            current.update(value)
            updated['detail_fetch'] = current
        elif key == 'selectors_json' and isinstance(value, dict):
            # Merge selectors_json
            current = updated.get('selectors_json', {})
            if isinstance(current, dict):
                current = current.copy()
            else:
                current = {}
            current.update(value)
            updated['selectors_json'] = current
        else:
            updated[key] = value
    
    return updated


def meets_working_threshold(metrics: Dict) -> bool:
    """
    Check if metrics meet "working" threshold.
    
    Thresholds:
    - kept_count >= 3
    - dated_ratio >= 0.5
    - future_count >= 1
    """
    kept_count = metrics.get('kept_count', 0)
    dated_ratio = metrics.get('dated_ratio', 0.0)
    future_count = metrics.get('future_count', 0)
    
    return (
        kept_count >= 3 and
        dated_ratio >= 0.5 and
        future_count >= 1
    )
