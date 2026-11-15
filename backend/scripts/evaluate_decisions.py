#!/usr/bin/env python3
"""
Evaluate Newsletter Subscription Decisions

Deterministic decision-making for all newsletter targets.
"""
import sys
import argparse
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.db import init_db
from backend.utils.decision_engine import evaluate_all_targets


def main():
    parser = argparse.ArgumentParser(description='Evaluate subscription decisions for all newsletter targets')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (compute decisions but do not write to DB)')
    parser.add_argument('--target-id', type=str, help='Evaluate specific target only')
    args = parser.parse_args()
    
    # Initialize database
    init_db()
    
    if args.target_id:
        # Evaluate single target (simplified - would need to extend evaluate_all_targets)
        print(f"Single target evaluation not yet implemented. Use --dry-run to see all decisions.")
        sys.exit(1)
    
    # Evaluate all targets
    print("Evaluating subscription decisions...")
    print()
    
    summary = evaluate_all_targets(dry_run=args.dry_run)
    
    if 'error' in summary:
        print(f"Error: {summary['error']}")
        sys.exit(1)
    
    print("=" * 60)
    print("DECISION EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Total targets: {summary['total']}")
    print(f"Auto-subscribe: {summary['auto_subscribe']}")
    print(f"Manual review: {summary['manual_review']}")
    print(f"Rejected: {summary['rejected']}")
    print(f"Paused: {summary['paused']}")
    print(f"Cooldown: {summary['cooldown']}")
    print("=" * 60)
    
    if args.dry_run:
        print()
        print("[DRY RUN] Decisions computed but not written to database.")
        print("Run without --dry-run to persist decisions.")
    else:
        print()
        print("Decisions written to database.")
        print("Run report_newsletter_targets.py to see governance report.")


if __name__ == '__main__':
    main()
