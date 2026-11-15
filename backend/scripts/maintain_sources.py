#!/usr/bin/env python3
"""
Source Maintenance Loop

Automatically detects degradation and applies repair playbooks.

Usage:
    python maintain_sources.py --dry-run --max-sources 5
    python maintain_sources.py --apply --repair --max-sources 10
    python maintain_sources.py --only-degraded --apply
"""
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone
import os

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from db import (
    init_db, insert_source_health, get_last_source_health,
    get_latest_source_health_map
)
from utils.source_degradation import detect_degradation
from utils.source_repair import select_playbook


def load_sources() -> List[Dict]:
    """Load sources from sources.json."""
    sources_file = backend_dir / "sources.json"
    if not sources_file.exists():
        return []
    with open(sources_file, 'r') as f:
        return json.load(f)


def load_source_stats() -> Dict[str, Dict]:
    """Load latest source_stats.json (from scrape run)."""
    stats_file = backend_dir / "source_stats.json"
    if not stats_file.exists():
        return {}
    with open(stats_file, 'r') as f:
        return json.load(f)


def compute_snapshot_from_run_stats(source_id: str, run_stats: Dict, run_id: str) -> Dict:
    """
    Compute source_health snapshot from run_stats.
    
    Enforces invariant: dated_count + undated_count == kept_count
    """
    raw_count = run_stats.get('raw_count', 0) or 0
    kept_count = run_stats.get('kept_count', 0) or 0
    dated_count = run_stats.get('dated_count', 0) or 0
    undated_count = run_stats.get('undated_count', 0) or 0
    future_count = run_stats.get('future_count', 0) or 0
    
    # Enforce invariant
    if dated_count + undated_count != kept_count:
        # Recompute from kept_count if mismatch
        if kept_count > 0:
            # Estimate: use dated_ratio if available
            dated_ratio = run_stats.get('dated_ratio', 0.0) or 0.0
            dated_count = int(kept_count * dated_ratio)
            undated_count = kept_count - dated_count
        else:
            dated_count = 0
            undated_count = 0
    
    dated_ratio = dated_count / kept_count if kept_count > 0 else 0.0
    kept_ratio = kept_count / raw_count if raw_count > 0 else 0.0
    
    # Extract error_class from diagnostics if available
    error_class = None
    error_evidence = None
    diagnostics = run_stats.get('diagnostics', {})
    if diagnostics:
        error = diagnostics.get('error')
        if error:
            error_class = 'deferred_transient_network'  # Default classification
            error_evidence = str(error)[:200]  # Truncate
    
    return {
        'source_id': source_id,
        'ts_utc': datetime.now(timezone.utc).isoformat(),
        'raw_count': raw_count,
        'kept_count': kept_count,
        'dated_count': dated_count,
        'undated_count': undated_count,
        'future_count': future_count,
        'dated_ratio': dated_ratio,
        'kept_ratio': kept_ratio,
        'error_class': error_class,
        'error_evidence': error_evidence,
        'run_id': run_id
    }


def run_scrape_if_needed(dry_run: bool) -> Optional[str]:
    """Run scrape to generate fresh run_stats if --run-scrape-first."""
    if dry_run:
        print("[DRY-RUN] Would run scrape to generate fresh stats")
        return "dry_run_run_id"
    
    print("Running scrape to generate fresh source stats...")
    run_scrape_path = backend_dir / "scripts" / "run_scrape.py"
    result = subprocess.run(
        [sys.executable, str(run_scrape_path)],
        capture_output=True,
        text=True,
        cwd=str(backend_dir),
        timeout=600
    )
    
    if result.returncode != 0:
        print(f"Warning: Scrape failed: {result.stderr[:500]}")
        return None
    
    # Generate run_id from timestamp
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return run_id


def apply_patch_to_source(source: Dict, patch: Dict) -> Dict:
    """Apply patch to source config (returns new dict, doesn't modify original)."""
    updated = source.copy()
    for key, value in patch.items():
        if key == 'detail_fetch' and isinstance(value, dict):
            # Merge detail_fetch config
            current = updated.get('detail_fetch', {})
            current.update(value)
            updated['detail_fetch'] = current
        else:
            updated[key] = value
    return updated


def write_sources_json(sources: List[Dict], dry_run: bool):
    """Write updated sources back to sources.json."""
    if dry_run:
        print("[DRY-RUN] Would write sources.json")
        return
    
    sources_file = backend_dir / "sources.json"
    # Backup first
    backup_file = sources_file.with_suffix('.json.backup')
    if sources_file.exists():
        import shutil
        shutil.copy2(sources_file, backup_file)
        print(f"Backed up sources.json to {backup_file.name}")
    
    with open(sources_file, 'w') as f:
        json.dump(sources, f, indent=2)
    print(f"Updated {sources_file}")


def main():
    parser = argparse.ArgumentParser(description='Source maintenance loop')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Dry-run mode (default: ON, no writes)')
    parser.add_argument('--apply', action='store_true',
                        help='Apply changes (writes to DB and sources.json)')
    parser.add_argument('--repair', action='store_true',
                        help='Run repair actions (autoparser, detail enrichment)')
    parser.add_argument('--max-sources', type=int, default=None,
                        help='Maximum sources to process')
    parser.add_argument('--only-degraded', action='store_true',
                        help='Only process degraded sources')
    parser.add_argument('--priority', type=str,
                        help='Filter by priority label (if sources have priority field)')
    parser.add_argument('--run-scrape-first', action='store_true',
                        help='Run scrape to generate fresh run_stats before maintenance')
    
    args = parser.parse_args()
    
    if args.apply:
        args.dry_run = False
    
    print("=" * 70)
    print("SOURCE MAINTENANCE LOOP")
    print("=" * 70)
    if args.dry_run:
        print("[DRY-RUN MODE - No changes will be saved]\n")
    else:
        print("[APPLY MODE - Changes will be saved]\n")
    
    # Initialize DB
    init_db()
    
    # Step 1: Load sources
    sources = load_sources()
    if not sources:
        print("No sources found in sources.json")
        return 1
    
    # Filter by priority if specified
    if args.priority:
        sources = [s for s in sources if s.get('priority') == args.priority]
    
    # Limit count
    if args.max_sources:
        sources = sources[:args.max_sources]
    
    print(f"Processing {len(sources)} sources...\n")
    
    # Step 2: Optionally run scrape
    run_id = None
    if args.run_scrape_first:
        run_id = run_scrape_if_needed(args.dry_run)
    else:
        # Use timestamp as run_id
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    # Step 3: Load source_stats (from latest scrape or existing file)
    source_stats = load_source_stats()
    
    # Step 4: Compute snapshots and detect degradation
    degraded_sources = []
    maintenance_results = []
    evidence_dir = backend_dir / "_evidence" / "maintenance" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    for source in sources:
        source_id = source.get('id', 'unknown')
        firm_name = source.get('firm_name', 'Unknown')
        
        print(f"[{source_id}] {firm_name}")
        
        # Get run_stats for this source
        stats = source_stats.get(source_id, {})
        if not stats:
            print(f"  ⚠ No run_stats available (source may not have been scraped recently)")
            continue
        
        # Compute snapshot
        snapshot = compute_snapshot_from_run_stats(source_id, stats, run_id)
        
        # Write snapshot to DB (unless dry-run)
        if not args.dry_run:
            try:
                insert_source_health(snapshot)
            except Exception as e:
                print(f"  ✗ Failed to insert snapshot: {e}")
                continue
        
        # Get historical snapshots for degradation detection
        history = get_last_source_health(source_id, limit=14)
        
        # Detect degradation
        degradation = detect_degradation(history, snapshot)
        
        result = {
            'source_id': source_id,
            'firm_name': firm_name,
            'snapshot': snapshot,
            'degradation': degradation
        }
        
        if degradation.get('degraded'):
            degraded_sources.append(source)
            print(f"  ✗ DEGRADED: {degradation.get('degradation_class')}")
            print(f"    Evidence: {degradation.get('evidence')}")
            
            # Select playbook
            patch, actions, why = select_playbook(source, degradation, evidence=stats)
            result['patch'] = patch
            result['repair_actions'] = actions
            result['why'] = why
            
            print(f"    Playbook: {degradation.get('recommended_playbook')}")
            if patch:
                print(f"    Patch: {list(patch.keys())}")
            if actions:
                print(f"    Actions: {len(actions)} repair action(s)")
        else:
            print(f"  ✓ Healthy")
        
        maintenance_results.append(result)
        
        # Save per-source evidence
        source_evidence_dir = evidence_dir / source_id
        source_evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_file = source_evidence_dir / "maintenance_result.json"
        with open(evidence_file, 'w') as f:
            json.dump(result, f, indent=2)
    
    # Step 5: Apply patches if --apply
    if args.apply and degraded_sources:
        print(f"\n{'='*70}")
        print(f"APPLYING PATCHES TO {len(degraded_sources)} SOURCES")
        print(f"{'='*70}\n")
        
        # Build source map for efficient lookup
        source_map = {s['id']: s for s in sources}
        updated_sources = []
        patches_applied = 0
        
        for result in maintenance_results:
            if not result.get('degradation', {}).get('degraded'):
                updated_sources.append(source_map[result['source_id']])
                continue
            
            patch = result.get('patch', {})
            if not patch:
                updated_sources.append(source_map[result['source_id']])
                continue
            
            source = source_map[result['source_id']]
            updated = apply_patch_to_source(source, patch)
            updated_sources.append(updated)
            patches_applied += 1
            
            print(f"[{result['source_id']}] Applied patch: {list(patch.keys())}")
        
        # Write updated sources.json
        write_sources_json(updated_sources, dry_run=args.dry_run)
        print(f"\nApplied {patches_applied} patches")
    
    # Step 6: Run repair actions if --repair
    if args.repair and degraded_sources:
        print(f"\n{'='*70}")
        print(f"RUNNING REPAIR ACTIONS")
        print(f"{'='*70}\n")
        
        for result in maintenance_results:
            if not result.get('degradation', {}).get('degraded'):
                continue
            
            actions = result.get('repair_actions', [])
            if not actions:
                continue
            
            source_id = result['source_id']
            print(f"[{source_id}] Running {len(actions)} repair action(s)...")
            
            for action in actions:
                if args.dry_run:
                    print(f"  [DRY-RUN] Would run: {action}")
                else:
                    # Parse action string (simplified - expects python -m ... format)
                    if action.startswith("python -m") or action.startswith("python"):
                        # Extract command
                        parts = action.split()
                        if parts[0] == "python" and parts[1] == "-m":
                            module = parts[2]
                            cmd_args = parts[3:]
                            cmd = [sys.executable, "-m", module] + cmd_args
                        else:
                            print(f"  ⚠ Skipping action (unparseable): {action}")
                            continue
                        
                        print(f"  → Running: {' '.join(cmd)}")
                        try:
                            subprocess.run(cmd, cwd=str(backend_dir), timeout=300, check=False)
                        except Exception as e:
                            print(f"  ✗ Action failed: {e}")
                    else:
                        print(f"  ⚠ Skipping action (not a command): {action}")
    
    # Step 7: Generate run summary
    run_summary = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'run_id': run_id,
        'dry_run': args.dry_run,
        'total_sources': len(sources),
        'sources_processed': len(maintenance_results),
        'degraded_count': len(degraded_sources),
        'healthy_count': len(maintenance_results) - len(degraded_sources),
        'degradation_breakdown': {},
        'playbook_breakdown': {},
        'patches_applied': patches_applied if args.apply else 0,
        'results': maintenance_results
    }
    
    # Breakdown by degradation class
    for result in maintenance_results:
        deg_class = result.get('degradation', {}).get('degradation_class')
        if deg_class:
            run_summary['degradation_breakdown'][deg_class] = \
                run_summary['degradation_breakdown'].get(deg_class, 0) + 1
        
        playbook = result.get('degradation', {}).get('recommended_playbook')
        if playbook:
            run_summary['playbook_breakdown'][playbook] = \
                run_summary['playbook_breakdown'].get(playbook, 0) + 1
    
    # Save run summary
    summary_file = evidence_dir / "run_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(run_summary, f, indent=2)
    
    # Print summary
    print(f"\n{'='*70}")
    print("MAINTENANCE SUMMARY")
    print(f"{'='*70}\n")
    print(f"Total processed: {run_summary['sources_processed']}")
    print(f"  ✓ Healthy: {run_summary['healthy_count']}")
    print(f"  ✗ Degraded: {run_summary['degraded_count']}")
    
    if run_summary['degradation_breakdown']:
        print("\nDegradation breakdown:")
        for deg_class, count in sorted(run_summary['degradation_breakdown'].items()):
            print(f"  {deg_class}: {count}")
    
    if run_summary['playbook_breakdown']:
        print("\nPlaybook breakdown:")
        for playbook, count in sorted(run_summary['playbook_breakdown'].items()):
            print(f"  {playbook}: {count}")
    
    if args.apply:
        print(f"\nPatches applied: {run_summary['patches_applied']}")
    
    print(f"\nEvidence saved to: {evidence_dir}")
    print(f"Run summary: {summary_file}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
