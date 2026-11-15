#!/usr/bin/env python3
"""
Newsletter Sender Discovery

Discovers actual senders/domains from emails matching newsletter targets.
Supports two modes:
- Local mode: Parse .eml files in backend/_email_ingest/
- Gmail mode: Search Gmail API for candidates

Outputs:
- backend/newsletter_sender_discovery.json (discovery results)
- md/NEWSLETTER_SENDER_DISCOVERY.md (human-readable report)
"""
import sys
import json
import argparse
import hashlib
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parseaddr
from email import policy
from email.parser import BytesParser

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def load_newsletter_targets() -> dict:
    """Load newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    if not targets_path.exists():
        return {'targets': []}
    
    try:
        with open(targets_path) as f:
            return json.load(f)
    except Exception:
        return {'targets': []}


def save_newsletter_targets(data: dict):
    """Save newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    data['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    with open(targets_path, 'w') as f:
        json.dump(data, f, indent=2)


def extract_domain(email: str) -> str:
    """Extract domain from email address."""
    if not email:
        return ''
    _, addr = parseaddr(email)
    if '@' in addr:
        return addr.split('@')[1].lower()
    return ''


def parse_eml_file(eml_path: Path) -> dict:
    """Parse a single .eml file and extract headers."""
    try:
        with open(eml_path, 'rb') as f:
            msg = BytesParser(policy=policy.default).parse(f)
        
        from_header = msg.get('From', '')
        reply_to = msg.get('Reply-To', '')
        subject = msg.get('Subject', '')
        date = msg.get('Date', '')
        list_id = msg.get('List-Id', '')
        list_unsubscribe = msg.get('List-Unsubscribe', '')
        
        _, from_email = parseaddr(from_header)
        from_domain = extract_domain(from_email)
        
        return {
            'file': str(eml_path.name),
            'from_email': from_email.lower() if from_email else '',
            'from_name': parseaddr(from_header)[0],
            'from_domain': from_domain,
            'reply_to': reply_to,
            'subject': subject,
            'date': date,
            'list_id': list_id,
            'list_unsubscribe': list_unsubscribe
        }
    except Exception as e:
        return {'file': str(eml_path.name), 'error': str(e)}


def match_sender_to_target(sender_info: dict, targets: list) -> list:
    """
    Match a sender to potential newsletter targets.
    
    Returns:
        List of target IDs that match
    """
    from_domain = sender_info.get('from_domain', '').lower()
    from_email = sender_info.get('from_email', '').lower()
    subject = sender_info.get('subject', '').lower()
    
    matches = []
    
    for target in targets:
        target_id = target.get('id', '')
        
        # Check domain match
        expected_domains = [d.lower() for d in target.get('expected_from_domains', [])]
        if from_domain and from_domain in expected_domains:
            matches.append(target_id)
            continue
        
        # Check if domain contains expected pattern
        for expected in expected_domains:
            if expected in from_domain or from_domain in expected:
                matches.append(target_id)
                break
        
        # Check email match
        expected_emails = [e.lower() for e in target.get('expected_from_emails', [])]
        if from_email and from_email in expected_emails:
            matches.append(target_id)
            continue
    
    return list(set(matches))


def calculate_confidence(sender_stats: dict, target: dict) -> str:
    """
    Calculate confidence level for a sender-target match.
    
    Rules:
    - high: sender appears >= 3 times AND matches expected domains OR has list headers
    - medium: appears >= 1 time AND matches expected domains
    - low: unknown domain but subject matches keywords
    """
    count = sender_stats.get('count', 0)
    domain = sender_stats.get('domain', '').lower()
    has_list_headers = sender_stats.get('has_list_headers', False)
    
    expected_domains = [d.lower() for d in target.get('expected_from_domains', [])]
    domain_match = any(exp in domain or domain in exp for exp in expected_domains)
    
    if count >= 3 and (domain_match or has_list_headers):
        return 'high'
    elif count >= 1 and domain_match:
        return 'medium'
    else:
        return 'low'


def discover_from_local(eml_dir: Path) -> dict:
    """
    Discover senders from local .eml files.
    
    Returns:
        Discovery results dict
    """
    results = {
        'mode': 'local',
        'source_dir': str(eml_dir),
        'discovered_at': datetime.now(timezone.utc).isoformat(),
        'total_emails': 0,
        'senders': {},
        'by_target': {}
    }
    
    if not eml_dir.exists():
        results['error'] = f"Directory not found: {eml_dir}"
        return results
    
    eml_files = list(eml_dir.glob('*.eml'))
    results['total_emails'] = len(eml_files)
    
    targets_data = load_newsletter_targets()
    targets = targets_data.get('targets', [])
    
    # Parse all emails
    all_parsed = []
    for eml_path in eml_files:
        parsed = parse_eml_file(eml_path)
        if 'error' not in parsed:
            all_parsed.append(parsed)
    
    # Aggregate by sender
    sender_stats = defaultdict(lambda: {
        'count': 0,
        'subjects': [],
        'dates': [],
        'domain': '',
        'has_list_headers': False,
        'target_matches': set()
    })
    
    for parsed in all_parsed:
        sender_key = parsed['from_email'] or parsed['from_domain']
        if not sender_key:
            continue
        
        stats = sender_stats[sender_key]
        stats['count'] += 1
        stats['domain'] = parsed['from_domain']
        stats['subjects'].append(parsed['subject'])
        stats['dates'].append(parsed['date'])
        stats['has_list_headers'] = stats['has_list_headers'] or bool(parsed['list_id'] or parsed['list_unsubscribe'])
        
        # Match to targets
        matches = match_sender_to_target(parsed, targets)
        stats['target_matches'].update(matches)
    
    # Convert to serializable format
    for sender_key, stats in sender_stats.items():
        results['senders'][sender_key] = {
            'count': stats['count'],
            'domain': stats['domain'],
            'subjects': stats['subjects'][:10],  # Limit
            'has_list_headers': stats['has_list_headers'],
            'target_matches': list(stats['target_matches'])
        }
    
    # Aggregate by target
    for target in targets:
        target_id = target.get('id')
        results['by_target'][target_id] = {
            'org_name': target.get('org_name', ''),
            'matched_senders': [],
            'confidence': 'low',
            'last_seen': None
        }
        
        for sender_key, stats in sender_stats.items():
            if target_id in stats['target_matches']:
                conf = calculate_confidence({
                    'count': stats['count'],
                    'domain': stats['domain'],
                    'has_list_headers': stats['has_list_headers']
                }, target)
                
                results['by_target'][target_id]['matched_senders'].append({
                    'sender': sender_key,
                    'count': stats['count'],
                    'confidence': conf
                })
                
                # Update overall confidence to highest
                if conf == 'high':
                    results['by_target'][target_id]['confidence'] = 'high'
                elif conf == 'medium' and results['by_target'][target_id]['confidence'] != 'high':
                    results['by_target'][target_id]['confidence'] = 'medium'
    
    return results


def discover_from_gmail(service, days: int = 30, max_results: int = 500, query_override: str = None) -> dict:
    """
    Discover senders from Gmail.
    
    Returns:
        Discovery results dict
    """
    results = {
        'mode': 'gmail',
        'days': days,
        'max_results': max_results,
        'discovered_at': datetime.now(timezone.utc).isoformat(),
        'total_emails': 0,
        'senders': {},
        'by_target': {}
    }
    
    targets_data = load_newsletter_targets()
    targets = targets_data.get('targets', [])
    
    # Build query: search for emails from expected domains
    if query_override:
        query = query_override
    else:
        # Build from targets
        domain_clauses = []
        for target in targets:
            for domain in target.get('expected_from_domains', []):
                domain_clauses.append(f'from:{domain}')
        
        if domain_clauses:
            query = f"({' OR '.join(domain_clauses)}) newer_than:{days}d"
        else:
            query = f"newer_than:{days}d"
    
    results['query'] = query
    
    try:
        # List messages
        response = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=min(max_results, 500)
        ).execute()
        
        messages = response.get('messages', [])
        results['total_emails'] = len(messages)
        
        # Fetch headers for each message
        sender_stats = defaultdict(lambda: {
            'count': 0,
            'subjects': [],
            'dates': [],
            'domain': '',
            'has_list_headers': False,
            'target_matches': set()
        })
        
        for msg_info in messages:
            try:
                msg = service.users().messages().get(
                    userId='me',
                    id=msg_info['id'],
                    format='metadata',
                    metadataHeaders=['From', 'Subject', 'Date', 'List-Id', 'List-Unsubscribe']
                ).execute()
                
                headers = msg.get('payload', {}).get('headers', [])
                
                from_header = ''
                subject = ''
                date = ''
                list_id = ''
                list_unsubscribe = ''
                
                for h in headers:
                    name = h.get('name', '').lower()
                    value = h.get('value', '')
                    if name == 'from':
                        from_header = value
                    elif name == 'subject':
                        subject = value
                    elif name == 'date':
                        date = value
                    elif name == 'list-id':
                        list_id = value
                    elif name == 'list-unsubscribe':
                        list_unsubscribe = value
                
                _, from_email = parseaddr(from_header)
                from_email = from_email.lower() if from_email else ''
                from_domain = extract_domain(from_email)
                
                sender_key = from_email or from_domain
                if not sender_key:
                    continue
                
                stats = sender_stats[sender_key]
                stats['count'] += 1
                stats['domain'] = from_domain
                stats['subjects'].append(subject)
                stats['dates'].append(date)
                stats['has_list_headers'] = stats['has_list_headers'] or bool(list_id or list_unsubscribe)
                stats['internal_date'] = msg.get('internalDate', '')
                
                # Match to targets
                parsed = {
                    'from_email': from_email,
                    'from_domain': from_domain,
                    'subject': subject
                }
                matches = match_sender_to_target(parsed, targets)
                stats['target_matches'].update(matches)
                
            except Exception as e:
                continue
        
        # Convert to serializable format
        for sender_key, stats in sender_stats.items():
            results['senders'][sender_key] = {
                'count': stats['count'],
                'domain': stats['domain'],
                'subjects': stats['subjects'][:10],
                'has_list_headers': stats['has_list_headers'],
                'target_matches': list(stats['target_matches'])
            }
        
        # Aggregate by target
        for target in targets:
            target_id = target.get('id')
            results['by_target'][target_id] = {
                'org_name': target.get('org_name', ''),
                'matched_senders': [],
                'confidence': 'low',
                'last_seen': None
            }
            
            for sender_key, stats in sender_stats.items():
                if target_id in stats['target_matches']:
                    conf = calculate_confidence({
                        'count': stats['count'],
                        'domain': stats['domain'],
                        'has_list_headers': stats['has_list_headers']
                    }, target)
                    
                    results['by_target'][target_id]['matched_senders'].append({
                        'sender': sender_key,
                        'count': stats['count'],
                        'confidence': conf
                    })
                    
                    if conf == 'high':
                        results['by_target'][target_id]['confidence'] = 'high'
                    elif conf == 'medium' and results['by_target'][target_id]['confidence'] != 'high':
                        results['by_target'][target_id]['confidence'] = 'medium'
                    
                    # Track last seen
                    if stats.get('internal_date'):
                        try:
                            ts = int(stats['internal_date']) / 1000
                            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                            results['by_target'][target_id]['last_seen'] = dt.isoformat()
                        except:
                            pass
        
    except Exception as e:
        results['error'] = str(e)
    
    return results


def apply_discovery_to_targets(discovery: dict, targets_data: dict) -> int:
    """
    Apply discovery results to newsletter_targets.json.
    
    Returns:
        Number of targets updated
    """
    updated_count = 0
    by_target = discovery.get('by_target', {})
    
    for target in targets_data.get('targets', []):
        target_id = target.get('id')
        if target_id not in by_target:
            continue
        
        target_discovery = by_target[target_id]
        matched_senders = target_discovery.get('matched_senders', [])
        
        if not matched_senders:
            continue
        
        # Update learned_senders / discovered_senders
        existing_learned = set(target.get('discovered_senders', []))
        for match in matched_senders:
            existing_learned.add(match['sender'])
        target['discovered_senders'] = sorted(existing_learned)
        
        # Update confidence
        new_confidence = target_discovery.get('confidence', 'low')
        old_confidence = target.get('sender_confidence', 'low')
        confidence_order = {'low': 0, 'medium': 1, 'high': 2}
        if confidence_order.get(new_confidence, 0) > confidence_order.get(old_confidence, 0):
            target['sender_confidence'] = new_confidence
        
        # Update last_seen_at
        if target_discovery.get('last_seen'):
            target['last_seen_at'] = target_discovery['last_seen']
        
        # Update status if appropriate
        if target.get('status') == 'todo' and new_confidence in ['medium', 'high']:
            target['status'] = 'subscribed'
        
        updated_count += 1
    
    return updated_count


def generate_discovery_report(discovery: dict) -> str:
    """Generate human-readable discovery report."""
    lines = []
    lines.append("# Newsletter Sender Discovery Report")
    lines.append("")
    lines.append(f"**Generated**: {discovery.get('discovered_at', 'N/A')}")
    lines.append(f"**Mode**: {discovery.get('mode', 'N/A')}")
    lines.append(f"**Total Emails Scanned**: {discovery.get('total_emails', 0)}")
    if discovery.get('query'):
        lines.append(f"**Query**: `{discovery.get('query')}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Summary by confidence
    by_target = discovery.get('by_target', {})
    high_conf = [t for t, d in by_target.items() if d.get('confidence') == 'high']
    medium_conf = [t for t, d in by_target.items() if d.get('confidence') == 'medium']
    low_conf = [t for t, d in by_target.items() if d.get('confidence') == 'low' and d.get('matched_senders')]
    no_match = [t for t, d in by_target.items() if not d.get('matched_senders')]
    
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **High confidence**: {len(high_conf)} targets")
    lines.append(f"- **Medium confidence**: {len(medium_conf)} targets")
    lines.append(f"- **Low confidence**: {len(low_conf)} targets")
    lines.append(f"- **No matches**: {len(no_match)} targets")
    lines.append("")
    
    # Discovered senders table
    lines.append("## Discovered Senders by Target")
    lines.append("")
    lines.append("| Target | Org | Confidence | Senders | Last Seen |")
    lines.append("|--------|-----|------------|---------|-----------|")
    
    for target_id, data in sorted(by_target.items(), key=lambda x: x[1].get('org_name', '')):
        org_name = data.get('org_name', '')
        confidence = data.get('confidence', 'low')
        senders = data.get('matched_senders', [])
        sender_str = ', '.join([s['sender'] for s in senders[:3]])
        if len(senders) > 3:
            sender_str += f' (+{len(senders) - 3})'
        if not sender_str:
            sender_str = '-'
        last_seen = data.get('last_seen', '-')
        if last_seen and last_seen != '-':
            try:
                dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                last_seen = dt.strftime('%Y-%m-%d')
            except:
                pass
        lines.append(f"| {target_id} | {org_name} | {confidence} | {sender_str} | {last_seen} |")
    
    lines.append("")
    
    # Sample subjects
    senders = discovery.get('senders', {})
    if senders:
        lines.append("## Sample Subjects by Sender")
        lines.append("")
        for sender, stats in sorted(senders.items(), key=lambda x: -x[1].get('count', 0))[:10]:
            lines.append(f"**{sender}** ({stats.get('count', 0)} emails):")
            for subj in stats.get('subjects', [])[:3]:
                lines.append(f"- {subj[:80]}{'...' if len(subj) > 80 else ''}")
            lines.append("")
    
    # Next actions
    lines.append("## Recommended Next Actions")
    lines.append("")
    
    if no_match:
        lines.append("**Targets with no discovered senders:**")
        for target_id in no_match[:5]:
            data = by_target.get(target_id, {})
            lines.append(f"- {data.get('org_name', target_id)}: Check subscription status, confirm email is arriving")
        lines.append("")
    
    if low_conf:
        lines.append("**Targets with low confidence:**")
        for target_id in low_conf[:5]:
            data = by_target.get(target_id, {})
            lines.append(f"- {data.get('org_name', target_id)}: Need more emails or verify expected domains")
        lines.append("")
    
    if high_conf:
        lines.append("**Targets ready for ingestion (high confidence):**")
        for target_id in high_conf:
            data = by_target.get(target_id, {})
            lines.append(f"- {data.get('org_name', target_id)}")
        lines.append("")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Discover newsletter senders')
    parser.add_argument('--days', type=int, default=30, help='Days to look back (Gmail mode)')
    parser.add_argument('--max', type=int, default=500, help='Max emails to scan')
    parser.add_argument('--query', type=str, help='Custom Gmail query')
    parser.add_argument('--local', action='store_true', help='Use local .eml files instead of Gmail')
    parser.add_argument('--apply', action='store_true', help='Apply discoveries to newsletter_targets.json')
    parser.add_argument('--report', action='store_true', help='Generate markdown report')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without writing')
    args = parser.parse_args()
    
    # Determine mode
    if args.local:
        print("Running in local mode (parsing .eml files)...")
        eml_dir = Path(backend_dir) / 'backend' / '_email_ingest'
        discovery = discover_from_local(eml_dir)
    else:
        # Try Gmail mode
        try:
            from backend.utils.gmail_auth import check_credentials_available, get_gmail_service
            
            if not check_credentials_available():
                print("Gmail credentials not found. Falling back to local mode...")
                print("(Place credentials.json in backend/_secrets/ for Gmail mode)")
                print()
                eml_dir = Path(backend_dir) / 'backend' / '_email_ingest'
                discovery = discover_from_local(eml_dir)
            else:
                service = get_gmail_service()
                if not service:
                    print("Failed to authenticate with Gmail. Falling back to local mode...")
                    eml_dir = Path(backend_dir) / 'backend' / '_email_ingest'
                    discovery = discover_from_local(eml_dir)
                else:
                    print(f"Running in Gmail mode (last {args.days} days, max {args.max} emails)...")
                    discovery = discover_from_gmail(service, args.days, args.max, args.query)
        except ImportError:
            print("Gmail libraries not available. Running in local mode...")
            eml_dir = Path(backend_dir) / 'backend' / '_email_ingest'
            discovery = discover_from_local(eml_dir)
    
    # Save discovery results
    discovery_path = Path(backend_dir) / 'backend' / 'newsletter_sender_discovery.json'
    if not args.dry_run:
        with open(discovery_path, 'w') as f:
            json.dump(discovery, f, indent=2)
        print(f"Discovery results saved to: {discovery_path}")
    else:
        print(f"[DRY RUN] Would save discovery to: {discovery_path}")
    
    # Apply to targets if requested
    if args.apply:
        targets_data = load_newsletter_targets()
        updated = apply_discovery_to_targets(discovery, targets_data)
        
        if not args.dry_run:
            save_newsletter_targets(targets_data)
            print(f"Updated {updated} target(s) in newsletter_targets.json")
        else:
            print(f"[DRY RUN] Would update {updated} target(s)")
    
    # Generate report if requested
    if args.report or args.dry_run:
        report = generate_discovery_report(discovery)
        
        report_path = Path(backend_dir) / 'md' / 'NEWSLETTER_SENDER_DISCOVERY.md'
        if not args.dry_run:
            report_path.parent.mkdir(exist_ok=True)
            with open(report_path, 'w') as f:
                f.write(report)
            print(f"Report saved to: {report_path}")
        
        # Print summary
        print()
        print("=" * 60)
        print("DISCOVERY SUMMARY")
        print("=" * 60)
        print(f"Mode: {discovery.get('mode', 'N/A')}")
        print(f"Total emails: {discovery.get('total_emails', 0)}")
        print(f"Unique senders: {len(discovery.get('senders', {}))}")
        print()
        
        by_target = discovery.get('by_target', {})
        high = sum(1 for d in by_target.values() if d.get('confidence') == 'high')
        medium = sum(1 for d in by_target.values() if d.get('confidence') == 'medium')
        low = sum(1 for d in by_target.values() if d.get('matched_senders') and d.get('confidence') == 'low')
        none = sum(1 for d in by_target.values() if not d.get('matched_senders'))
        
        print(f"High confidence targets: {high}")
        print(f"Medium confidence targets: {medium}")
        print(f"Low confidence targets: {low}")
        print(f"No match targets: {none}")
        print("=" * 60)


if __name__ == '__main__':
    main()
