#!/usr/bin/env python3
"""
Find low-confidence sources that would benefit from selector_overrides.

Usage:
    python find_low_confidence_sources.py
"""
import sys
import json
from pathlib import Path
from typing import Dict, List

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.html_autoparser import parse_html_autoparser
import requests


SOURCES_FILE = backend_dir / "sources.json"


def analyze_source(source: Dict) -> Dict:
    """Analyze a source and return confidence metrics."""
    source_id = source.get('id', '')
    url = source.get('url', '')
    adapter_type = source.get('adapter_type', '')
    
    if adapter_type != 'html_list':
        return None
    
    # Check if already has selector_overrides
    has_overrides = bool(source.get('selector_overrides'))
    if has_overrides:
        return None  # Skip sources that already have overrides
    
    # Check if has selectors
    selectors = source.get('selectors_json', {})
    if not selectors.get('item_selector'):
        return None  # Skip sources without selectors
    
    try:
        # Fetch and run autoparser
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, allow_redirects=True)
        
        if response.status_code != 200:
            return None
        
        result = parse_html_autoparser(url, response.text, response.url)
        
        # Check if needs refinement
        if result.get('needs_refinement'):
            return {
                'source_id': source_id,
                'firm_name': source.get('firm_name', ''),
                'url': url,
                'event_likeness_ratio': result.get('event_likeness_ratio', 0.0),
                'detected_mode': result.get('detected_mode'),
                'tier': result.get('tier'),
                'sample_events_count': len(result.get('sample_events', [])),
                'current_selectors': selectors
            }
        
        return None
    except Exception:
        return None


def main():
    # Load sources
    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)
    
    # Analyze HTML sources
    low_confidence = []
    for source in sources:
        if source.get('active', 0) == 0:  # Only check inactive sources
            analysis = analyze_source(source)
            if analysis:
                low_confidence.append(analysis)
    
    # Sort by event_likeness_ratio (lowest first - most need help)
    low_confidence.sort(key=lambda x: x.get('event_likeness_ratio', 1.0))
    
    print(f"=== Low-Confidence Sources (Would Benefit from selector_overrides) ===\n")
    print(f"Found: {len(low_confidence)} sources\n")
    
    if low_confidence:
        print("Top 10 sources that would be fixed by 1 override:\n")
        for i, src in enumerate(low_confidence[:10], 1):
            print(f"{i}. {src['firm_name']} ({src['source_id']})")
            print(f"   URL: {src['url'][:70]}")
            print(f"   Event likeness: {src['event_likeness_ratio']:.1%}")
            print(f"   Mode: {src['detected_mode']}, Tier: {src['tier']}")
            print(f"   Sample events: {src['sample_events_count']}")
            print(f"   Current selectors: {src['current_selectors'].get('item_selector', 'N/A')}")
            print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
