#!/usr/bin/env python3
"""
Batch onboarding script with strict guardrails.

Prioritizes ICS/RSS sources, produces ranked ready queue + failure breakdown,
updates sources/registry with provenance, and verifies scrape + UI event counts.

Usage:
    python batch_onboard_sources.py --priority p0 --dry-run
    python batch_onboard_sources.py --priority p0 --apply
"""
import sys
import json
import argparse
import subprocess
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from collections import Counter, defaultdict

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from db import get_sources, init_db
from utils.source_registry import sync_registry, load_registry
from utils.pipeline import run_source_pipeline
from utils.lanes import infer_lane_from_source, is_lane_supported
from utils.quality_gates import validate_source_before_add


SOURCES_FILE = backend_dir / "sources.json"
REGISTRY_FILE = backend_dir / "source_registry.json"
QUEUE_FILE = backend_dir / "onboarding_queue.json"
REPORT_FILE = backend_dir / "onboarding_report.json"


# Lane priority (higher = better)
LANE_PRIORITY = {
    'ics': 100,
    'rss': 90,
    'json_api': 80,
    'html_list': 50,
    'playwright': 10
}


def load_sources() -> List[Dict]:
    """Load sources.json."""
    if not SOURCES_FILE.exists():
        return []
    try:
        with open(SOURCES_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_sources(sources: List[Dict]):
    """Save sources.json."""
    with open(SOURCES_FILE, 'w') as f:
        json.dump(sources, f, indent=2)


def get_bulk_discovered_sources(sources: List[Dict]) -> List[Dict]:
    """Get sources that were generated from bulk discovery."""
    return [
        s for s in sources
        if s.get('active', 0) == 0 and (
            'Generated from bulk discovery' in s.get('comment', '') or
            s.get('onboarded_at') is None  # New sources without onboarded_at
        )
    ]


def rank_source(source: Dict) -> Tuple[float, Dict]:
    """Rank a source for onboarding priority. Returns (score, metadata)."""
    score = 0.0
    metadata = {
        'lane': infer_lane_from_source(source),
        'firm_name': source.get('firm_name', ''),
        'firm_type': source.get('firm_type', ''),
        'url': source.get('url', ''),
        'reasons': []
    }
    
    lane = metadata['lane']
    
    # Lane priority (ICS/RSS first)
    lane_priority = LANE_PRIORITY.get(lane, 0)
    score += lane_priority
    metadata['reasons'].append(f"Lane priority: {lane_priority} ({lane})")
    
    # Check if lane is supported
    if is_lane_supported(lane):
        score += 20
        metadata['reasons'].append("Lane is supported")
    else:
        score -= 50
        metadata['reasons'].append("Lane NOT supported")
    
    # Firm type bonus (non-bank categories preferred)
    firm_type = metadata['firm_type']
    if firm_type in ['Asset Manager', 'Hedge Fund', 'Association', 'Academic', 'Think Tank']:
        score += 10
        metadata['reasons'].append(f"Preferred firm type: {firm_type}")
    
    # Check for failure_class (penalize)
    failure_class = source.get('failure_class')
    if failure_class:
        if failure_class in ['press_release_only', 'js_rendered', 'gated_login']:
            score -= 100  # Hard stop
            metadata['reasons'].append(f"HARD STOP: {failure_class}")
        else:
            score -= 20
            metadata['reasons'].append(f"Has failure_class: {failure_class}")
    
    # URL quality check
    url = metadata['url']
    if any(x in url.lower() for x in ['/event', '/events', '/webinar', '/conference']):
        score += 5
        metadata['reasons'].append("URL contains event patterns")
    
    metadata['score'] = score
    return score, metadata


def validate_source_strict(source: Dict) -> Tuple[bool, List[str], Dict]:
    """Strict validation of a source. Returns (passed, errors, stats)."""
    errors = []
    stats = {}
    
    # Check quality gates
    passed, gate_errors = validate_source_before_add(source)
    if not passed:
        errors.extend(gate_errors)
        return False, errors, stats
    
    # Run pipeline to get actual metrics
    try:
        pipeline_result = run_source_pipeline(source)
        kept_events = pipeline_result.get('kept_events', [])
        run_stats = pipeline_result.get('run_stats', {})
        
        stats = {
            'kept_count': len(kept_events),
            'dated_count': run_stats.get('dated_count', 0),
            'future_count': run_stats.get('future_count', 0),
            'dated_ratio': run_stats.get('dated_ratio', 0.0),
            'kept_ratio': run_stats.get('kept_ratio', 0.0)
        }
        
        # Strict thresholds
        MIN_EVENTS = 3
        MIN_DATED_RATIO = 0.70
        MIN_FUTURE_EVENTS = 1
        
        if stats['kept_count'] < MIN_EVENTS:
            errors.append(f"Insufficient events: {stats['kept_count']} < {MIN_EVENTS}")
        
        if stats['dated_ratio'] < MIN_DATED_RATIO:
            errors.append(f"Low date coverage: {stats['dated_ratio']:.1%} < {MIN_DATED_RATIO:.1%}")
        
        if stats['future_count'] < MIN_FUTURE_EVENTS:
            errors.append(f"No future events: {stats['future_count']} < {MIN_FUTURE_EVENTS}")
        
        # Lane-specific checks
        lane = infer_lane_from_source(source)
        if lane == 'html_list':
            # HTML sources need selectors
            if not source.get('selectors_json') or not source.get('selectors_json').get('item_selector'):
                errors.append("HTML source missing selectors")
        
    except Exception as e:
        errors.append(f"Pipeline error: {str(e)}")
        return False, errors, stats
    
    return len(errors) == 0, errors, stats


def update_registry_with_provenance(source_id: str, passed: bool, errors: List[str], stats: Dict, metadata: Dict):
    """Update source registry with provenance information."""
    if not REGISTRY_FILE.exists():
        sync_registry()
    
    with open(REGISTRY_FILE, 'r') as f:
        registry = json.load(f)
    
    if source_id not in registry:
        # Create entry
        sources = load_sources()
        source = next((s for s in sources if s.get('id') == source_id), None)
        if not source:
            return
        
        from utils.scraping_strategy import identify_sector
        
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
    entry['provenance'] = {
        'discovery_method': 'bulk_discovery',
        'onboarding_timestamp': datetime.now(timezone.utc).isoformat(),
        'onboarding_rank': metadata.get('score', 0),
        'validation_stats': stats
    }
    
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
        entry['next_action'] = 'Fix validation issues and re-run onboarding'
    
    with open(REGISTRY_FILE, 'w') as f:
        json.dump(registry, f, indent=2)


def get_event_count_from_api() -> int:
    """Get current event count from API."""
    try:
        response = requests.get('http://127.0.0.1:5000/api/events', timeout=5, params={'with_date': '0'})
        if response.status_code == 200:
            data = response.json()
            return len(data)
    except Exception:
        pass
    return -1


def main():
    parser = argparse.ArgumentParser(description='Batch onboard sources with strict guardrails')
    parser.add_argument('--priority', choices=['p0', 'p1', 'p2', 'all'], default='p0',
                       help='Priority filter')
    parser.add_argument('--apply', action='store_true',
                       help='Actually activate sources (default: dry-run)')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Dry run mode (default)')
    parser.add_argument('--min-rank', type=float, default=50.0,
                       help='Minimum rank score to consider (default: 50.0)')
    parser.add_argument('--max-sources', type=int, default=20,
                       help='Maximum sources to process (default: 20)')
    
    args = parser.parse_args()
    
    if args.apply:
        args.dry_run = False
    
    init_db()
    
    # Load sources
    sources = load_sources()
    bulk_sources = get_bulk_discovered_sources(sources)
    
    print(f"=== Batch Onboarding ===")
    print(f"Priority: {args.priority}")
    print(f"Bulk discovered sources: {len(bulk_sources)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()
    
    # Rank sources
    ranked = []
    for source in bulk_sources:
        score, metadata = rank_source(source)
        ranked.append((score, source, metadata))
    
    # Sort by score (highest first)
    ranked.sort(key=lambda x: x[0], reverse=True)
    
    # Filter by min rank
    ranked = [(s, src, meta) for s, src, meta in ranked if s >= args.min_rank]
    
    # Limit to max sources
    ranked = ranked[:args.max_sources]
    
    print(f"=== Ranked Ready Queue ===")
    print(f"Sources above rank {args.min_rank}: {len(ranked)}")
    print()
    
    ready_queue = []
    failure_breakdown = defaultdict(list)
    
    # Get initial event count
    initial_count = get_event_count_from_api()
    if initial_count >= 0:
        print(f"Initial event count (API): {initial_count}")
    print()
    
    # Process each source
    for i, (score, source, metadata) in enumerate(ranked, 1):
        source_id = source.get('id', '')
        firm_name = source.get('firm_name', '')
        lane = metadata['lane']
        
        print(f"{i}. {firm_name} ({source_id})")
        print(f"   Lane: {lane}, Rank: {score:.1f}")
        print(f"   URL: {source.get('url', '')[:80]}...")
        
        # Validate
        passed, errors, stats = validate_source_strict(source)
        
        if passed:
            print(f"   ✓ PASSED")
            print(f"   Stats: {stats.get('kept_count', 0)} events, {stats.get('dated_ratio', 0):.1%} dated, {stats.get('future_count', 0)} future")
            ready_queue.append({
                'source_id': source_id,
                'firm_name': firm_name,
                'lane': lane,
                'rank': score,
                'stats': stats,
                'metadata': metadata
            })
            
            # Activate if --apply
            if not args.dry_run:
                # Update source to active
                for s in sources:
                    if s.get('id') == source_id:
                        s['active'] = 1
                        s['onboarded_at'] = datetime.now(timezone.utc).isoformat()
                        break
                
                # Update registry
                update_registry_with_provenance(source_id, True, [], stats, metadata)
                print(f"   → ACTIVATED")
        else:
            print(f"   ✗ FAILED")
            for error in errors:
                print(f"      - {error}")
            
            # Categorize failure
            if any('HARD STOP' in r for r in metadata['reasons']):
                failure_type = 'hard_stop'
            elif any('not supported' in e.lower() for e in errors):
                failure_type = 'unsupported_lane'
            elif any('Insufficient events' in e for e in errors):
                failure_type = 'insufficient_events'
            elif any('Low date coverage' in e for e in errors):
                failure_type = 'low_date_coverage'
            elif any('No future events' in e for e in errors):
                failure_type = 'no_future_events'
            else:
                failure_type = 'other'
            
            failure_breakdown[failure_type].append({
                'source_id': source_id,
                'firm_name': firm_name,
                'lane': lane,
                'rank': score,
                'errors': errors,
                'stats': stats,
                'metadata': metadata
            })
            
            # Update registry even for failures
            if not args.dry_run:
                update_registry_with_provenance(source_id, False, errors, stats, metadata)
        
        print()
    
    # Save sources if --apply
    if not args.dry_run:
        save_sources(sources)
        sync_registry()
    
    # Summary
    print(f"=== Summary ===")
    print(f"Ready to activate: {len(ready_queue)}")
    print(f"Failed: {sum(len(v) for v in failure_breakdown.values())}")
    print()
    
    # Failure breakdown
    if failure_breakdown:
        print(f"=== Failure Breakdown ===")
        for failure_type, items in sorted(failure_breakdown.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"{failure_type}: {len(items)}")
            for item in items[:3]:  # Show top 3
                print(f"  - {item['firm_name']} ({item['source_id']}): {', '.join(item['errors'][:2])}")
        print()
    
    # Ready queue summary
    if ready_queue:
        print(f"=== Ready Queue (Top {len(ready_queue)}) ===")
        for item in ready_queue[:10]:
            print(f"  {item['firm_name']} ({item['lane']}): {item['stats'].get('kept_count', 0)} events, rank {item['rank']:.1f}")
        print()
    
    # Save reports
    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'priority': args.priority,
        'initial_event_count': initial_count,
        'ready_queue': ready_queue,
        'failure_breakdown': {k: v for k, v in failure_breakdown.items()},
        'summary': {
            'total_processed': len(ranked),
            'ready_count': len(ready_queue),
            'failed_count': sum(len(v) for v in failure_breakdown.values())
        }
    }
    
    with open(REPORT_FILE, 'w') as f:
        json.dump(report, f, indent=2)
    
    with open(QUEUE_FILE, 'w') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'ready_queue': ready_queue
        }, f, indent=2)
    
    print(f"Reports written:")
    print(f"  - {REPORT_FILE}")
    print(f"  - {QUEUE_FILE}")
    
    # Verify scrape + UI
    if not args.dry_run and ready_queue:
        print()
        print(f"=== Verifying Scrape + UI ===")
        
        # Run scrape
        print("Running scrape...")
        try:
            result = subprocess.run(
                [sys.executable, str(backend_dir / "scripts" / "run_scrape.py")],
                capture_output=True,
                text=True,
                timeout=120
            )
            print(f"Scrape completed (exit code: {result.returncode})")
        except Exception as e:
            print(f"Scrape error: {e}")
        
        # Check event count
        final_count = get_event_count_from_api()
        if initial_count >= 0 and final_count >= 0:
            delta = final_count - initial_count
            print(f"Event count: {initial_count} → {final_count} (Δ {delta:+d})")
            if delta > 0:
                print(f"✓ Event count increased")
            else:
                print(f"⚠ Event count did not increase")
        else:
            print("⚠ Could not verify event count (API not accessible)")
    
    print()
    if args.dry_run:
        print(f"[DRY RUN] Use --apply to actually activate sources")
    else:
        print(f"✓ Batch onboarding complete")


if __name__ == '__main__':
    main()
