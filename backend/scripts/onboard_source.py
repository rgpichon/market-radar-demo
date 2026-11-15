#!/usr/bin/env python3
"""
Registry-driven source onboarding command.

This script validates and activates sources that are already in sources.json
or source_registry.json. It does NOT add new sources.

Usage:
    python onboard_source.py --source_id <source_id>
    python onboard_source.py --firm_name "Firm Name"
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from db import get_sources, init_db
from utils.source_registry import get_source_status, sync_registry
from utils.quality_gates import validate_source_before_add
from utils.pipeline import run_source_pipeline
from utils.lanes import infer_lane_from_source


def find_source_by_id_or_name(source_id: str = None, firm_name: str = None):
    """Find source by ID or firm name."""
    sources = get_sources(active_only=False)
    
    if source_id:
        for source in sources:
            if source.get('id') == source_id:
                return source
        return None
    
    if firm_name:
        # Try exact match first
        for source in sources:
            if source.get('firm_name', '').lower() == firm_name.lower():
                return source
        # Try partial match
        for source in sources:
            if firm_name.lower() in source.get('firm_name', '').lower():
                return source
    
    return None


def run_validation(source):
    """Run validation pipeline on source."""
    print(f"\n=== Running Validation ===")
    print(f"Source: {source.get('firm_name')} ({source.get('id')})")
    print(f"URL: {source.get('url')}")
    print(f"Lane: {infer_lane_from_source(source)}")
    
    # Run pipeline
    pipeline_result = run_source_pipeline(source)
    kept_events = pipeline_result['kept_events']
    run_stats = pipeline_result['run_stats']
    
    print(f"\nResults:")
    print(f"  Raw events: {run_stats.get('raw_count', 0)}")
    print(f"  Kept events: {len(kept_events)}")
    print(f"  Dated events: {run_stats.get('dated_count', 0)}")
    print(f"  Future events: {run_stats.get('future_count', 0)}")
    print(f"  Kept ratio: {run_stats.get('kept_ratio', 0.0):.2%}")
    print(f"  Dated ratio: {run_stats.get('dated_ratio', 0.0):.2%}")
    
    if run_stats.get('rejected'):
        print(f"\nRejections:")
        for reason, count in run_stats['rejected'].items():
            print(f"  {reason}: {count}")
    
    return {
        'kept_count': len(kept_events),
        'dated_count': run_stats.get('dated_count', 0),
        'future_count': run_stats.get('future_count', 0),
        'kept_ratio': run_stats.get('kept_ratio', 0.0),
        'dated_ratio': run_stats.get('dated_ratio', 0.0),
        'run_stats': run_stats
    }


def check_quality_gates(validation_result, source):
    """Check quality gates."""
    errors = []
    warnings = []
    
    kept_count = validation_result['kept_count']
    dated_ratio = validation_result['dated_ratio']
    future_count = validation_result['future_count']
    kept_ratio = validation_result['kept_ratio']
    lane = infer_lane_from_source(source)
    
    # Gate 1: >= 3 kept events
    if kept_count < 3:
        errors.append(f"Insufficient events: {kept_count} < 3")
    
    # Gate 2: >= 70% dated
    if dated_ratio < 0.70:
        errors.append(f"Low date coverage: {dated_ratio:.1%} < 70%")
    
    # Gate 3: >= 1 future event
    if future_count < 1:
        errors.append(f"No future events: {future_count} < 1")
    
    # Gate 4: kept_ratio not insane (>=0.2 unless rss/json_api)
    if lane not in ['rss', 'json_api']:
        if kept_ratio < 0.20:
            errors.append(f"Low kept ratio: {kept_ratio:.1%} < 20%")
    else:
        # RSS/JSON API can have lower kept ratio if events-only filter is strict
        if kept_ratio < 0.10:
            warnings.append(f"Very low kept ratio: {kept_ratio:.1%} < 10%")
    
    return errors, warnings


def activate_source(source_id: str):
    """Activate source in sources.json."""
    sources_file = backend_dir / "sources.json"
    
    with open(sources_file, 'r') as f:
        sources = json.load(f)
    
    updated = False
    for source in sources:
        if source.get('id') == source_id:
            if source.get('active', 0) != 1:
                source['active'] = 1
                updated = True
            break
    
    if updated:
        with open(sources_file, 'w') as f:
            json.dump(sources, f, indent=2)
        return True
    
    return False


def update_registry(source_id: str, passed: bool, errors: list, warnings: list):
    """Update source registry with validation results."""
    registry_file = backend_dir / "source_registry.json"
    
    if not registry_file.exists():
        sync_registry()
    
    with open(registry_file, 'r') as f:
        registry = json.load(f)
    
    if source_id not in registry:
        # Create entry
        source = find_source_by_id_or_name(source_id=source_id)
        if not source:
            return
        
        from utils.scraping_strategy import identify_sector
        from utils.lanes import infer_lane_from_source
        
        registry[source_id] = {
            'source_id': source_id,
            'firm_name': source.get('firm_name', ''),
            'sector': identify_sector(source.get('firm_name'), source.get('firm_type')),
            'lane': infer_lane_from_source(source),
            'acquisition_status': 'inactive',
            'validation_status': 'not_validated',
            'active': False,
            'last_checked': datetime.now(timezone.utc).isoformat(),
            'failure_reason': None,
            'next_action': None,
            'url': source.get('url', '')
        }
    
    entry = registry[source_id]
    entry['last_checked'] = datetime.now(timezone.utc).isoformat()
    
    if passed:
        entry['acquisition_status'] = 'active'
        entry['validation_status'] = 'validated'
        entry['active'] = True
        entry['failure_reason'] = None
        entry['next_action'] = None
    else:
        entry['acquisition_status'] = 'inactive'
        entry['validation_status'] = 'failed'
        entry['active'] = False
        entry['failure_reason'] = '; '.join(errors)
        if warnings:
            entry['failure_reason'] += ' (warnings: ' + '; '.join(warnings) + ')'
        entry['next_action'] = 'Fix validation issues and re-run onboarding'
    
    with open(registry_file, 'w') as f:
        json.dump(registry, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='Onboard a source with validation')
    parser.add_argument('--source_id', help='Source ID')
    parser.add_argument('--firm_name', help='Firm name')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (validate without activating)')
    parser.add_argument('--activate', action='store_true', help='Activate source if validation passes')
    parser.add_argument('--print-reasons', action='store_true', help='Print detailed failure reasons')
    
    args = parser.parse_args()
    
    if not args.source_id and not args.firm_name:
        parser.error("Must provide either --source_id or --firm_name")
    
    init_db()
    
    # Find source
    source = find_source_by_id_or_name(source_id=args.source_id, firm_name=args.firm_name)
    
    if not source:
        print(f"ERROR: Source not found")
        if args.source_id:
            print(f"  Searched for source_id: {args.source_id}")
        if args.firm_name:
            print(f"  Searched for firm_name: {args.firm_name}")
        print(f"\nAvailable sources:")
        sources = get_sources(active_only=False)
        for s in sources[:10]:
            print(f"  - {s.get('id')}: {s.get('firm_name')}")
        if len(sources) > 10:
            print(f"  ... and {len(sources) - 10} more")
        sys.exit(1)
    
    source_id = source.get('id')
    print(f"\n=== Source Onboarding: {source.get('firm_name')} ===")
    print(f"Source ID: {source_id}")
    
    # Check if already active
    if source.get('active', 0) == 1:
        print(f"\nSource is already active.")
        print(f"Re-running validation to confirm quality...")
    else:
        print(f"\nSource is currently inactive.")
        print(f"Running validation to determine if it should be activated...")
    
    # Run validation
    validation_result = run_validation(source)
    
    # Check quality gates (custom thresholds)
    errors, warnings = check_quality_gates(validation_result, source)
    
    # Also run formal quality gate validation
    from utils.quality_gates import validate_source_before_add
    formal_passed, formal_errors = validate_source_before_add(source)
    if not formal_passed:
        errors.extend(formal_errors)
    
    # Apply quality gate validation (skip duplicate check since source already exists)
    # We only check lane support and validation thresholds
    from utils.lanes import is_lane_supported, infer_lane_from_source
    lane = infer_lane_from_source(source)
    if not is_lane_supported(lane):
        errors.append(f"Lane '{lane}' is not currently supported")
    
    # Summary
    print(f"\n=== Quality Gates ===")
    if args.print_reasons or errors:
        if errors:
            print(f"FAILED:")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"PASSED")
    
    if warnings:
        print(f"\nWARNINGS:")
        for warning in warnings:
            print(f"  - {warning}")
    
    passed = len(errors) == 0
    
    if args.dry_run:
        print(f"\n[DRY RUN] Source would {'PASS' if passed else 'FAIL'} validation")
        if passed:
            print(f"[DRY RUN] Use --activate to actually activate the source")
        return 0 if passed else 1
    
    # Update registry
    update_registry(source_id, passed, errors, warnings)
    
    # Activate if passed AND --activate flag provided
    if passed and args.activate:
        was_active = source.get('active', 0) == 1
        activate_source(source_id)
        if not was_active:
            print(f"\nSource activated in sources.json")
        else:
            print(f"\nSource remains active (validation confirmed)")
        print(f"Registry updated: acquisition_status=active, validation_status=validated")
    elif passed and not args.activate:
        print(f"\nSource validated but not activated (use --activate to enable)")
        print(f"Registry updated: validation_status=validated")
    else:
        print(f"\nSource remains inactive")
        print(f"Registry updated: acquisition_status=inactive, validation_status=failed")
        print(f"\nNext action: Fix validation issues and re-run onboarding")
    
    # Final summary
    print(f"\n=== Summary ===")
    print(f"Source: {source.get('firm_name')} ({source_id})")
    print(f"Status: {'ACTIVE' if passed else 'INACTIVE'}")
    print(f"Kept events: {validation_result['kept_count']}")
    print(f"Future events: {validation_result['future_count']}")
    print(f"Dated ratio: {validation_result['dated_ratio']:.1%}")
    
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
