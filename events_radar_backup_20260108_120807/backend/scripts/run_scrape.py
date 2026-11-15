#!/usr/bin/env python3
"""
CLI script to run scraping once.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from scrape_runner import run_scrape
from db import init_db

if __name__ == '__main__':
    init_db()
    print("Running scrape...")
    result = run_scrape()
    
    print(f"\n=== Scrape Summary ===")
    print(f"Total Sources: {result['total_sources']}")
    print(f"  ✓ Successful: {result['sources_ok']}")
    print(f"  ○ Zero Events: {result['sources_zero']}")
    print(f"  ✗ Failed: {result['sources_failed']}")
    
    # Show raw vs kept counts
    print(f"\n=== Filtering Summary ===")
    print(f"Raw items matched:    {result.get('total_raw', result['total_extracted'])}")
    print(f"Kept after filtering: {result['total_extracted']}")
    filtered_out = result.get('total_raw', result['total_extracted']) - result['total_extracted']
    if filtered_out > 0:
        print(f"Filtered out:         {filtered_out}")
    
    print(f"\n=== Database Updates ===")
    print(f"Inserted: {result['total_inserted']}")
    print(f"Updated: {result['total_updated']}")
    print(f"Notifications: {result['total_notifications']}")
    
    print(f"\n=== Per Source (Raw → Kept) ===")
    for sr in result['source_results']:
        status = "✓" if not sr['error'] and sr['events_found'] > 0 else "○" if not sr['error'] else "✗"
        raw = sr.get('raw_items', sr['events_found'])
        kept = sr['events_found']
        
        # Show raw → kept format
        filter_str = f"Raw {raw} → Kept {kept}" if raw != kept else f"Found {kept}"
        
        print(f"{status} {sr['firm_name']} ({sr['source_id']}): {filter_str}")
        
        # Show rejection reasons if any
        if sr.get('rejected_reasons'):
            reasons = sr['rejected_reasons']
            top_reasons = sorted(reasons.items(), key=lambda x: -x[1])[:3]
            reason_str = ", ".join([f"{r}: {c}" for r, c in top_reasons])
            print(f"    Rejected ({sum(reasons.values())}): {reason_str}")
        
        # Show error if any
        if sr['error']:
            print(f"    Error: {sr['error']}")
        
        # Show diagnostics if 0 events found (helps debugging)
        if sr['events_found'] == 0 and sr.get('diagnostics'):
            diag = sr['diagnostics']
            print(f"    Diagnostics: adapter={diag.get('adapter_type')}, "
                  f"status={diag.get('status_code', 'N/A')}, "
                  f"has_item_selector={diag.get('has_item_selector')}, "
                  f"html_length={diag.get('html_length')} bytes")
            if diag.get('item_selector'):
                print(f"      item_selector: {diag['item_selector']}")
            if diag.get('is_js_rendered'):
                print(f"      ⚠️  Likely JS-rendered page")
