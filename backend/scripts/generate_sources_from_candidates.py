#!/usr/bin/env python3
"""
Generate sources.json entries from validated candidates.

Converts ready_to_onboard candidates into sources.json entries (inactive by default).

Usage:
    python generate_sources_from_candidates.py --priority p0 --dry-run
    python generate_sources_from_candidates.py --priority p0 --apply
"""
import sys
import json
import argparse
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List
from urllib.parse import urlparse

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

VALIDATED_FILE = backend_dir / "source_candidates_validated.json"
SOURCES_FILE = backend_dir / "sources.json"


def slugify(text: str) -> str:
    """Convert text to a valid source ID slug."""
    # Convert to lowercase
    text = text.lower()
    # Replace spaces and special chars with underscores
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '_', text)
    # Remove leading/trailing underscores
    text = text.strip('_')
    return text


def infer_default_tags(firm_type: str, firm_name: str) -> List[str]:
    """Infer default tags based on firm type and name."""
    tags = []
    
    firm_name_lower = firm_name.lower()
    
    # Firm type based tags
    if firm_type == 'Asset Manager':
        tags.append('Asset Management')
    elif firm_type == 'Hedge Fund':
        tags.append('Hedge Fund')
    elif firm_type == 'Association':
        tags.append('Association')
    elif firm_type == 'Academic':
        tags.append('Academic')
        tags.append('Research')
    elif firm_type == 'Think Tank':
        tags.append('Think Tank')
        tags.append('Policy')
    elif firm_type == 'Central Bank':
        tags.append('Central Bank')
        tags.append('Monetary Policy')
    elif firm_type == 'Regulator':
        tags.append('Regulatory')
    elif firm_type == 'Conference':
        tags.append('Conference')
    elif firm_type == 'Data Provider':
        tags.append('Data Provider')
    
    # Name-based tags
    if any(x in firm_name_lower for x in ['macro', 'economics', 'economic']):
        tags.append('Macro')
    if any(x in firm_name_lower for x in ['finance', 'financial', 'markets']):
        tags.append('Finance')
    if any(x in firm_name_lower for x in ['policy', 'public']):
        tags.append('Policy')
    
    # Remove duplicates while preserving order
    seen = set()
    unique_tags = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)
    
    return unique_tags if unique_tags else ['Events']


def generate_source_entry(firm_data: Dict, candidate: Dict) -> Dict:
    """Generate a sources.json entry from a validated candidate."""
    firm_name = firm_data.get('firm_name', '')
    firm_type = firm_data.get('firm_type', '')
    url = candidate.get('url', '')
    lane = candidate.get('lane', '')
    
    # Generate source ID with URL-based uniqueness for duplicates
    base_id = slugify(firm_name)
    if lane == 'rss':
        base_id = base_id + '_rss'
    elif lane == 'ics':
        base_id = base_id + '_ics'
    elif lane == 'html_list':
        base_id = base_id + '_events'
    else:
        base_id = base_id + '_' + slugify(lane)
    
    # For duplicate URLs or IDs, add a hash of the URL path
    existing_ids = {s.get('id') for s in load_existing_sources()}
    existing_urls = {s.get('url') for s in load_existing_sources()}
    
    source_id = base_id
    
    # If ID or URL already exists, make it unique
    if source_id in existing_ids or url in existing_urls:
        import hashlib
        # Create short hash from URL path
        url_path = url.split('?')[0].split('#')[0]  # Remove query/fragment
        url_hash = hashlib.md5(url_path.encode()).hexdigest()[:6]
        source_id = f"{base_id}_{url_hash}"
        
        # Still check for collisions
        counter = 1
        original_unique_id = source_id
        while source_id in existing_ids:
            source_id = f"{original_unique_id}_{counter}"
            counter += 1
    
    # Base entry
    entry = {
        'id': source_id,
        'firm_name': firm_name,
        'firm_type': firm_type,
        'url': url,
        'adapter_type': lane,
        'default_tags_json': infer_default_tags(firm_type, firm_name),
        'active': 0,  # Inactive by default
        'comment': f'Generated from bulk discovery on {datetime.now(timezone.utc).isoformat()}'
    }
    
    # Lane-specific configuration
    if lane == 'rss':
        entry['enforce_events_only'] = True
        # Add postprocess rules for events
        entry['postprocess_rules'] = {
            'require_url_contains_one_of': ['/event/', '/events/', '/webinar', '/conference']
        }
    elif lane == 'ics':
        entry['enforce_events_only'] = True
    elif lane == 'html_list':
        # Use selectors from validation if available
        selectors_json = candidate.get('selectors_json', {})
        if selectors_json:
            entry['selectors_json'] = selectors_json
        else:
            entry['selectors_json'] = {}
        
        # Apply selector_overrides if present (source-specific patching)
        # This allows manual refinement without changing autoparser logic
        selector_overrides = candidate.get('selector_overrides')
        if selector_overrides:
            entry['selector_overrides'] = selector_overrides
            entry['comment'] = f"{entry.get('comment', '')} - Selectors manually refined"
        
        entry['postprocess_rules'] = {
            'min_title_length': 12,
            'require_url_contains_one_of': ['/event/', '/events/', '/webinar', '/conference']
        }
        
        # Add detail_fetch if candidate needs it (detail_only is first-class)
        detail_fetch_patch = candidate.get('detail_fetch_patch')
        if detail_fetch_patch:
            entry['detail_fetch'] = detail_fetch_patch
            entry['comment'] = f"{entry.get('comment', '')} - Detail fetch enabled (dates on detail pages)"
    
    # Add failure metadata if candidate was deferred
    candidate_status = candidate.get('status', '')
    if candidate_status == 'deferred':
        failure_class = candidate.get('failure_class')
        if failure_class:
            entry['failure_class'] = failure_class
            entry['failure_evidence'] = candidate.get('evidence', {})
            entry['recommended_next_action'] = f'Fix {failure_class} issue and re-validate'
            entry['comment'] = f"{entry.get('comment', '')} - Status: deferred ({failure_class})"
    elif candidate_status == 'ready_to_onboard_with_detail_fetch':
        entry['comment'] = f"{entry.get('comment', '')} - Status: ready (events found, dates need detail fetch)"
    
    return entry


def load_existing_sources() -> List[Dict]:
    """Load existing sources.json."""
    if not SOURCES_FILE.exists():
        return []
    
    try:
        with open(SOURCES_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def main():
    parser = argparse.ArgumentParser(description='Generate sources from validated candidates')
    parser.add_argument('--priority', choices=['p0', 'p1', 'p2', 'all'], default='p0',
                       help='Priority filter')
    parser.add_argument('--apply', action='store_true',
                       help='Write to sources.json (default: dry-run)')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Dry run mode (default)')
    
    args = parser.parse_args()
    
    if args.apply:
        args.dry_run = False
    
    # Load validated candidates
    if not VALIDATED_FILE.exists():
        print(f"Error: {VALIDATED_FILE} not found. Run validate_candidates_bulk.py first.")
        sys.exit(1)
    
    with open(VALIDATED_FILE, 'r') as f:
        validated_data = json.load(f)
    
    firms = validated_data.get('firms', [])
    
    print(f"=== Generate Sources from Candidates ===")
    print(f"Priority: {args.priority}")
    print(f"Firms to process: {len(firms)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()
    
    # Load existing sources to check for duplicates
    existing_sources = load_existing_sources()
    existing_ids = {s.get('id') for s in existing_sources}
    existing_urls = {s.get('url') for s in existing_sources}
    
    new_entries = []
    skipped_duplicates = []
    
    for firm_data in firms:
        firm_name = firm_data.get('firm_name', '')
        candidates = firm_data.get('candidates_validated', [])
        
        # Process ready_to_onboard, ready_to_onboard_with_detail_fetch, and deferred candidates (deferred as inactive)
        ready_candidates = [
            c for c in candidates 
            if c.get('status') in ['ready_to_onboard', 'ready_to_onboard_with_detail_fetch']
        ]
        deferred_candidates = [c for c in candidates if c.get('status') == 'deferred']
        
        # Prioritize ready, but also include deferred (especially RSS/ICS)
        candidates_to_process = ready_candidates + deferred_candidates[:2]  # Top 2 deferred per firm
        
        if not candidates_to_process:
            continue
        
        print(f"\n=== Processing: {firm_name} ===")
        print(f"Ready candidates: {len(ready_candidates)}")
        
        for candidate in candidates_to_process:
            entry = generate_source_entry(firm_data, candidate)
            
            # Check for duplicates
            if entry['id'] in existing_ids:
                print(f"  ⚠ Skipping {entry['id']}: ID already exists")
                skipped_duplicates.append(entry['id'])
                continue
            
            if entry['url'] in existing_urls:
                print(f"  ⚠ Skipping {entry['id']}: URL already exists")
                skipped_duplicates.append(entry['url'])
                continue
            
            new_entries.append(entry)
            print(f"  ✓ Generated: {entry['id']} ({entry['adapter_type']})")
    
    # Summary
    print(f"\n=== Summary ===")
    print(f"New entries generated: {len(new_entries)}")
    print(f"Skipped duplicates: {len(skipped_duplicates)}")
    
    if new_entries:
        print(f"\nNew entries:")
        for entry in new_entries:
            print(f"  - {entry['id']}: {entry['firm_name']} ({entry['adapter_type']})")
            print(f"    URL: {entry['url']}")
            print(f"    Status: {'INACTIVE' if entry.get('active', 0) == 0 else 'ACTIVE'}")
    
    # Write to sources.json if --apply
    if not args.dry_run and new_entries:
        all_sources = existing_sources + new_entries
        
        # Sort by firm_name for readability
        all_sources.sort(key=lambda x: x.get('firm_name', ''))
        
        with open(SOURCES_FILE, 'w') as f:
            json.dump(all_sources, f, indent=2)
        
        print(f"\n✓ Added {len(new_entries)} sources to {SOURCES_FILE}")
        print(f"  Total sources: {len(all_sources)}")
        print(f"  All new sources are INACTIVE - run onboarding to activate")
    elif args.dry_run:
        print(f"\n[DRY RUN] Would add {len(new_entries)} sources to {SOURCES_FILE}")
        print(f"Use --apply to write changes")
    
    # Acceptance criteria
    if len(new_entries) >= 20:
        print(f"\n✓ Acceptance criteria met: {len(new_entries)} sources generated (target: 20+)")
    else:
        print(f"\n⚠ Acceptance criteria: {len(new_entries)} sources generated (target: 20+)")


if __name__ == '__main__':
    main()
