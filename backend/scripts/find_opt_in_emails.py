#!/usr/bin/env python3
"""
Opt-In Email Finder

Searches Gmail for confirmation/double opt-in emails and extracts
confirmation links for human verification.

Does NOT click confirmation links - presents them for manual action.
"""
import sys
import json
import argparse
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional
from email.utils import parseaddr

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


# Confirmation email subject patterns
OPT_IN_SUBJECT_PATTERNS = [
    r'confirm', r'verify', r'activate', r'complete.*registration',
    r'welcome', r'subscription', r'please.*confirm', r'action required'
]

# Confirmation link patterns
CONFIRM_LINK_PATTERNS = [
    r'confirm', r'verify', r'activate', r'opt-in', r'subscribe',
    r'unsubscribe',  # Sometimes confirmation is in same email
    r'click here', r'click to confirm'
]


def load_newsletter_targets() -> dict:
    """Load newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    if not targets_path.exists():
        return {'targets': []}
    with open(targets_path) as f:
        return json.load(f)


def extract_domain(email: str) -> str:
    """Extract domain from email address."""
    if not email:
        return ''
    _, addr = parseaddr(email)
    if '@' in addr:
        return addr.split('@')[1].lower()
    return ''


def extract_links_from_html(html: str) -> List[Dict]:
    """Extract all links from HTML with context."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
    except ImportError:
        # Fallback to regex
        links = re.findall(r'href=["\']([^"\']+)["\']', html)
        return [{'url': link, 'text': ''} for link in links if link.startswith('http')]
    
    links = []
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        if not href.startswith('http'):
            continue
        
        text = a.get_text(strip=True)
        links.append({'url': href, 'text': text[:100]})
    
    return links


def is_confirmation_link(url: str, text: str) -> bool:
    """Check if a link looks like a confirmation link."""
    combined = (url + ' ' + text).lower()
    
    for pattern in CONFIRM_LINK_PATTERNS:
        if re.search(pattern, combined):
            return True
    
    # Check for typical confirmation URL patterns
    if '/confirm' in url.lower() or '/verify' in url.lower():
        return True
    if 'token=' in url.lower() or 'key=' in url.lower():
        return True
    
    return False


def match_email_to_target(from_addr: str, subject: str, targets: List[Dict]) -> Optional[str]:
    """Match an email to a newsletter target based on sender domain."""
    from_domain = extract_domain(from_addr)
    
    for target in targets:
        expected_domains = [d.lower() for d in target.get('expected_from_domains', [])]
        discovered = [d.lower() for d in target.get('discovered_senders', [])]
        
        # Check domain match
        for domain in expected_domains + discovered:
            if domain in from_domain or from_domain in domain:
                return target.get('id')
    
    return None


def search_opt_in_emails(service, days: int = 14, max_results: int = 100) -> List[Dict]:
    """
    Search Gmail for opt-in confirmation emails.
    
    Returns:
        List of opt-in email candidates
    """
    # Build query for confirmation emails
    query_parts = [
        f'newer_than:{days}d',
        '(subject:confirm OR subject:verify OR subject:activate OR subject:subscription OR subject:"action required")',
        '-category:promotions'
    ]
    query = ' '.join(query_parts)
    
    results = []
    
    try:
        response = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()
        
        messages = response.get('messages', [])
        
        for msg_info in messages:
            try:
                msg = service.users().messages().get(
                    userId='me',
                    id=msg_info['id'],
                    format='full'
                ).execute()
                
                # Extract headers
                headers = msg.get('payload', {}).get('headers', [])
                from_addr = ''
                subject = ''
                date = ''
                
                for h in headers:
                    name = h.get('name', '').lower()
                    if name == 'from':
                        from_addr = h.get('value', '')
                    elif name == 'subject':
                        subject = h.get('value', '')
                    elif name == 'date':
                        date = h.get('value', '')
                
                # Get body
                body_html = ''
                body_text = ''
                
                def extract_body(payload):
                    nonlocal body_html, body_text
                    if 'body' in payload and payload['body'].get('data'):
                        import base64
                        data = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
                        if payload.get('mimeType') == 'text/html':
                            body_html = data
                        else:
                            body_text = data
                    if 'parts' in payload:
                        for part in payload['parts']:
                            extract_body(part)
                
                extract_body(msg.get('payload', {}))
                
                # Extract confirmation links
                links = extract_links_from_html(body_html or body_text)
                confirm_links = [l for l in links if is_confirmation_link(l['url'], l['text'])]
                
                if confirm_links:
                    results.append({
                        'gmail_id': msg_info['id'],
                        'from': from_addr,
                        'subject': subject,
                        'date': date,
                        'confirm_links': confirm_links[:5],  # Limit to 5
                        'internal_date': msg.get('internalDate', '')
                    })
                
            except Exception:
                continue
        
    except Exception as e:
        print(f"Error searching Gmail: {e}")
    
    return results


def save_opt_in_queue(emails: List[Dict], targets: List[Dict]) -> str:
    """Save opt-in queue to JSON and return path."""
    queue = []
    
    for email in emails:
        target_id = match_email_to_target(email['from'], email['subject'], targets)
        
        queue.append({
            'target_id': target_id,
            'gmail_id': email['gmail_id'],
            'from': email['from'],
            'subject': email['subject'],
            'confirm_links': email['confirm_links'],
            'evidence_path': ''
        })
    
    queue_path = Path(backend_dir) / 'backend' / 'opt_in_queue.json'
    with open(queue_path, 'w') as f:
        json.dump({
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'queue': queue
        }, f, indent=2)
    
    return str(queue_path)


def main():
    parser = argparse.ArgumentParser(description='Find opt-in confirmation emails')
    parser.add_argument('--days', type=int, default=14, help='Days to look back')
    parser.add_argument('--max', type=int, default=100, help='Max emails to scan')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no Gmail API calls)')
    args = parser.parse_args()
    
    targets_data = load_newsletter_targets()
    targets = targets_data.get('targets', [])
    
    print(f"Searching for opt-in emails (last {args.days} days)")
    print()
    
    if args.dry_run:
        print("[DRY RUN] Would search Gmail for confirmation emails")
        print("[DRY RUN] Would look for patterns: confirm, verify, activate, subscription")
        print("[DRY RUN] Would extract confirmation links for manual action")
        return 0
    
    # Check Gmail credentials
    try:
        from backend.utils.gmail_auth import check_credentials_available, get_gmail_service
        
        if not check_credentials_available():
            print("Gmail credentials not found")
            print("Place credentials.json in backend/_secrets/")
            return 1
        
        service = get_gmail_service()
        if not service:
            print("Failed to authenticate with Gmail")
            return 1
        
    except ImportError:
        print("Gmail utilities not available")
        return 1
    
    # Search for opt-in emails
    emails = search_opt_in_emails(service, args.days, args.max)
    
    print(f"Found {len(emails)} potential opt-in email(s)")
    print()
    
    if not emails:
        print("No confirmation emails found")
        return 0
    
    # Save queue
    queue_path = save_opt_in_queue(emails, targets)
    print(f"Queue saved to: {queue_path}")
    print()
    
    # Print summary
    print("=" * 60)
    print("OPT-IN CONFIRMATION QUEUE")
    print("=" * 60)
    print()
    print("DO NOT click links automatically. Review and confirm manually.")
    print()
    
    for email in emails:
        target_id = match_email_to_target(email['from'], email['subject'], targets)
        
        print(f"From: {email['from']}")
        print(f"Subject: {email['subject']}")
        print(f"Target: {target_id or 'UNKNOWN'}")
        print("Confirmation links:")
        for link in email['confirm_links'][:3]:
            print(f"  - {link['url'][:80]}...")
        print()
    
    print("=" * 60)
    print(f"Total: {len(emails)} email(s) with confirmation links")
    print()
    print("After confirming manually, run:")
    print("  python backend/scripts/mark_opt_in_confirmed.py --target-id <id>")
    print("=" * 60)


if __name__ == '__main__':
    sys.exit(main() or 0)
