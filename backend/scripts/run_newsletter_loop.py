#!/usr/bin/env python3
"""
Newsletter Ingestion Loop

Orchestrates the complete newsletter workflow:
1. Generate status report
2. Run sender discovery
3. Run Gmail ingestion in dry-run mode
4. Output recommended next actions

Degrades gracefully if Gmail credentials are missing.
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def run_command(cmd: list, description: str) -> tuple[bool, str]:
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
            timeout=120
        )
        
        output = result.stdout
        if result.stderr:
            output += '\n' + result.stderr
        
        if result.returncode == 0:
            print(output)
            return True, output
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
    print("\n" + "=" * 60)
    print("NEWSLETTER INGESTION LOOP")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    has_gmail = check_gmail_credentials()
    if has_gmail:
        print("Gmail credentials: FOUND")
    else:
        print("Gmail credentials: NOT FOUND (will use local mode)")
    
    python = sys.executable
    scripts_dir = Path(__file__).parent
    
    # Step 1: Generate status report
    success, _ = run_command(
        [python, str(scripts_dir / 'report_newsletter_targets.py')],
        "Generate Newsletter Targets Status Report"
    )
    if not success:
        print("Warning: Status report generation failed")
    
    # Step 2: Run sender discovery
    discovery_cmd = [python, str(scripts_dir / 'discover_newsletter_senders.py'), '--report']
    if has_gmail:
        discovery_cmd.extend(['--days', '30', '--max', '200'])
    else:
        discovery_cmd.append('--local')
    
    success, _ = run_command(discovery_cmd, "Discover Newsletter Senders")
    if not success:
        print("Warning: Sender discovery failed or no results")
    
    # Step 3: Run Gmail ingestion dry-run (only if credentials exist)
    if has_gmail:
        success, output = run_command(
            [python, str(scripts_dir / 'ingest_gmail.py'),
             '--use-newsletter-targets', '--days', '14', '--max', '50', '--dry-run'],
            "Gmail Ingestion (Dry Run)"
        )
    else:
        print("\n" + "=" * 60)
        print("STEP: Gmail Ingestion (Dry Run)")
        print("=" * 60)
        print("Skipped: No Gmail credentials available")
        print()
        print("To enable Gmail ingestion:")
        print("1. Create a Google Cloud project and enable Gmail API")
        print("2. Download OAuth credentials to backend/_secrets/credentials.json")
        print("3. Run this script again")
    
    # Step 4: Summarize and recommend next actions
    print("\n" + "=" * 60)
    print("RECOMMENDED NEXT ACTIONS")
    print("=" * 60)
    print()
    
    # Load targets to check status
    try:
        import json
        targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
        with open(targets_path) as f:
            targets_data = json.load(f)
        
        targets = targets_data.get('targets', [])
        
        # Count by status
        todo = [t for t in targets if t.get('status') == 'todo']
        subscribed = [t for t in targets if t.get('status') == 'subscribed']
        validated = [t for t in targets if t.get('status') == 'validated']
        
        # Count by confidence
        high_conf = [t for t in targets if t.get('sender_confidence') == 'high']
        medium_conf = [t for t in targets if t.get('sender_confidence') == 'medium']
        
        # Check missing signup URLs
        missing_signup = [t for t in targets if t.get('signup_url') == 'FILL_ME']
        
        print("Current Status:")
        print(f"  - Todo: {len(todo)}")
        print(f"  - Subscribed: {len(subscribed)}")
        print(f"  - Validated: {len(validated)}")
        print(f"  - High confidence: {len(high_conf)}")
        print(f"  - Medium confidence: {len(medium_conf)}")
        print()
        
        if missing_signup:
            print("1. FILL SIGNUP URLs:")
            for t in missing_signup[:5]:
                print(f"   - {t.get('org_name')}: Find newsletter signup page")
            if len(missing_signup) > 5:
                print(f"   - ... and {len(missing_signup) - 5} more")
            print()
        
        if todo:
            print("2. SUBSCRIBE TO NEWSLETTERS:")
            for t in todo[:5]:
                print(f"   - {t.get('org_name')}: Subscribe using rdr.events.rp@gmail.com")
            if len(todo) > 5:
                print(f"   - ... and {len(todo) - 5} more")
            print()
        
        if not has_gmail:
            print("3. SET UP GMAIL CREDENTIALS:")
            print("   - Place credentials.json in backend/_secrets/")
            print("   - Run discovery again with Gmail mode")
            print()
        
        if high_conf or medium_conf:
            print("4. RUN INGESTION:")
            print("   python backend/scripts/ingest_gmail.py --use-newsletter-targets --days 30 --max 200")
            print()
        
    except Exception as e:
        print(f"Error loading targets: {e}")
    
    print("=" * 60)
    print("Loop completed")
    print("=" * 60)
    
    # Check reports
    print()
    print("Generated Reports:")
    md_dir = Path(backend_dir) / 'md'
    reports = [
        'NEWSLETTER_TARGETS_STATUS.md',
        'NEWSLETTER_SENDER_DISCOVERY.md'
    ]
    for report in reports:
        path = md_dir / report
        if path.exists():
            print(f"  - {path}")


if __name__ == '__main__':
    main()
