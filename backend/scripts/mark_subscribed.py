#!/usr/bin/env python3
"""
Mark Newsletter Target as Subscribed

After manually subscribing to a newsletter, mark it as subscribed in the registry.
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def load_newsletter_targets() -> dict:
    """Load newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    if not targets_path.exists():
        print("newsletter_targets.json not found")
        sys.exit(1)
    
    with open(targets_path) as f:
        return json.load(f)


def save_newsletter_targets(data: dict):
    """Save newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    with open(targets_path, 'w') as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='Mark newsletter target as subscribed')
    parser.add_argument('--target-id', type=str, help='Target ID to mark as subscribed')
    parser.add_argument('--all-p0', action='store_true', help='Mark all P0 targets as subscribed (use with caution)')
    args = parser.parse_args()
    
    if not args.target_id and not args.all_p0:
        parser.error("Either --target-id or --all-p0 must be provided")
    
    data = load_newsletter_targets()
    targets = data.get('targets', [])
    
    if args.all_p0:
        # Mark all P0 targets as subscribed
        updated = 0
        for target in targets:
            if target.get('priority') == 'p0':
                old_status = target.get('status', 'todo')
                target['status'] = 'subscribed'
                updated += 1
                print(f"Marked {target.get('org_name')} ({target.get('id')}) as subscribed (was: {old_status})")
        
        if updated == 0:
            print("No P0 targets found")
            sys.exit(1)
        
        save_newsletter_targets(data)
        data['updated_at'] = datetime.now().strftime('%Y-%m-%d')
        save_newsletter_targets(data)
        
        print(f"\n✓ Marked {updated} P0 target(s) as subscribed")
        print("Next steps:")
        print("1. Wait for confirmation emails (if any)")
        print("2. Run: python backend/scripts/discover_newsletter_senders.py --days 30 --apply --report")
        print("3. Run: python backend/scripts/ingest_gmail.py --days 30 --max 200")
    else:
        # Mark single target
        target_id = args.target_id
        found = False
        
        for target in targets:
            if target.get('id') == target_id:
                old_status = target.get('status', 'todo')
                target['status'] = 'subscribed'
                found = True
                print(f"Marked {target.get('org_name')} ({target_id}) as subscribed (was: {old_status})")
                break
        
        if not found:
            print(f"Target '{target_id}' not found")
            sys.exit(1)
        
        save_newsletter_targets(data)
        data['updated_at'] = datetime.now().strftime('%Y-%m-%d')
        save_newsletter_targets(data)
        
        print(f"\n✓ Target marked as subscribed")
        print("Next steps:")
        print("1. Wait for confirmation emails (if any)")
        print("2. Run: python backend/scripts/discover_newsletter_senders.py --days 30 --apply --report")
        print("3. Run: python backend/scripts/ingest_gmail.py --days 30 --max 200")


if __name__ == '__main__':
    main()
