#!/usr/bin/env python3
"""
Mark Opt-In Confirmed

Updates newsletter target status after manual opt-in confirmation.
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def load_newsletter_targets() -> dict:
    """Load newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    if not targets_path.exists():
        return {'targets': []}
    with open(targets_path) as f:
        return json.load(f)


def save_newsletter_targets(data: dict):
    """Save newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    data['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    with open(targets_path, 'w') as f:
        json.dump(data, f, indent=2)


def ensure_acquisition_fields(target: dict) -> dict:
    """Ensure target has acquisition fields."""
    if 'acquisition' not in target:
        target['acquisition'] = {}
    
    acq = target['acquisition']
    acq.setdefault('discovery_seed_urls', [])
    acq.setdefault('discovered_signup_pages', [])
    acq.setdefault('discovered_forms', [])
    acq.setdefault('subscribe_attempts', [])
    acq.setdefault('opt_in_required', None)
    acq.setdefault('last_success_utc', None)
    acq.setdefault('last_failure_utc', None)
    acq.setdefault('automation_feasibility', 'unknown')
    
    return target


def main():
    parser = argparse.ArgumentParser(description='Mark newsletter opt-in as confirmed')
    parser.add_argument('--target-id', type=str, required=True, help='Target ID to mark confirmed')
    parser.add_argument('--notes', type=str, default='', help='Optional notes')
    args = parser.parse_args()
    
    targets_data = load_newsletter_targets()
    targets = targets_data.get('targets', [])
    
    # Find target
    target = None
    for t in targets:
        if t.get('id') == args.target_id:
            target = t
            break
    
    if not target:
        print(f"Error: Target '{args.target_id}' not found")
        return 1
    
    target = ensure_acquisition_fields(target)
    
    # Update status
    now = datetime.now(timezone.utc).isoformat()
    target['status'] = 'subscribed'
    target['acquisition']['last_success_utc'] = now
    target['acquisition']['opt_in_required'] = True
    
    # Add note
    if args.notes:
        existing_notes = target.get('notes', '')
        target['notes'] = f"{existing_notes} | Opt-in confirmed: {args.notes}" if existing_notes else f"Opt-in confirmed: {args.notes}"
    
    # Save
    save_newsletter_targets(targets_data)
    
    print(f"Marked {args.target_id} ({target.get('org_name')}) as subscribed")
    print(f"Last success: {now}")
    print()
    print("Next steps:")
    print("1. Run discover_newsletter_senders.py to learn sender addresses")
    print("2. Run ingest_gmail.py --mode targets to ingest events")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
