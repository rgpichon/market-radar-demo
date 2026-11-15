#!/usr/bin/env python3
"""
End-to-End Source Pipeline

Runs the complete source discovery and promotion loop:
1. Bulk discovery → 2. Bulk validation (with enrichment) → 3. Generate sources → 4. Promotion loop → 5. Summary

Usage:
    python run_source_pipeline_end_to_end.py --priority p0 --dry-run
    python run_source_pipeline_end_to_end.py --priority p0 --apply --max-new-fetches 20
"""
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timezone
from collections import defaultdict

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.detail_enrich import validate_detail_enrichment


def run_command(cmd: List[str], description: str, dry_run: bool = False) -> Dict:
    """Run a subprocess command and return result."""
    print(f"\n{'='*70}")
    print(f"STEP: {description}")
    print(f"{'='*70}\n")
    
    if dry_run:
        print(f"[DRY-RUN] Would run: {' '.join(cmd)}")
        return {'success': True, 'output': '', 'dry_run': True}
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour max per step
        )
        
        if result.returncode == 0:
            print(f"✓ {description} completed successfully")
            if result.stdout:
                print(result.stdout[-1000:])  # Last 1000 chars
            return {'success': True, 'output': result.stdout, 'stderr': result.stderr}
        else:
            print(f"✗ {description} failed (exit code {result.returncode})")
            if result.stderr:
                print(result.stderr[-500:])
            return {'success': False, 'output': result.stdout, 'stderr': result.stderr, 'exit_code': result.returncode}
    except subprocess.TimeoutExpired:
        print(f"✗ {description} timed out")
        return {'success': False, 'error': 'timeout'}
    except Exception as e:
        print(f"✗ {description} error: {e}")
        return {'success': False, 'error': str(e)}


def load_json_file(file_path: Path) -> Dict:
    """Load JSON file, return empty dict if not found."""
    if not file_path.exists():
        return {}
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def generate_summary(
    discovery_result: Dict,
    validation_result: Dict,
    generation_result: Dict,
    promotion_result: Dict
) -> Dict:
    """Generate comprehensive terminal summary."""
    summary = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'discovery': {},
        'validation': {},
        'generation': {},
        'promotion': {},
        'totals': {}
    }
    
    # Discovery summary
    if discovery_result.get('success'):
        candidates_file = backend_dir / "source_candidates.json"
        candidates_data = load_json_file(candidates_file)
        firms = candidates_data.get('firms', [])
        total_candidates = sum(len(f.get('candidates', [])) for f in firms)
        summary['discovery'] = {
            'firms_discovered': len(firms),
            'total_candidates': total_candidates
        }
    
    # Validation summary
    if validation_result.get('success'):
        validated_file = backend_dir / "source_candidates_validated.json"
        validated_data = load_json_file(validated_file)
        firms = validated_data.get('firms', [])
        
        status_counts = defaultdict(int)
        for firm in firms:
            for candidate in firm.get('candidates_validated', []):
                status = candidate.get('status', 'unknown')
                status_counts[status] += 1
        
        summary['validation'] = {
            'firms_validated': len(firms),
            'by_status': dict(status_counts)
        }
    
    # Generation summary
    if generation_result.get('success'):
        sources_file = backend_dir / "sources.json"
        sources = load_json_file(sources_file)
        if isinstance(sources, list):
            active = sum(1 for s in sources if s.get('active', 0) == 1)
            inactive = len(sources) - active
            summary['generation'] = {
                'total_sources': len(sources),
                'active': active,
                'inactive': inactive
            }
    
    # Promotion summary
    if promotion_result.get('success'):
        evidence_file = backend_dir / "_evidence" / "detail_enrich" / "run_summary.json"
        promotion_data = load_json_file(evidence_file)
        
        if promotion_data:
            summary['promotion'] = {
                'total_processed': promotion_data.get('total_processed', 0),
                'promoted_count': promotion_data.get('promoted_count', 0),
                'by_classification': promotion_data.get('by_classification', {}),
                'top_failure_reasons': promotion_data.get('top_failure_reasons', {})
            }
    
    # Totals
    summary['totals'] = {
        'candidates_discovered': summary['discovery'].get('total_candidates', 0),
        'candidates_validated': sum(summary['validation'].get('by_status', {}).values()),
        'sources_generated': summary['generation'].get('total_sources', 0),
        'sources_promoted': summary['promotion'].get('promoted_count', 0)
    }
    
    return summary


def print_terminal_summary(summary: Dict):
    """Print comprehensive terminal summary."""
    print(f"\n{'='*70}")
    print("END-TO-END PIPELINE SUMMARY")
    print(f"{'='*70}\n")
    
    # Discovery
    if summary['discovery']:
        print("📡 DISCOVERY:")
        print(f"  Firms discovered: {summary['discovery'].get('firms_discovered', 0)}")
        print(f"  Total candidates: {summary['discovery'].get('total_candidates', 0)}")
    
    # Validation
    if summary['validation']:
        print("\n✅ VALIDATION:")
        print(f"  Firms validated: {summary['validation'].get('firms_validated', 0)}")
        by_status = summary['validation'].get('by_status', {})
        if by_status:
            print("  Status breakdown:")
            for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
                print(f"    {status}: {count}")
    
    # Generation
    if summary['generation']:
        print("\n📝 GENERATION:")
        gen = summary['generation']
        print(f"  Total sources: {gen.get('total_sources', 0)}")
        print(f"  Active: {gen.get('active', 0)}")
        print(f"  Inactive: {gen.get('inactive', 0)}")
    
    # Promotion
    if summary['promotion']:
        print("\n🚀 PROMOTION:")
        prom = summary['promotion']
        print(f"  Total processed: {prom.get('total_processed', 0)}")
        print(f"  Promoted: {prom.get('promoted_count', 0)}")
        by_class = prom.get('by_classification', {})
        if by_class:
            print("  Classification breakdown:")
            for cls, count in sorted(by_class.items(), key=lambda x: -x[1]):
                print(f"    {cls}: {count}")
        
        top_reasons = prom.get('top_failure_reasons', {})
        if top_reasons:
            print("  Top failure reasons:")
            for reason, count in list(top_reasons.items())[:5]:
                print(f"    {reason}: {count}")
    
    # Totals
    print(f"\n{'='*70}")
    print("TOTALS")
    print(f"{'='*70}")
    totals = summary['totals']
    print(f"  Candidates discovered: {totals.get('candidates_discovered', 0)}")
    print(f"  Candidates validated: {totals.get('candidates_validated', 0)}")
    print(f"  Sources generated: {totals.get('sources_generated', 0)}")
    print(f"  Sources promoted: {totals.get('sources_promoted', 0)}")
    print()


def main():
    parser = argparse.ArgumentParser(description='Run end-to-end source pipeline')
    parser.add_argument('--priority', choices=['p0', 'p1', 'p2', 'all'], default='p0',
                       help='Priority filter')
    parser.add_argument('--apply', action='store_true',
                       help='Apply changes (default: dry-run)')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Dry run mode (default: True unless --apply)')
    parser.add_argument('--max-new-fetches', type=int, default=None,
                       help='Maximum new network fetches per run')
    parser.add_argument('--max-sources', type=int, default=50,
                       help='Maximum sources to process in promotion')
    parser.add_argument('--max-detail', type=int, default=25,
                       help='Maximum detail pages per source')
    parser.add_argument('--min-sample-ok', type=int, default=8,
                       help='Minimum successful detail page fetches required')
    parser.add_argument('--skip-discovery', action='store_true',
                       help='Skip discovery step (use existing candidates)')
    parser.add_argument('--skip-validation', action='store_true',
                       help='Skip validation step (use existing validated candidates)')
    parser.add_argument('--skip-generation', action='store_true',
                       help='Skip generation step')
    parser.add_argument('--skip-promotion', action='store_true',
                       help='Skip promotion step')
    
    args = parser.parse_args()
    
    if args.apply:
        args.dry_run = False
    
    print(f"\n{'='*70}")
    print("END-TO-END SOURCE PIPELINE")
    print(f"{'='*70}")
    print(f"Priority: {args.priority}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"Caps: max_new_fetches={args.max_new_fetches}, max_sources={args.max_sources}, "
          f"max_detail={args.max_detail}, min_sample_ok={args.min_sample_ok}")
    print()
    
    results = {}
    
    # Step 1: Bulk Discovery
    if not args.skip_discovery:
        cmd = [
            sys.executable,
            str(backend_dir / "scripts" / "discover_sources_bulk.py"),
            "--priority", args.priority
        ]
        results['discovery'] = run_command(cmd, "Bulk Discovery", args.dry_run)
    else:
        results['discovery'] = {'success': True, 'skipped': True}
    
    # Step 2: Bulk Validation (with enrichment)
    if not args.skip_validation:
        cmd = [
            sys.executable,
            str(backend_dir / "scripts" / "validate_candidates_bulk.py"),
            "--priority", args.priority,
            "--enable-detail-enrichment"
        ]
        if args.dry_run:
            cmd.append("--dry-run")
        else:
            cmd.append("--apply")
        results['validation'] = run_command(cmd, "Bulk Validation (with enrichment)", args.dry_run)
    else:
        results['validation'] = {'success': True, 'skipped': True}
    
    # Step 3: Generate Sources
    if not args.skip_generation:
        cmd = [
            sys.executable,
            str(backend_dir / "scripts" / "generate_sources_from_candidates.py"),
            "--priority", args.priority
        ]
        results['generation'] = run_command(cmd, "Generate Sources", args.dry_run)
    else:
        results['generation'] = {'success': True, 'skipped': True}
    
    # Step 4: Promotion Loop
    if not args.skip_promotion:
        cmd = [
            sys.executable,
            str(backend_dir / "scripts" / "promote_partial_sources.py"),
            "--sources", "sources.json",
            "--max-sources", str(args.max_sources),
            "--max-detail", str(args.max_detail),
            "--min-sample-ok", str(args.min_sample_ok),
            "--sampling-mode", "stratified"
        ]
        if args.max_new_fetches:
            cmd.extend(["--max-new-fetches", str(args.max_new_fetches)])
        if args.dry_run:
            cmd.append("--dry-run")
        else:
            cmd.append("--apply")
        results['promotion'] = run_command(cmd, "Promotion Loop", args.dry_run)
    else:
        results['promotion'] = {'success': True, 'skipped': True}
    
    # Step 5: Generate and print summary
    summary = generate_summary(
        results['discovery'],
        results['validation'],
        results['generation'],
        results['promotion']
    )
    
    print_terminal_summary(summary)
    
    # Save summary
    summary_file = backend_dir / "_evidence" / "pipeline_summary.json"
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"Full summary saved to: {summary_file}")
    
    # Return exit code
    all_success = all(r.get('success', False) or r.get('skipped', False) for r in results.values())
    return 0 if all_success else 1


if __name__ == '__main__':
    sys.exit(main())
