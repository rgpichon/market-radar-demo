#!/usr/bin/env python3
"""
Fix duplicate source IDs by making them unique based on URL.

Usage:
    python fix_duplicate_source_ids.py --apply
"""
import sys
import json
import hashlib
from pathlib import Path
from collections import defaultdict

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

SOURCES_FILE = backend_dir / "sources.json"


def make_unique_id(base_id: str, url: str, existing_ids: set) -> str:
    """Make a unique ID by adding URL hash."""
    import hashlib
    url_path = url.split('?')[0].split('#')[0]
    url_hash = hashlib.md5(url_path.encode()).hexdigest()[:6]
    unique_id = f"{base_id}_{url_hash}"
    
    counter = 1
    original = unique_id
    while unique_id in existing_ids:
        unique_id = f"{original}_{counter}"
        counter += 1
    
    return unique_id


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fix duplicate source IDs')
    parser.add_argument('--apply', action='store_true', help='Apply changes')
    args = parser.parse_args()
    
    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)
    
    # Find duplicates
    id_groups = defaultdict(list)
    for i, source in enumerate(sources):
        source_id = source.get('id', '')
        id_groups[source_id].append((i, source))
    
    duplicates = {k: v for k, v in id_groups.items() if len(v) > 1}
    
    print(f"=== Fix Duplicate Source IDs ===")
    print(f"Total sources: {len(sources)}")
    print(f"Duplicate IDs: {len(duplicates)}")
    print()
    
    if not duplicates:
        print("No duplicates found!")
        return
    
    # Get all existing IDs
    all_ids = {s.get('id') for s in sources}
    
    # Fix duplicates
    fixed_count = 0
    for dup_id, instances in duplicates.items():
        print(f"Fixing duplicate: {dup_id} ({len(instances)} instances)")
        
        # Keep first one as-is, fix the rest
        for idx, (i, source) in enumerate(instances):
            if idx == 0:
                print(f"  Keeping: {source.get('firm_name')} - {source.get('url', '')[:60]}")
                continue
            
            old_id = source.get('id')
            url = source.get('url', '')
            new_id = make_unique_id(old_id, url, all_ids)
            
            print(f"  Changing: {source.get('firm_name')}")
            print(f"    {old_id} → {new_id}")
            print(f"    URL: {url[:60]}")
            
            if args.apply:
                sources[i]['id'] = new_id
                all_ids.add(new_id)
                fixed_count += 1
        print()
    
    if args.apply and fixed_count > 0:
        with open(SOURCES_FILE, 'w') as f:
            json.dump(sources, f, indent=2)
        print(f"✓ Fixed {fixed_count} duplicate IDs")
        print(f"  Run sync_sources_from_json() to update database")
    elif not args.apply:
        print(f"[DRY RUN] Would fix {sum(len(v)-1 for v in duplicates.values())} duplicate IDs")
        print(f"Use --apply to make changes")


if __name__ == '__main__':
    main()
