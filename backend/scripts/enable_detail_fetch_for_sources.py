#!/usr/bin/env python3
"""
Enable detail_fetch for sources that have events but 0% dated ratio.

Usage:
    python enable_detail_fetch_for_sources.py [--dry-run]
"""
import sys
import json
import argparse
from pathlib import Path

backend_dir = Path(__file__).parent.parent
SOURCES_FILE = backend_dir / "sources.json"

# Sources that need detail_fetch (from test results)
SOURCES_NEEDING_DETAIL_FETCH = [
    'afme_events',  # Already has detail_fetch for participants, but may need date extraction
    'aima_events',
    'cfa_society_global_events',
    'cambridge_judge_business_school_events',  # HTML version
    'carnegie_events',
    'ecb_conferences'  # ECB conferences (note: id is ecb_conferences, not ecb_events)
]

DETAIL_FETCH_TEMPLATE = {
    "enabled": True,
    "max": 10,
    "stop_after_first_valid": True,
    "date_selector": "script[type=\"application/ld+json\"], time[datetime], meta[itemprop=\"startDate\"], meta[property*=\"date\"], .date, .event-date, [class*=\"date\"]",
    "date_attr": "datetime",
    "priority_order": ["jsonld", "time_datetime", "meta_itemprop", "meta_property", "class_date"]
}


def enable_detail_fetch(sources: list, dry_run: bool = False) -> int:
    """Enable detail_fetch for sources that need it."""
    updated = 0
    
    for source in sources:
        source_id = source.get('id', '')
        if source_id not in SOURCES_NEEDING_DETAIL_FETCH:
            continue
        
        # Skip if already has detail_fetch enabled
        existing_detail_fetch = source.get('detail_fetch', {})
        if existing_detail_fetch.get('enabled', False):
            print(f"  ⊘ {source_id}: Already has detail_fetch enabled")
            continue
        
        # Add detail_fetch
        if not dry_run:
            source['detail_fetch'] = DETAIL_FETCH_TEMPLATE.copy()
            # Update comment
            comment = source.get('comment', '')
            if 'detail_fetch' not in comment.lower():
                source['comment'] = f"{comment} - detail_fetch enabled for date extraction".strip()
        
        updated += 1
        status = "[DRY-RUN] " if dry_run else ""
        print(f"  {status}✓ {source_id}: detail_fetch enabled")
    
    return updated


def main():
    parser = argparse.ArgumentParser(description='Enable detail_fetch for sources with 0% dated ratio')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without saving')
    args = parser.parse_args()
    
    # Load sources
    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)
    
    print(f"=== Enabling detail_fetch for {len(SOURCES_NEEDING_DETAIL_FETCH)} Sources ===\n")
    if args.dry_run:
        print("[DRY-RUN MODE - No changes will be saved]\n")
    
    updated = enable_detail_fetch(sources, dry_run=args.dry_run)
    
    if not args.dry_run and updated > 0:
        # Save updated sources
        with open(SOURCES_FILE, 'w') as f:
            json.dump(sources, f, indent=2)
        print(f"\n✓ Updated {updated} sources in {SOURCES_FILE}")
    elif args.dry_run:
        print(f"\n[DRY-RUN] Would update {updated} sources")
    else:
        print(f"\n⊘ No sources needed updates")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
