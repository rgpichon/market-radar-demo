#!/usr/bin/env python3
"""
Test the metadata-first validation system on problematic sources.

Usage:
    python test_metadata_first_validation.py [--source-id ID] [--all-problematic]
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.metadata_first_validator import validate_html_source_metadata_first
from utils.structured_metadata_extractor import extract_structured_events
from utils.ics_harvester import find_ics_links, harvest_ics_from_detail_page
from utils.js_data_detector import detect_js_data
from urllib.parse import urljoin
import requests


# Problematic sources from test results
PROBLEMATIC_SOURCES = [
    {'id': 'aima_events', 'url': 'https://www.aima.org/events.html', 'name': 'AIMA'},
    {'id': 'cfa_society_global_events', 'url': 'https://www.cfainstitute.org/events', 'name': 'CFA Society Global'},
    {'id': 'cambridge_judge_business_school_events', 'url': 'https://www.jbs.cam.ac.uk/events/', 'name': 'Cambridge Judge Business School (HTML)'},
    {'id': 'bank_of_england_events', 'url': 'https://www.bankofengland.co.uk/news/events', 'name': 'Bank of England'},
    {'id': 'caia_association_events', 'url': 'https://caia.org/events', 'name': 'CAIA Association'},
    {'id': 'aqr_events', 'url': 'https://www.aqr.com/Insights/Events', 'name': 'AQR'},
    {'id': 'afme_events', 'url': 'https://www.afme.eu/events', 'name': 'AFME'},
    {'id': 'carnegie_events', 'url': 'https://carnegieendowment.org/events', 'name': 'Carnegie Endowment'},
]


def test_phase_1_structured_metadata(url: str) -> Dict:
    """Test Phase 1: Structured metadata extraction."""
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            return {'found': False, 'error': f'HTTP {response.status_code}'}
        
        result = extract_structured_events(response.text, response.url)
        return {
            'found': result['count'] > 0,
            'count': result['count'],
            'source_type': result['source_type'],
            'sample_events': result['events'][:3] if result['events'] else []
        }
    except Exception as e:
        return {'found': False, 'error': str(e)}


def test_phase_2_ics_harvesting(url: str) -> Dict:
    """Test Phase 2: ICS harvesting from detail pages."""
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            return {'found': False, 'error': f'HTTP {response.status_code}'}
        
        # Find ICS links on list page
        ics_links = find_ics_links(response.text, response.url)
        
        # Try detail pages
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        event_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if any(hint in href.lower() for hint in ['/event', '/events', '/webinar']):
                from urllib.parse import urljoin
                full_url = urljoin(response.url, href)
                if full_url not in event_links:
                    event_links.append(full_url)
        
        ics_found = False
        ics_samples = []
        
        # Try first 3 detail pages
        for detail_url in event_links[:3]:
            try:
                detail_response = requests.get(detail_url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }, allow_redirects=True)
                
                if detail_response.status_code == 200:
                    ics_result = harvest_ics_from_detail_page(detail_response.text, detail_url)
                    if ics_result and ics_result['count'] > 0:
                        ics_found = True
                        ics_samples.append({
                            'url': detail_url,
                            'events': ics_result['count']
                        })
            except Exception:
                continue
        
        return {
            'found': ics_found or len(ics_links) > 0,
            'ics_links_on_list': len(ics_links),
            'ics_found_on_details': ics_found,
            'samples': ics_samples
        }
    except Exception as e:
        return {'found': False, 'error': str(e)}


def test_phase_3_js_data(url: str) -> Dict:
    """Test Phase 3: JS data detection."""
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            return {'found': False, 'error': f'HTTP {response.status_code}'}
        
        result = detect_js_data(response.text, response.url)
        return {
            'found': result['found'],
            'source_type': result['source_type'],
            'events_found': len(result['events']),
            'evidence': result['evidence']
        }
    except Exception as e:
        return {'found': False, 'error': str(e)}


def test_full_validation(source: Dict) -> Dict:
    """Test full metadata-first validation."""
    url = source['url']
    name = source['name']
    
    print(f"\n{'='*70}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    print(f"{'='*70}")
    
    # Full validation
    validation_result = validate_html_source_metadata_first(url, name)
    
    # Phase-by-phase tests
    phase1 = test_phase_1_structured_metadata(url)
    phase2 = test_phase_2_ics_harvesting(url)
    phase3 = test_phase_3_js_data(url)
    
    return {
        'source': name,
        'url': url,
        'full_validation': validation_result,
        'phase1_structured': phase1,
        'phase2_ics': phase2,
        'phase3_js_data': phase3
    }


def main():
    parser = argparse.ArgumentParser(description='Test metadata-first validation')
    parser.add_argument('--source-id', type=str, help='Test specific source ID')
    parser.add_argument('--all-problematic', action='store_true', help='Test all problematic sources')
    parser.add_argument('--limit', type=int, default=10, help='Limit number of sources to test')
    args = parser.parse_args()
    
    sources_to_test = []
    
    if args.source_id:
        source = next((s for s in PROBLEMATIC_SOURCES if s['id'] == args.source_id), None)
        if source:
            sources_to_test = [source]
        else:
            print(f"Source {args.source_id} not found in problematic sources list")
            return 1
    elif args.all_problematic:
        sources_to_test = PROBLEMATIC_SOURCES[:args.limit]
    else:
        # Test first 3 by default
        sources_to_test = PROBLEMATIC_SOURCES[:3]
    
    print(f"=== Testing Metadata-First Validation on {len(sources_to_test)} Sources ===\n")
    
    results = []
    for source in sources_to_test:
        result = test_full_validation(source)
        results.append(result)
        
        # Print summary
        val = result['full_validation']
        print(f"\n📊 Validation Result:")
        print(f"  Status: {val['status']}")
        print(f"  Method: {val['validation_method']}")
        print(f"  Events: {val['events_found']} found, {val['future_events']} future, {val['dated_events']} dated")
        print(f"  Action: {val['recommended_next_action']}")
        
        # Phase results
        print(f"\n🔍 Phase Results:")
        print(f"  Phase 1 (Structured): {'✓' if result['phase1_structured'].get('found') else '✗'} "
              f"{result['phase1_structured'].get('count', 0)} events via {result['phase1_structured'].get('source_type', 'none')}")
        print(f"  Phase 2 (ICS): {'✓' if result['phase2_ics'].get('found') else '✗'} "
              f"{result['phase2_ics'].get('ics_links_on_list', 0)} links, {len(result['phase2_ics'].get('samples', []))} detail pages with ICS")
        print(f"  Phase 3 (JS Data): {'✓' if result['phase3_js_data'].get('found') else '✗'} "
              f"{result['phase3_js_data'].get('events_found', 0)} events via {result['phase3_js_data'].get('source_type', 'none')}")
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}\n")
    
    validated = [r for r in results if r['full_validation']['status'].startswith('validated')]
    partial = [r for r in results if r['full_validation']['status'] == 'partial_needs_detail']
    failed = [r for r in results if r['full_validation']['status'] in ['no_events', 'gated_login', 'js_rendered_blocked']]
    
    print(f"Total tested: {len(results)}")
    print(f"  ✓ Validated: {len(validated)}")
    print(f"  ⚠ Partial: {len(partial)}")
    print(f"  ✗ Failed: {len(failed)}")
    
    # Phase success rates
    phase1_success = sum(1 for r in results if r['phase1_structured'].get('found'))
    phase2_success = sum(1 for r in results if r['phase2_ics'].get('found'))
    phase3_success = sum(1 for r in results if r['phase3_js_data'].get('found'))
    
    print(f"\nPhase Success Rates:")
    print(f"  Phase 1 (Structured Metadata): {phase1_success}/{len(results)} ({phase1_success/len(results)*100:.1f}%)")
    print(f"  Phase 2 (ICS Harvesting): {phase2_success}/{len(results)} ({phase2_success/len(results)*100:.1f}%)")
    print(f"  Phase 3 (JS Data): {phase3_success}/{len(results)} ({phase3_success/len(results)*100:.1f}%)")
    
    # Validated sources
    if validated:
        print(f"\n✓ Validated Sources ({len(validated)}):")
        for r in validated:
            val = r['full_validation']
            print(f"  - {r['source']}: {val['events_found']} events via {val['validation_method']}")
    
    # Partial sources
    if partial:
        print(f"\n⚠ Partial Sources ({len(partial)}):")
        for r in partial:
            val = r['full_validation']
            print(f"  - {r['source']}: {val['events_found']} events, needs detail_fetch")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
