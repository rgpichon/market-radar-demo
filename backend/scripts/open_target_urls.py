#!/usr/bin/env python3
"""
Open Target URLs Helper

Prints signup URLs for manual subscription in a clean, stable order.
"""
import sys
import json
import argparse
from pathlib import Path

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


def main():
    from backend.utils.target_filter import filter_newsletter_targets
    
    parser = argparse.ArgumentParser(description='Print signup URLs for manual subscription')
    parser.add_argument('--priority', type=str, choices=['p0', 'p1', 'p2'], default='p0', help='Target priority')
    parser.add_argument('--only', type=str, choices=['requires_manual', 'todo'], help='Filter by status/feasibility')
    args = parser.parse_args()
    
    targets_data = load_newsletter_targets()
    if not targets_data:
        print("No newsletter targets found")
        sys.exit(1)
    
    all_targets = targets_data.get('targets', [])
    
    # Determine status filter
    include_statuses = None
    if args.only == 'requires_manual':
        include_statuses = ['requires_manual']
    elif args.only == 'todo':
        include_statuses = ['todo']
    
    # Use canonical filter
    filtered_targets, breakdown = filter_newsletter_targets(
        all_targets,
        priority=args.priority,
        include_statuses=include_statuses,
        enforce_governance=True  # Exclude paused/cooldown/rejected
    )
    
    # Additional filtering for requires_manual (check feasibility)
    if args.only == 'requires_manual':
        final_targets = []
        for t in filtered_targets:
            status = t.get('status', 'todo')
            acq = t.get('acquisition', {})
            feasibility = acq.get('automation_feasibility', 'unknown')
            
            if status == 'requires_manual' or feasibility in ['requires_manual', 'captcha_blocked', 'login_required']:
                final_targets.append(t)
        filtered_targets = final_targets
    
    # Sort by org_name, then by best discovery score
    def sort_key(t):
        org = t.get('org_name', '')
        acq = t.get('acquisition', {})
        pages = acq.get('discovered_signup_pages', [])
        best_score = max([p.get('score', 0) for p in pages] + [0])
        return (org, -best_score)
    
    filtered_targets.sort(key=sort_key)
    
    if not filtered_targets:
        print("No matching targets found")
        sys.exit(1)
    
    print(f"Signup URLs for {args.priority.upper()} targets ({len(filtered_targets)} total):")
    print()
    
    for target in filtered_targets:
        org_name = target.get('org_name', 'Unknown')
        target_id = target.get('id', 'unknown')
        signup_url = target.get('signup_url', '')
        
        if not signup_url or signup_url in ['FILL_ME', 'AUTO_DISCOVER']:
            # Try to get from discovered pages
            acq = target.get('acquisition', {})
            pages = acq.get('discovered_signup_pages', [])
            real_pages = [p for p in pages if p.get('url', '').startswith('http')]
            if real_pages:
                sorted_pages = sorted(real_pages, key=lambda p: -p.get('score', 0))
                signup_url = sorted_pages[0].get('url', '')
            else:
                signup_url = 'NO_URL_FOUND'
        
        print(f"{org_name} ({target_id}):")
        print(f"  {signup_url}")
        print()


if __name__ == '__main__':
    main()
