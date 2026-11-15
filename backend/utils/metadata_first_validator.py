"""
Metadata-First Validator - Integrates all phases

This is the main entry point for HTML source validation that follows
the priority order: structured metadata → detail recovery → JS data → selectors.
"""
import json
from typing import Dict, Optional
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from .structured_metadata_extractor import extract_structured_events, is_future_event
from .ics_harvester import find_ics_links, harvest_ics_from_detail_page
from .js_data_detector import detect_js_data
from .html_autoparser import parse_html_autoparser


def validate_html_source_metadata_first(url: str, firm_name: str = "Unknown") -> Dict:
    """
    Validate HTML source using metadata-first approach.
    
    Returns validation result with clear classification.
    """
    result = {
        'url': url,
        'status': 'unknown',
        'validation_method': None,
        'events_found': 0,
        'future_events': 0,
        'dated_events': 0,
        'evidence': {},
        'recommended_next_action': None,
        'selectors_json': {},
        'detail_fetch_config': None
    }
    
    try:
        # Fetch HTML
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            result['status'] = 'failed'
            result['validation_method'] = 'http_error'
            result['recommended_next_action'] = f'HTTP {response.status_code} - check URL'
            return result
        
        html = response.text
        base_url = response.url
        
        # ===== PHASE 1: Structured Metadata Extraction =====
        structured_result = extract_structured_events(html, base_url)
        if structured_result['count'] > 0:
            events = structured_result['events']
            future_count = sum(1 for e in events if is_future_event(e))
            dated_count = sum(1 for e in events if e.get('date_iso'))
            
            result['status'] = 'validated_structured'
            result['validation_method'] = structured_result['source_type']
            result['events_found'] = len(events)
            result['future_events'] = future_count
            result['dated_events'] = dated_count
            result['evidence'] = {
                'structured_metadata': structured_result['evidence'],
                'sample_events': events[:5]  # First 5 for evidence
            }
            
            if future_count >= 3 and dated_count >= len(events) * 0.5:
                result['recommended_next_action'] = 'ready_to_onboard'
            else:
                result['recommended_next_action'] = 'structured_events_found_but_needs_review'
            
            return result
        
        # ===== PHASE 2: Detail Page Date Recovery & ICS Harvesting =====
        # Check if we can find events on list page (even without dates)
        # Then try detail pages for dates/ICS
        
        # First, try to find event links on list page
        soup = BeautifulSoup(html, 'html.parser')
        event_links = _find_event_links(soup, base_url)
        
        if len(event_links) >= 3:
            # Try detail pages for dates/ICS
            detail_results = _try_detail_pages_for_dates(event_links[:5], base_url)  # Sample 5
            
            if detail_results['dates_found'] > 0 or detail_results['ics_found']:
                result['status'] = 'validated_detail_recovered'
                result['validation_method'] = 'detail_fetch' + ('_ics' if detail_results['ics_found'] else '')
                result['events_found'] = len(event_links)
                result['dated_events'] = detail_results['dates_found']
                result['future_events'] = detail_results['future_count']
                result['evidence'] = {
                    'detail_page_samples': detail_results['samples'],
                    'ics_found': detail_results['ics_found']
                }
                result['detail_fetch_config'] = {
                    'enabled': True,
                    'max': 10,
                    'stop_after_first_valid': True,
                    'date_selector': 'script[type="application/ld+json"], time[datetime], meta[itemprop="startDate"], meta[property*="date"], .date, .event-date',
                    'date_attr': 'datetime',
                    'harvest_ics': True  # Enable ICS harvesting
                }
                result['recommended_next_action'] = 'ready_to_onboard_with_detail_fetch'
                return result
        
        # ===== PHASE 3: Hidden JSON/API/JS Data Detection =====
        js_result = detect_js_data(html, base_url)
        if js_result['found'] and js_result['events']:
            events = js_result['events']
            future_count = sum(1 for e in events if is_future_event(e))
            dated_count = sum(1 for e in events if e.get('date_iso'))
            
            result['status'] = 'validated_json_api'
            result['validation_method'] = js_result['source_type']
            result['events_found'] = len(events)
            result['future_events'] = future_count
            result['dated_events'] = dated_count
            result['evidence'] = js_result['evidence']
            result['recommended_next_action'] = 'treat_as_json_api_lane'
            return result
        
        # ===== PHASE 4: Selector-Based Autoparser (Fallback) =====
        autoparser_result = parse_html_autoparser(url, html, base_url)
        
        detected_mode = autoparser_result.get('detected_mode', 'no_events')
        sample_events = autoparser_result.get('sample_events', [])
        
        if detected_mode == 'gated_login':
            result['status'] = 'gated_login'
            result['validation_method'] = 'autoparser'
            result['recommended_next_action'] = 'skip_source'
            return result
        
        if detected_mode == 'js_rendered':
            result['status'] = 'js_rendered_blocked'
            result['validation_method'] = 'autoparser'
            result['recommended_next_action'] = 'try_playwright_or_skip'
            return result
        
        if detected_mode == 'no_events':
            result['status'] = 'no_events'
            result['validation_method'] = 'autoparser'
            result['recommended_next_action'] = 'skip_source'
            return result
        
        if detected_mode == 'detail_only':
            result['status'] = 'partial_needs_detail'
            result['validation_method'] = 'autoparser'
            result['events_found'] = len(sample_events)
            result['selectors_json'] = autoparser_result.get('selectors_json', {})
            result['detail_fetch_config'] = autoparser_result.get('detail_fetch_patch')
            result['recommended_next_action'] = 'enable_detail_fetch'
            return result
        
        if detected_mode in ['jsonld', 'microdata', 'dom_cluster']:
            future_count = sum(1 for e in sample_events if is_future_event(e))
            dated_count = sum(1 for e in sample_events if e.get('date_iso'))
            
            result['status'] = 'validated_selector'
            result['validation_method'] = detected_mode
            result['events_found'] = len(sample_events)
            result['future_events'] = future_count
            result['dated_events'] = dated_count
            result['selectors_json'] = autoparser_result.get('selectors_json', {})
            result['evidence'] = {
                'autoparser_tier': autoparser_result.get('tier'),
                'needs_refinement': autoparser_result.get('needs_refinement', False)
            }
            
            if future_count >= 3 and dated_count >= len(sample_events) * 0.5:
                result['recommended_next_action'] = 'ready_to_onboard'
            else:
                result['recommended_next_action'] = 'review_selectors'
            
            return result
        
        # Fallback: unknown
        result['status'] = 'no_events'
        result['validation_method'] = 'autoparser'
        result['recommended_next_action'] = 'skip_source'
        return result
        
    except Exception as e:
        result['status'] = 'failed'
        result['validation_method'] = 'error'
        result['recommended_next_action'] = f'Error: {str(e)}'
        return result


def _find_event_links(soup: BeautifulSoup, base_url: str) -> list:
    """Find event-like links on a list page."""
    event_links = []
    event_hints = ['/event', '/events', '/webinar', '/conference', '/seminar']
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if not href:
            continue
        
        href_lower = href.lower()
        if any(hint in href_lower for hint in event_hints):
            if not href.startswith('http'):
                href = urljoin(base_url, href)
            if href not in event_links:
                event_links.append(href)
    
    return event_links


def _try_detail_pages_for_dates(event_links: list, base_url: str) -> Dict:
    """Try to extract dates from detail pages (including ICS)."""
    dates_found = 0
    future_count = 0
    ics_found = False
    samples = []
    
    for link in event_links[:5]:  # Sample first 5
        try:
            response = requests.get(link, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }, allow_redirects=True)
            
            if response.status_code != 200:
                continue
            
            html = response.text
            
            # Try ICS first (most reliable)
            ics_result = harvest_ics_from_detail_page(html, link)
            if ics_result and ics_result['count'] > 0:
                ics_found = True
                event = ics_result['events'][0]
                if event.get('date_iso'):
                    dates_found += 1
                    if is_future_event(event):
                        future_count += 1
                    samples.append({
                        'url': link,
                        'method': 'ics',
                        'date': event.get('date_iso')
                    })
                continue
            
            # Try structured metadata on detail page
            structured = extract_structured_events(html, link)
            if structured['count'] > 0:
                event = structured['events'][0]
                if event.get('date_iso'):
                    dates_found += 1
                    if is_future_event(event):
                        future_count += 1
                    samples.append({
                        'url': link,
                        'method': 'structured',
                        'date': event.get('date_iso')
                    })
                    continue
            
        except Exception:
            continue
    
    return {
        'dates_found': dates_found,
        'future_count': future_count,
        'ics_found': ics_found,
        'samples': samples
    }
