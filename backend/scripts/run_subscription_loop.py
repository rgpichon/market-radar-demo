#!/usr/bin/env python3
"""
Newsletter Subscription Loop Orchestration

Runs the complete newsletter acquisition workflow:
1. Generate status report
2. Discover signup pages
3. Extract signup forms
4. Attempt subscriptions (HTTP mode)
5. Find opt-in emails
6. Generate final report

Degrades gracefully without Gmail credentials.
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def run_command(cmd: list, description: str, optional: bool = False) -> tuple:
    """Run a command and return (success, output)."""
    print(f"\n{'=' * 60}")
    print(f"STEP: {description}")
    print(f"{'=' * 60}")
    print(f"Running: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 min timeout
        )
        
        output = result.stdout
        if result.stderr:
            output += '\n' + result.stderr
        
        if result.returncode == 0:
            print(output)
            return True, output
        else:
            if optional:
                print(f"Optional step failed (continuing): {result.stderr[:200]}")
                return False, output
            else:
                print(f"Command failed (exit code {result.returncode})")
                print(output)
                return False, output
    except subprocess.TimeoutExpired:
        print("Command timed out")
        return False, "Timeout"
    except Exception as e:
        print(f"Error: {e}")
        return False, str(e)


def check_gmail_credentials() -> bool:
    """Check if Gmail credentials are available."""
    try:
        from backend.utils.gmail_auth import check_credentials_available
        return check_credentials_available()
    except ImportError:
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Run newsletter subscription loop')
    parser.add_argument('--priority', type=str, choices=['p0', 'p1', 'p2'], default='p0', help='Target priority')
    parser.add_argument('--skip-evaluate', action='store_true', help='Skip decision evaluation step')
    parser.add_argument('--skip-discovery', action='store_true', help='Skip discovery step')
    parser.add_argument('--skip-forms', action='store_true', help='Skip form extraction step')
    parser.add_argument('--skip-subscribe', action='store_true', help='Skip subscription step')
    parser.add_argument('--dry-run', action='store_true', help='Dry run all steps')
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("NEWSLETTER SUBSCRIPTION LOOP")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Priority: {args.priority}")
    
    has_gmail = check_gmail_credentials()
    if has_gmail:
        print("Gmail credentials: FOUND")
    else:
        print("Gmail credentials: NOT FOUND (opt-in detection will be skipped)")
    
    python = sys.executable
    scripts_dir = Path(__file__).parent
    
    # Step 1: Generate initial status report
    run_command(
        [python, str(scripts_dir / 'report_newsletter_targets.py')],
        "Generate Initial Status Report"
    )
    
    # Step 1.5: Evaluate decisions (GOVERNANCE - must run before any operations)
    if not args.skip_evaluate:
        cmd = [python, str(scripts_dir / 'evaluate_decisions.py')]
        if args.dry_run:
            cmd.append('--dry-run')
        run_command(cmd, "Evaluate Decisions (Governance)", optional=False)
    else:
        print("\n[SKIPPED] Decision evaluation step")
    
    # Step 2: Discover signup pages
    if not args.skip_discovery:
        cmd = [python, str(scripts_dir / 'discover_signup_pages.py'), '--priority', args.priority, '--apply']
        if args.dry_run:
            cmd.append('--dry-run')
        run_command(cmd, "Discover Signup Pages")
    else:
        print("\n[SKIPPED] Discovery step")
    
    # Step 3: Extract signup forms
    if not args.skip_forms:
        cmd = [python, str(scripts_dir / 'extract_signup_forms.py'), '--priority', args.priority, '--apply']
        if args.dry_run:
            cmd.append('--dry-run')
        run_command(cmd, "Extract Signup Forms")
    else:
        print("\n[SKIPPED] Form extraction step")
    
    # Step 4: Attempt subscriptions
    if not args.skip_subscribe:
        cmd = [python, str(scripts_dir / 'subscribe_newsletters.py'), '--priority', args.priority, '--apply']
        if args.dry_run:
            cmd.append('--dry-run')
        run_command(cmd, "Attempt Subscriptions (HTTP mode)")
    else:
        print("\n[SKIPPED] Subscription step")
    
    # Step 5: Find opt-in emails (only if Gmail credentials exist)
    if has_gmail:
        cmd = [python, str(scripts_dir / 'find_opt_in_emails.py'), '--days', '14']
        if args.dry_run:
            cmd.append('--dry-run')
        run_command(cmd, "Find Opt-In Emails", optional=True)
    else:
        print("\n" + "=" * 60)
        print("STEP: Find Opt-In Emails")
        print("=" * 60)
        print("Skipped: No Gmail credentials available")
        print()
        print("To enable opt-in detection:")
        print("1. Place credentials.json in backend/_secrets/")
        print("2. Run this script again")
    
    # Step 6: Generate final status report
    run_command(
        [python, str(scripts_dir / 'report_newsletter_targets.py')],
        "Generate Final Status Report"
    )
    
    # Summary
    print("\n" + "=" * 60)
    print("SUBSCRIPTION LOOP COMPLETED")
    print("=" * 60)
    print()
    print("NEXT ACTIONS:")
    print()
    print("1. Check backend/opt_in_queue.json for confirmation links")
    print("2. Manually click confirmation links in a browser")
    print("3. Run: python backend/scripts/mark_opt_in_confirmed.py --target-id <id>")
    print("4. Run: python backend/scripts/discover_newsletter_senders.py --apply")
    print("5. Run: python backend/scripts/ingest_gmail.py --mode targets")
    print()
    print("Report: md/NEWSLETTER_INGESTION_RUNBOOK.md")
    print("=" * 60)


if __name__ == '__main__':
    main()
