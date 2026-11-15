#!/usr/bin/env python3
"""
Update Newsletter Targets from Gmail

Scans Gmail for messages matching newsletter targets and updates discovered_senders,
sender_confidence, last_seen_at, and status fields.
"""
import sys
import json
import argparse
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.utils.gmail_auth import get_gmail_service, check_credentials_available
from backend.utils.gmail_parse import parse_gmail_message


def load_newsletter_targets() -> dict:
    """Load newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    if not targets_path.exists():
        print(f"Error: {targets_path} not found")
        sys.exit(1)
    
    try:
        with open(targets_path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {targets_path}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading {targets_path}: {e}")
        sys.exit(1)


def save_newsletter_targets(data: dict):
    """Save newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    try:
        with open(targets_path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error writing {targets_path}: {e}")
        sys.exit(1)


def extract_domain_from_email(email: str) -> str:
    """Extract domain from email address."""
    if not email:
        return ''
    _, addr = parseaddr(email)
    if '@' in addr:
        return addr.split('@')[1].lower()
    return ''


def extract_sender_from_message(message: dict) -> tuple[str, str]:
    """
    Extract sender email and domain from Gmail message.
    
    Returns:
        Tuple of (email, domain)
    """
    headers = message.get('payload', {}).get('headers', [])
    from_header = ''
    for header in headers:
        if header.get('name', '').lower() == 'from':
            from_header = header.get('value', '')
            break
    
    if not from_header:
        return '', ''
    
    name, email = parseaddr(from_header)
    domain = extract_domain_from_email(email)
    return email.lower(), domain


def matches_target(message: dict, target: dict) -> bool:
    """
    Check if message matches target criteria.
    
    Args:
        message: Gmail message dict
        target: Target dict from newsletter_targets.json
    
    Returns:
        True if message matches target
    """
    email, domain = extract_sender_from_message(message)
    
    # Check expected domains
    expected_domains = target.get('expected_from_domains', [])
    if expected_domains:
        if domain not in [d.lower() for d in expected_domains]:
            return False
    
    # Check expected emails
    expected_emails = target.get('expected_from_emails', [])
    if expected_emails:
        if email not in [e.lower() for e in expected_emails]:
            return False
    
    # If no expected domains/emails, check discovered_senders
    if not expected_domains and not expected_emails:
        discovered = target.get('discovered_senders', [])
        if discovered:
            if domain not in [extract_domain_from_email(d) for d in discovered] and email not in [d.lower() for d in discovered]:
                return False
    
    return True


def calculate_confidence(messages: list, target: dict) -> str:
    """
    Calculate sender confidence based on message patterns.
    
    Rules:
    - HIGH: at least 3 messages from same domain/email in last 30 days + subject contains include keyword
    - MEDIUM: at least 1 message but uncertain consistency
    - LOW: otherwise
    """
    if not messages:
        return 'low'
    
    # Count senders
    sender_counts = Counter()
    include_keywords = set([kw.lower() for kw in target.get('subject_include_any', [])])
    
    for msg in messages:
        email, domain = extract_sender_from_message(msg)
        sender_key = email or domain
        
        # Check subject for include keywords
        headers = msg.get('payload', {}).get('headers', [])
        subject = ''
        for header in headers:
            if header.get('name', '').lower() == 'subject':
                subject = header.get('value', '').lower()
                break
        
        has_keyword = any(kw in subject for kw in include_keywords)
        
        if has_keyword:
            sender_counts[sender_key] += 1
    
    # Check for HIGH confidence
    if sender_counts and max(sender_counts.values()) >= 3:
        return 'high'
    
    # Check for MEDIUM confidence
    if len(messages) >= 1:
        return 'medium'
    
    return 'low'


def update_target_from_messages(target: dict, messages: list, dry_run: bool = False) -> dict:
    """
    Update target based on discovered messages.
    
    Args:
        target: Target dict
        messages: List of matching Gmail messages
        dry_run: If True, don't modify target
    
    Returns:
        Updated target dict
    """
    target = target.copy()  # Don't mutate original
    
    if not messages:
        return target
    
    # Extract discovered senders
    discovered = set(target.get('discovered_senders', []))
    for msg in messages:
        email, domain = extract_sender_from_message(msg)
        if email:
            discovered.add(email)
        if domain:
            discovered.add(domain)
    
    target['discovered_senders'] = sorted(discovered)
    
    # Calculate confidence
    confidence = calculate_confidence(messages, target)
    target['sender_confidence'] = confidence
    
    # Update last_seen_at (most recent message)
    if messages:
        # Get internal date from most recent message
        internal_dates = []
        for msg in messages:
            internal_date = msg.get('internalDate')
            if internal_date:
                try:
                    internal_dates.append(int(internal_date))
                except (ValueError, TypeError):
                    pass
        
        if internal_dates:
            latest_timestamp = max(internal_dates) / 1000  # Convert from milliseconds
            target['last_seen_at'] = datetime.fromtimestamp(latest_timestamp, tz=timezone.utc).isoformat()
    
    # Update status
    current_status = target.get('status', 'todo')
    if current_status == 'todo' and confidence in ['medium', 'high']:
        target['status'] = 'subscribed_candidate'
    elif current_status == 'subscribed_candidate' and confidence == 'high':
        target['status'] = 'subscribed'
    
    return target


def build_target_query(target: dict, days: int) -> str:
    """
    Build Gmail query for a specific target.
    
    Args:
        target: Target dict
        days: Days to look back
    
    Returns:
        Gmail query string
    """
    query_parts = []
    
    # From domains/emails
    from_clauses = []
    expected_domains = target.get('expected_from_domains', [])
    expected_emails = target.get('expected_from_emails', [])
    discovered = target.get('discovered_senders', [])
    
    # Use discovered senders if available, else expected
    if discovered:
        for sender in discovered:
            if '@' in sender:
                from_clauses.append(f'from:{sender}')
            else:
                from_clauses.append(f'from:{sender}')
    elif expected_domains:
        for domain in expected_domains:
            from_clauses.append(f'from:{domain}')
    elif expected_emails:
        for email in expected_emails:
            from_clauses.append(f'from:{email}')
    
    if from_clauses:
        if len(from_clauses) > 1:
            query_parts.append(f'({" OR ".join(from_clauses)})')
        else:
            query_parts.append(from_clauses[0])
    
    # Date
    query_parts.append(f'newer_than:{days}d')
    
    return ' '.join(query_parts)


def list_messages_for_target(service, target: dict, days: int, max_results: int) -> list:
    """
    List Gmail messages matching target.
    
    Args:
        service: Gmail service object
        target: Target dict
        days: Days to look back
        max_results: Maximum messages
    
    Returns:
        List of message dicts
    """
    query = build_target_query(target, days)
    
    if not query:
        return []
    
    try:
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=min(max_results, 500)
        ).execute()
        
        messages = results.get('messages', [])
        
        # Fetch full messages
        full_messages = []
        for msg_info in messages:
            try:
                msg = service.users().messages().get(
                    userId='me',
                    id=msg_info['id'],
                    format='metadata',
                    metadataHeaders=['From', 'Subject', 'Date']
                ).execute()
                full_messages.append(msg)
            except Exception as e:
                print(f"Warning: Error fetching message {msg_info.get('id')}: {e}")
        
        return full_messages
    except Exception as e:
        print(f"Error listing messages for {target.get('id')}: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description='Update newsletter targets from Gmail')
    parser.add_argument('--days', type=int, default=30, help='Days to look back')
    parser.add_argument('--max-per-target', type=int, default=50, help='Max messages per target')
    parser.add_argument('--target-id', type=str, help='Process only this target ID')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no file writes)')
    args = parser.parse_args()
    
    # Load targets
    data = load_newsletter_targets()
    targets = data.get('targets', [])
    
    # Filter by target_id if specified
    if args.target_id:
        targets = [t for t in targets if t.get('id') == args.target_id]
        if not targets:
            print(f"Error: Target '{args.target_id}' not found")
            sys.exit(1)
    
    if args.dry_run:
        print(f"[DRY RUN] Processing {len(targets)} target(s)")
        print(f"[DRY RUN] Days: {args.days}, Max per target: {args.max_per_target}")
        print()
        
        # In dry-run, check credentials but exit gracefully if missing
        if not check_credentials_available():
            print("[DRY RUN] Gmail credentials not found (would require OAuth for actual run)")
            print("[DRY RUN] Would process targets if credentials were available")
            return 0
        print()
    
    # Check credentials (for actual run)
    if not check_credentials_available():
        print("Error: Gmail credentials not found")
        print("Please place credentials.json in backend/_secrets/")
        print("See README.md for setup instructions")
        sys.exit(1)
    
    # Get Gmail service
    service = get_gmail_service()
    if not service:
        print("Error: Failed to authenticate with Gmail")
        print("Please run the script again to complete OAuth flow")
        sys.exit(1)
    
    # Process each target
    updated_count = 0
    for target in targets:
        target_id = target.get('id', 'unknown')
        org_name = target.get('org_name', '')
        
        print(f"Processing: {org_name} ({target_id})")
        
        # List messages
        messages = list_messages_for_target(service, target, args.days, args.max_per_target)
        
        print(f"  Found {len(messages)} messages")
        
        # Filter messages that actually match target
        matching_messages = [msg for msg in messages if matches_target(msg, target)]
        
        print(f"  Matching: {len(matching_messages)} messages")
        
        if matching_messages:
            # Update target
            updated_target = update_target_from_messages(target, matching_messages, dry_run=args.dry_run)
            
            # Show changes
            old_status = target.get('status', 'todo')
            new_status = updated_target.get('status', 'todo')
            old_confidence = target.get('sender_confidence', 'low')
            new_confidence = updated_target.get('sender_confidence', 'low')
            
            if old_status != new_status:
                print(f"  Status: {old_status} -> {new_status}")
            if old_confidence != new_confidence:
                print(f"  Confidence: {old_confidence} -> {new_confidence}")
            
            discovered_count = len(updated_target.get('discovered_senders', []))
            print(f"  Discovered senders: {discovered_count}")
            
            # Update in data
            for i, t in enumerate(data['targets']):
                if t.get('id') == target_id:
                    if not args.dry_run:
                        data['targets'][i] = updated_target
                    updated_count += 1
                    break
        
        print()
    
    # Update timestamp
    if not args.dry_run and updated_count > 0:
        data['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        save_newsletter_targets(data)
        print(f"Updated {updated_count} target(s)")
    elif args.dry_run:
        print(f"[DRY RUN] Would update {updated_count} target(s)")
    
    print("Done")


if __name__ == '__main__':
    main()
