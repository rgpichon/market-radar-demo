#!/usr/bin/env python3
"""
Gmail Ingestion Script

Read-only Gmail API ingestion for macro-signal event invitations.
"""
import sys
import argparse
import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.utils.gmail_auth import get_gmail_service, check_credentials_available
from backend.utils.gmail_parse import parse_gmail_message
from backend.utils.gmail_event_extract import extract_events_from_gmail_message, save_gmail_evidence
from backend.db import get_db, upsert_event, is_email_ingested, record_ingested_email
from backend.utils.contracts import normalize_event
from backend.utils.newsletter_quality import update_newsletter_quality_stats
from datetime import datetime, timezone


def update_sender_stats(sender_email: str, newsletter_id: str = None, intel_extracted: bool = False, rejected: bool = False):
    """
    Update sender statistics (PHASE 4).
    
    Args:
        sender_email: Sender email address
        newsletter_id: Optional newsletter target ID
        intel_extracted: Whether intel was extracted from this email
        rejected: Whether email was rejected
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Get current stats
    cursor.execute("""
        SELECT emails_seen, intel_items_extracted, rejection_rate, promotion_level
        FROM sender_stats
        WHERE sender_email = ?
    """, (sender_email,))
    
    row = cursor.fetchone()
    if row:
        emails_seen = row['emails_seen'] or 0
        intel_items = row['intel_items_extracted'] or 0
        rejection_rate = row['rejection_rate'] or 0.0
        promotion_level = row['promotion_level'] or 'unknown'
    else:
        emails_seen = 0
        intel_items = 0
        rejection_rate = 0.0
        promotion_level = 'unknown'
    
    # Update counts
    emails_seen += 1
    if intel_extracted:
        intel_items += 1
    if rejected:
        # Update rejection rate
        total_processed = emails_seen
        if total_processed > 0:
            current_rejections = rejection_rate * (total_processed - 1)
            rejection_rate = (current_rejections + 1) / total_processed
    
    # Recalculate rejection rate
    if emails_seen > 0:
        rejection_rate = 1.0 - (intel_items / emails_seen)
    
    # Determine promotion level (PHASE 4)
    if emails_seen >= 3 and rejection_rate < 0.2 and intel_items >= 2:
        promotion_level = 'strict'
    elif emails_seen >= 2 and rejection_rate < 0.3 and intel_items >= 1:
        promotion_level = 'high'
    elif emails_seen >= 1 and rejection_rate < 0.5:
        promotion_level = 'medium'
    elif rejection_rate > 0.8 or (emails_seen >= 5 and intel_items == 0):
        promotion_level = 'low'
    else:
        promotion_level = 'unknown'
    
    # Upsert stats
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO sender_stats
        (sender_email, newsletter_id, emails_seen, intel_items_extracted, rejection_rate, 
         promotion_level, last_seen, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (sender_email, newsletter_id, emails_seen, intel_items, rejection_rate, 
          promotion_level, now, now))
    
    conn.commit()
    conn.close()


def load_newsletter_targets() -> dict:
    """
    Load newsletter targets registry.
    
    Returns:
        Newsletter targets dict or None if file doesn't exist
    """
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    if not targets_path.exists():
        return None
    
    try:
        with open(targets_path) as f:
            return json.load(f)
    except Exception:
        return None


def get_targets_allowlist(targets_data: dict = None) -> tuple[list, list]:
    """
    Extract allowlist domains and emails from subscribed newsletter targets.
    
    Args:
        targets_data: Newsletter targets dict (if None, loads from file)
    
    Returns:
        Tuple of (domains_list, emails_list)
    """
    if targets_data is None:
        targets_data = load_newsletter_targets()
    
    if not targets_data:
        return [], []
    
    targets = targets_data.get('targets', [])
    domains = set()
    emails = set()
    
    for target in targets:
        if target.get('status') == 'subscribed':
            domains.update(target.get('expected_from_domains', []))
            emails.update(target.get('expected_from_emails', []))
    
    return sorted(domains), sorted(emails)


def load_gmail_config(config_path: Path = None) -> dict:
    """
    Load Gmail ingestion config.
    
    Args:
        config_path: Path to config file (default: backend/gmail_ingestion_config.json)
    
    Returns:
        Config dict
    """
    if config_path is None:
        config_path = Path(backend_dir) / 'backend' / 'gmail_ingestion_config.json'
    
    if not config_path.exists():
        # Return defaults
        return {
            'include_labels': ['inbox', 'important'],
            'exclude_categories': ['promotions', 'social'],
            'newer_than_days_default': 30,
            'must_have_ics': False,
            'include_keywords': ['webinar', 'roundtable', 'forum', 'panel', 'briefing', 'conference', 'summit'],
            'exclude_keywords': ['earnings', 'results', 'quarterly', 'press release'],
            'from_allowlist': [],
            'from_blocklist': [],
            'subject_allowlist_keywords': [],
            'subject_blocklist_keywords': []
        }
    
    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception:
        return load_gmail_config(None)  # Fallback to defaults


def build_gmail_query(days: int = 30, custom_query: str = None, config: dict = None, use_newsletter_targets: bool = False, mode: str = 'default', targets_mode: str = 'lenient', priority: str = None) -> str:
    """
    Build Gmail API query string from config.
    
    Args:
        days: Number of days to look back
        custom_query: Custom query override
        config: Gmail config dict
        use_newsletter_targets: If True, extend allowlist from newsletter_targets.json
        mode: 'default' or 'targets'
        targets_mode: 'strict' (require learned_senders) or 'lenient' (use expected domains)
    
    Returns:
        Gmail query string
    """
    if custom_query:
        return custom_query
    
    if config is None:
        config = load_gmail_config()
    
    # Targets mode: build query from newsletter targets
    if mode == 'targets':
        from backend.utils.target_filter import filter_newsletter_targets
        
        targets_data = load_newsletter_targets()
        if targets_data:
            all_targets = targets_data.get('targets', [])
            
            # Filter targets: only newsletter/both mode, subscribed/confirmed, enforce governance
            filtered_targets, _ = filter_newsletter_targets(
                all_targets,
                priority=priority,
                include_statuses=['subscribed', 'confirmed'],
                enforce_governance=True,
                acquisition_mode='newsletter'  # Only process newsletter targets (not events_portal-only)
            )
            
            # Collect senders based on targets_mode
            all_domains = set()
            all_emails = set()
            include_keywords = set()
            exclude_keywords = set()
            
            for target in filtered_targets:
                discovered = target.get('discovered_senders', [])
                expected_domains = target.get('expected_from_domains', [])
                
                # Strict mode: only use targets with discovered senders
                if targets_mode == 'strict':
                    if not discovered:
                        continue
                    # Use discovered senders only
                    for sender in discovered:
                        if '@' in sender:
                            all_emails.add(sender.lower())
                            all_domains.add(sender.split('@')[1].lower())
                        else:
                            all_domains.add(sender.lower())
                else:
                    # Lenient mode: use discovered if available, else expected domains
                    if discovered:
                        for sender in discovered:
                            if '@' in sender:
                                all_emails.add(sender.lower())
                                all_domains.add(sender.split('@')[1].lower())
                            else:
                                all_domains.add(sender.lower())
                    else:
                        # Fall back to expected domains
                        for domain in expected_domains:
                            all_domains.add(domain.lower())
                
                # Aggregate keywords from all targets
                include_keywords.update(target.get('subject_include_any', []))
                exclude_keywords.update(target.get('subject_exclude_any', []))
            
            # Merge with config
            config = config.copy()
            existing_allowlist = set(config.get('from_allowlist', []))
            existing_allowlist.update(all_domains)
            existing_allowlist.update(all_emails)
            config['from_allowlist'] = sorted(existing_allowlist)
            
            # Merge keywords
            existing_include = set(config.get('include_keywords', []))
            existing_include.update(include_keywords)
            config['include_keywords'] = sorted(existing_include)
            
            existing_exclude = set(config.get('exclude_keywords', []))
            existing_exclude.update(exclude_keywords)
            config['exclude_keywords'] = sorted(existing_exclude)
    
    # Extend allowlist from newsletter targets if requested (legacy flag)
    elif use_newsletter_targets:
        targets_data = load_newsletter_targets()
        if targets_data:
            domains, emails = get_targets_allowlist(targets_data)
            # Merge with existing allowlist
            existing_domains = set(config.get('from_allowlist', []))
            existing_domains.update(domains)
            existing_domains.update(emails)  # Emails can also go in from_allowlist
            config = config.copy()  # Don't mutate original
            config['from_allowlist'] = sorted(existing_domains)
    
    query_parts = []
    
    # Labels
    include_labels = config.get('include_labels', ['inbox', 'important'])
    if include_labels:
        label_clauses = [f'label:{label}' for label in include_labels]
        if len(label_clauses) > 1:
            query_parts.append(f'({" OR ".join(label_clauses)})')
        else:
            query_parts.append(label_clauses[0])
    
    # Date
    query_parts.append(f'newer_than:{days}d')
    
    # Exclude categories
    exclude_categories = config.get('exclude_categories', [])
    for cat in exclude_categories:
        query_parts.append(f'-category:{cat}')
    
    # Include keywords or ICS requirement
    must_have_ics = config.get('must_have_ics', False)
    include_keywords = config.get('include_keywords', [])
    
    if must_have_ics:
        query_parts.append('has:attachment filename:ics')
    else:
        # ICS OR keywords
        keyword_clauses = []
        if include_keywords:
            # Group keywords into quoted phrases
            keyword_clauses = [f'"{kw}"' for kw in include_keywords[:10]]  # Limit to avoid query length
        keyword_clauses.append('has:attachment filename:ics')
        if len(keyword_clauses) > 1:
            query_parts.append(f'({" OR ".join(keyword_clauses)})')
        else:
            query_parts.append(keyword_clauses[0])
    
    # From allowlist
    from_allowlist = config.get('from_allowlist', [])
    if from_allowlist:
        from_clauses = [f'from:{addr}' for addr in from_allowlist]
        if len(from_clauses) > 1:
            query_parts.append(f'({" OR ".join(from_clauses)})')
        else:
            query_parts.append(from_clauses[0])
    
    # From blocklist
    from_blocklist = config.get('from_blocklist', [])
    for addr in from_blocklist:
        query_parts.append(f'-from:{addr}')
    
    # Exclude keywords
    exclude_keywords = config.get('exclude_keywords', [])
    if exclude_keywords:
        exclude_clauses = [f'"{kw}"' for kw in exclude_keywords[:5]]  # Limit
        if len(exclude_clauses) > 1:
            query_parts.append(f'-({" OR ".join(exclude_clauses)})')
        else:
            query_parts.append(f'-{exclude_clauses[0]}')
    
    return ' '.join(query_parts)


def explain_query(query: str, config: dict) -> str:
    """
    Generate human-readable explanation of query.
    
    Args:
        query: Gmail query string
        config: Config dict used
    
    Returns:
        Explanation string
    """
    lines = []
    lines.append("Query Explanation:")
    lines.append("")
    
    if 'label:' in query:
        labels = config.get('include_labels', [])
        lines.append(f"- Include labels: {', '.join(labels)}")
    
    if 'newer_than:' in query:
        import re
        match = re.search(r'newer_than:(\d+)d', query)
        if match:
            lines.append(f"- Look back: {match.group(1)} days")
    
    if '-category:' in query:
        categories = config.get('exclude_categories', [])
        lines.append(f"- Exclude categories: {', '.join(categories)}")
    
    if 'has:attachment filename:ics' in query:
        if config.get('must_have_ics'):
            lines.append("- Require ICS attachment")
        else:
            lines.append("- Include ICS attachments OR keywords")
    
    include_keywords = config.get('include_keywords', [])
    if include_keywords:
        lines.append(f"- Include keywords: {', '.join(include_keywords[:5])}...")
    
    exclude_keywords = config.get('exclude_keywords', [])
    if exclude_keywords:
        lines.append(f"- Exclude keywords: {', '.join(exclude_keywords[:5])}...")
    
    from_allowlist = config.get('from_allowlist', [])
    if from_allowlist:
        lines.append(f"- From allowlist: {', '.join(from_allowlist)}")
    
    from_blocklist = config.get('from_blocklist', [])
    if from_blocklist:
        lines.append(f"- From blocklist: {', '.join(from_blocklist)}")
    
    return '\n'.join(lines)


def list_messages(service, query: str, max_results: int = 200) -> list:
    """
    List Gmail message IDs matching query.
    
    Args:
        service: Gmail service object
        query: Gmail query string
        max_results: Maximum number of messages
    
    Returns:
        List of message dicts with 'id' and 'threadId'
    """
    try:
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=min(max_results, 500)  # Gmail API limit
        ).execute()
        
        messages = results.get('messages', [])
        return messages
    except Exception as e:
        print(f"Error listing messages: {e}")
        return []


def get_message(service, message_id: str) -> dict:
    """
    Get full message by ID.
    
    Args:
        service: Gmail service object
        message_id: Message ID
    
    Returns:
        Message dict
    """
    try:
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()
        return message
    except Exception as e:
        print(f"Error getting message {message_id}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Ingest macro-signal events from Gmail')
    parser.add_argument('--query', type=str, help='Custom Gmail query (overrides config)')
    parser.add_argument('--max', type=int, default=200, help='Maximum messages to process')
    parser.add_argument('--days', type=int, default=30, help='Days to look back')
    parser.add_argument('--config', type=str, help='Path to gmail_ingestion_config.json')
    parser.add_argument('--print-default-query', action='store_true', help='Print default query and exit')
    parser.add_argument('--explain-query', action='store_true', help='Print query explanation and exit')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no DB writes)')
    parser.add_argument('--report-only', action='store_true', help='Print last run report and exit')
    parser.add_argument('--use-newsletter-targets', action='store_true', help='Extend allowlist from newsletter_targets.json (legacy)')
    parser.add_argument('--print-targets-allowlist', action='store_true', help='Print allowlist from subscribed newsletter targets and exit')
    parser.add_argument('--mode', type=str, choices=['default', 'targets'], default='targets', help='Ingestion mode: default (config-based) or targets (targets-driven)')
    parser.add_argument('--targets-mode', type=str, choices=['strict', 'lenient'], default='lenient', dest='targets_mode', help='Targets mode: strict (require learned_senders) or lenient (use expected domains)')
    parser.add_argument('--print-live-plan', action='store_true', help='Print ingestion plan without credentials (targets, senders, query)')
    parser.add_argument('--print-query-components', action='store_true', help='Print query components breakdown (no credentials)')
    args = parser.parse_args()
    
    # Auto-enable use_newsletter_targets when mode is targets
    if args.mode == 'targets':
        args.use_newsletter_targets = True
    
    # Load config
    config_path = None
    if args.config:
        config_path = Path(args.config)
    config = load_gmail_config(config_path)
    
    # Print targets allowlist and exit
    if args.print_targets_allowlist:
        targets_data = load_newsletter_targets()
        if not targets_data:
            print("No newsletter_targets.json found")
            return 0
        
        domains, emails = get_targets_allowlist(targets_data)
        print("Newsletter Targets Allowlist:")
        print()
        if domains:
            print("Domains:")
            for domain in domains:
                print(f"  {domain}")
            print()
        if emails:
            print("Email Addresses:")
            for email in emails:
                print(f"  {email}")
            print()
        if not domains and not emails:
            print("No subscribed targets found. Allowlist is empty.")
        return 0
    
    # Print query components (no credentials required)
    if args.print_query_components:
        from backend.utils.target_filter import filter_newsletter_targets
        
        targets_data = load_newsletter_targets()
        if not targets_data:
            print("No newsletter targets found")
            return 0
        
        all_targets = targets_data.get('targets', [])
        filtered_targets, _ = filter_newsletter_targets(
            all_targets,
            priority=None,
            include_statuses=['subscribed', 'confirmed'],
            enforce_governance=True
        )
        
        # Collect components
        allowlist_senders = set()
        allowlist_domains = set()
        include_keywords = set()
        exclude_keywords = set()
        
        for target in filtered_targets:
            discovered = target.get('discovered_senders', [])
            expected_domains = target.get('expected_from_domains', [])
            
            if args.targets_mode == 'strict':
                if discovered:
                    for sender in discovered:
                        if '@' in sender:
                            allowlist_senders.add(sender.lower())
                            allowlist_domains.add(sender.split('@')[1].lower())
                        else:
                            allowlist_domains.add(sender.lower())
            else:  # lenient
                if discovered:
                    for sender in discovered:
                        if '@' in sender:
                            allowlist_senders.add(sender.lower())
                            allowlist_domains.add(sender.split('@')[1].lower())
                        else:
                            allowlist_domains.add(sender.lower())
                else:
                    for domain in expected_domains:
                        allowlist_domains.add(domain.lower())
            
            include_keywords.update(target.get('subject_include_any', []))
            exclude_keywords.update(target.get('subject_exclude_any', []))
        
        # Merge with config
        config_keywords_include = set(config.get('include_keywords', []))
        config_keywords_exclude = set(config.get('exclude_keywords', []))
        include_keywords.update(config_keywords_include)
        exclude_keywords.update(config_keywords_exclude)
        
        print("=" * 60)
        print("QUERY COMPONENTS BREAKDOWN")
        print("=" * 60)
        print()
        print(f"Allowlist senders: {len(allowlist_senders)}")
        if allowlist_senders:
            sample = sorted(list(allowlist_senders))[:5]
            print(f"  Sample: {', '.join(sample)}{'...' if len(allowlist_senders) > 5 else ''}")
        print()
        print(f"Allowlist domains: {len(allowlist_domains)}")
        if allowlist_domains:
            sample = sorted(list(allowlist_domains))[:10]
            print(f"  Sample: {', '.join(sample)}{'...' if len(allowlist_domains) > 10 else ''}")
        print()
        print(f"Include keywords: {len(include_keywords)}")
        if include_keywords:
            sample = sorted(list(include_keywords))[:10]
            print(f"  Sample: {', '.join(sample)}{'...' if len(include_keywords) > 10 else ''}")
        print()
        print(f"Exclude keywords: {len(exclude_keywords)}")
        if exclude_keywords:
            sample = sorted(list(exclude_keywords))[:10]
            print(f"  Sample: {', '.join(sample)}{'...' if len(exclude_keywords) > 10 else ''}")
        print()
        
        # Build and show final query
        query = build_gmail_query(
            days=args.days,
            custom_query=None,
            config=config,
            use_newsletter_targets=False,
            mode=args.mode,
            targets_mode=args.targets_mode,
            priority=None
        )
        print("Final query:")
        print(f"  {query}")
        print("=" * 60)
        return 0
    
    # Build query
    query = build_gmail_query(days=args.days, custom_query=args.query, config=config, use_newsletter_targets=args.use_newsletter_targets, mode=args.mode, targets_mode=args.targets_mode, priority=None)
    
    # Print default query and exit
    if args.print_default_query:
        print(query)
        return 0
    
    # Explain query and exit
    if args.explain_query:
        print(explain_query(query, config))
        return 0
    
    # Print live plan (no credentials required)
    if args.print_live_plan:
        from backend.utils.target_filter import filter_newsletter_targets
        
        targets_data = load_newsletter_targets()
        if not targets_data:
            print("No newsletter targets found")
            return 0
        
        all_targets = targets_data.get('targets', [])
        
        # Use canonical filter (same as query building)
        filtered_targets, breakdown = filter_newsletter_targets(
            all_targets,
            priority=None,  # All priorities for plan
            include_statuses=['subscribed', 'confirmed'],
            enforce_governance=True
        )
        
        print("=" * 60)
        print("GMAIL INGESTION PLAN")
        print("=" * 60)
        print()
        
        # Diagnostics section
        print("DIAGNOSTICS (no credentials required):")
        print(f"  Total targets loaded: {breakdown['total_loaded']}")
        print(f"  After priority filter: {breakdown['after_priority_filter']}")
        print(f"  After status filter (subscribed/confirmed): {breakdown['after_status_filter']}")
        print(f"  After governance filter: {breakdown['after_governance_filter']}")
        print(f"  Blocked by governance: {breakdown['blocked_count']}")
        if breakdown['blocked_reasons']:
            print("  Blocked reasons:")
            for reason, count in breakdown['blocked_reasons'].items():
                print(f"    - {reason}: {count}")
        print()
        
        # Status histogram
        if breakdown['status_counts']:
            print("Status distribution:")
            for status, count in sorted(breakdown['status_counts'].items()):
                print(f"  {status}: {count}")
            print()
        
        # Sample targets (first 10)
        print("Sample targets considered (first 10):")
        for i, target in enumerate(filtered_targets[:10]):
            target_id = target.get('id', 'unknown')
            org = target.get('org_name', 'Unknown')
            status = target.get('status', 'unknown')
            priority = target.get('priority', '')
            expected_domains = target.get('expected_from_domains', [])
            learned_senders = target.get('discovered_senders', [])
            signup_url = target.get('signup_url', '')
            has_url = bool(signup_url and signup_url not in ['FILL_ME', 'AUTO_DISCOVER'])
            
            from backend.db import is_paused_or_cooldown
            is_blocked, block_reason = is_paused_or_cooldown(target_id)
            
            print(f"  {i+1}. {org} ({target_id})")
            print(f"     status={status}, priority={priority}, domains={len(expected_domains)}, senders={len(learned_senders)}, url={has_url}, blocked={is_blocked}")
            if is_blocked:
                print(f"     block_reason: {block_reason}")
        if len(filtered_targets) > 10:
            print(f"  ... and {len(filtered_targets) - 10} more")
        print()
        
        # Analyze targets for query building
        learned_senders_count = 0
        expected_domains_count = 0
        targets_with_senders = []
        targets_with_domains = []
        
        for target in filtered_targets:
            discovered = target.get('discovered_senders', [])
            expected = target.get('expected_from_domains', [])
            
            if discovered:
                learned_senders_count += len(discovered)
                targets_with_senders.append({
                    'org': target.get('org_name'),
                    'id': target.get('id'),
                    'senders': discovered[:3]
                })
            elif expected:
                expected_domains_count += len(expected)
                targets_with_domains.append({
                    'org': target.get('org_name'),
                    'id': target.get('id'),
                    'domains': expected[:3]
                })
        
        print("QUERY BUILDING SUMMARY:")
        print(f"  Subscribed/confirmed targets (after governance): {len(filtered_targets)}")
        print(f"  Targets with learned senders: {len(targets_with_senders)}")
        print(f"  Targets with expected domains only: {len(targets_with_domains)}")
        print()
        
        if targets_with_senders:
            print("Targets contributing learned senders:")
            for t in targets_with_senders:
                print(f"  - {t['org']} ({t['id']}): {', '.join(t['senders'][:2])}{'...' if len(t['senders']) > 2 else ''}")
            print()
        
        if targets_with_domains:
            print("Targets contributing expected domains:")
            for t in targets_with_domains:
                print(f"  - {t['org']} ({t['id']}): {', '.join(t['domains'][:2])}{'...' if len(t['domains']) > 2 else ''}")
            print()
        
        # Build query to show
        query = build_gmail_query(
            days=args.days,
            custom_query=None,
            config=config,
            use_newsletter_targets=False,
            mode=args.mode,
            targets_mode=args.targets_mode,
            priority=None
        )
        
        print("Query:")
        print(f"  {query}")
        print()
        
        # Expected next steps
        if learned_senders_count == 0 and expected_domains_count == 0:
            print("⚠️  Next steps: Subscribe to newsletters first, then run sender discovery")
        elif learned_senders_count == 0:
            print("⚠️  Next steps: Run sender discovery to learn actual sender addresses")
            print("   Command: python backend/scripts/discover_newsletter_senders.py --days 30 --apply")
        else:
            print("✓ Ready for ingestion: Learned senders available")
        
        print("=" * 60)
        return 0
    
    # Report only
    if args.report_only:
        report_dir = Path(backend_dir) / 'backend' / '_evidence' / 'email' / 'run_reports'
        if report_dir.exists():
            reports = sorted(report_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
            if reports:
                with open(reports[0]) as f:
                    report = json.load(f)
                print(f"Last run: {reports[0].name}")
                print(f"Scanned: {report.get('scanned', 0)}")
                print(f"Ingested: {report.get('ingested', 0)}")
                print(f"Rejected: {report.get('rejected', 0)}")
                print(f"Skipped (dedup): {report.get('skipped_dedup', 0)}")
                return 0
        print("No run reports found")
        return 0
    
    # For dry-run, print config and query without requiring credentials
    if args.dry_run:
        print(f"[DRY RUN] Mode: {args.mode}")
        print(f"[DRY RUN] Targets mode: {args.targets_mode}")
        print(f"[DRY RUN] Config: {config_path or 'default'}")
        print(f"[DRY RUN] Query: {query}")
        print(f"[DRY RUN] Max results: {args.max}")
        print(f"[DRY RUN] Days: {args.days}")
        print(f"[DRY RUN] Must have ICS: {config.get('must_have_ics', False)}")
        print(f"[DRY RUN] Include labels: {', '.join(config.get('include_labels', []))}")
        print(f"[DRY RUN] Exclude categories: {', '.join(config.get('exclude_categories', []))}")
        if args.mode == 'targets':
            targets_data = load_newsletter_targets()
            if targets_data:
                targets = targets_data.get('targets', [])
                total = len(targets)
                with_discovered = len([t for t in targets if t.get('discovered_senders')])
                high_conf = len([t for t in targets if t.get('sender_confidence') == 'high'])
                subscribed = len([t for t in targets if t.get('status') == 'subscribed'])
                print(f"[DRY RUN] Total targets: {total}")
                print(f"[DRY RUN] Targets with discovered senders: {with_discovered}")
                print(f"[DRY RUN] High confidence targets: {high_conf}")
                print(f"[DRY RUN] Subscribed targets: {subscribed}")
                
                # Show which targets are contributing to query
                print()
                print("[DRY RUN] Targets contributing to query:")
                for t in targets:
                    discovered = t.get('discovered_senders', [])
                    expected = t.get('expected_from_domains', [])
                    if args.targets_mode == 'strict':
                        if discovered:
                            print(f"  - {t.get('org_name')}: {', '.join(discovered[:3])}{'...' if len(discovered) > 3 else ''}")
                    else:
                        if discovered:
                            print(f"  - {t.get('org_name')}: {', '.join(discovered[:3])}{'...' if len(discovered) > 3 else ''} (discovered)")
                        elif expected:
                            print(f"  - {t.get('org_name')}: {', '.join(expected[:3])}{'...' if len(expected) > 3 else ''} (expected)")
        print()
        print("[DRY RUN] No Gmail API calls made. Use without --dry-run to actually ingest.")
        return 0
    
    # Check credentials (only needed for actual ingestion)
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
    
    # List messages
    print(f"Querying Gmail: {query}")
    messages = list_messages(service, query, max_results=args.max)
    
    if not messages:
        print("No messages found")
        return
    
    print(f"Found {len(messages)} message(s)")
    print()
    
    # Process messages
    scanned = 0
    skipped_dedup = 0
    ingested = 0
    rejected = 0
    errors = 0
    rejection_reasons = Counter()
    ingested_events = []  # Track ingested events for summary
    
    for msg_info in messages:
        message_id = msg_info['id']
        scanned += 1
        
        # Check if already ingested
        if is_email_ingested(gmail_id=message_id):
            skipped_dedup += 1
            continue
        
        # Pre-filter: check subject for blocklist
        # Get message headers first (lightweight)
        try:
            message_headers = service.users().messages().get(
                userId='me',
                id=message_id,
                format='metadata',
                metadataHeaders=['Subject', 'From']
            ).execute()
            
            headers = message_headers.get('payload', {}).get('headers', [])
            subject = ''
            from_addr = ''
            for header in headers:
                if header.get('name', '').lower() == 'subject':
                    subject = header.get('value', '')
                elif header.get('name', '').lower() == 'from':
                    from_addr = header.get('value', '')
            
            # Pre-filter: subject blocklist
            subject_blocklist = config.get('subject_blocklist_keywords', [])
            pre_filtered = False
            if subject_blocklist:
                subject_lower = subject.lower()
                for keyword in subject_blocklist:
                    if keyword.lower() in subject_lower:
                        rejected += 1
                        rejection_reasons['pre_filter_subject_blocked'] = rejection_reasons.get('pre_filter_subject_blocked', 0) + 1
                        record_ingested_email(
                            gmail_id=message_id,
                            thread_id=message_headers.get('threadId', ''),
                            internal_date=message_headers.get('internalDate', ''),
                            subject=subject,
                            from_addr=from_addr,
                            sha256='',
                            status='rejected',
                            failure_reason='pre_filter_subject_blocked'
                        )
                        pre_filtered = True
                        break
            
            if pre_filtered:
                continue
            
            # Pre-filter: from blocklist
            from_blocklist = config.get('from_blocklist', [])
            if from_blocklist:
                from_lower = from_addr.lower()
                for blocked in from_blocklist:
                    if blocked.lower() in from_lower:
                        rejected += 1
                        rejection_reasons['pre_filter_from_blocked'] = rejection_reasons.get('pre_filter_from_blocked', 0) + 1
                        record_ingested_email(
                            gmail_id=message_id,
                            thread_id=message_headers.get('threadId', ''),
                            internal_date=message_headers.get('internalDate', ''),
                            subject=subject,
                            from_addr=from_addr,
                            sha256='',
                            status='rejected',
                            failure_reason='pre_filter_from_blocked'
                        )
                        pre_filtered = True
                        break
            
            if pre_filtered:
                continue
        except Exception:
            pass  # Continue to full message fetch
        
        # Get full message
        message = get_message(service, message_id)
        if not message:
            errors += 1
            continue
        
        # Parse message
        try:
            parsed = parse_gmail_message(service, message)
        except Exception as e:
            errors += 1
            record_ingested_email(
                gmail_id=message_id,
                thread_id=message.get('threadId', ''),
                internal_date=message.get('internalDate', ''),
                subject='',
                from_addr='',
                sha256='',
                status='error',
                failure_reason=f'parse_error: {str(e)}'
            )
            continue
        
        # Check SHA256 deduplication
        if is_email_ingested(sha256=parsed['sha256']):
            skipped_dedup += 1
            record_ingested_email(
                gmail_id=message_id,
                thread_id=parsed['thread_id'],
                internal_date=parsed['internal_date'],
                subject=parsed['subject'],
                from_addr=parsed['from_addr'],
                sha256=parsed['sha256'],
                status='rejected',
                failure_reason='duplicate_sha256'
            )
            continue
        
        # Extract events (can be multiple from newsletter templates)
        try:
            extracted_events = extract_events_from_gmail_message(service, message)
        except Exception as e:
            errors += 1
            record_ingested_email(
                gmail_id=message_id,
                thread_id=parsed['thread_id'],
                internal_date=parsed['internal_date'],
                subject=parsed['subject'],
                from_addr=parsed['from_addr'],
                sha256=parsed['sha256'],
                status='error',
                failure_reason=f'extraction_error: {str(e)}'
            )
            continue
        
        # Determine rejection reason if no events extracted
        if not extracted_events:
            # Re-validate to get reason
            from backend.utils.email_rules import validate_email_event, extract_date_time_from_text, choose_best_link
            subject = parsed.get('subject', '')
            body = parsed.get('plain_body', '')
            date_time = extract_date_time_from_text(body)
            links = parsed.get('links', [])
            is_valid, reason = validate_email_event(subject, body, date_time, links)
            rejection_reason = reason or 'validation_failed'
            rejection_reasons[rejection_reason] = rejection_reasons.get(rejection_reason, 0) + 1
            record_ingested_email(
                gmail_id=message_id,
                thread_id=parsed['thread_id'],
                internal_date=parsed['internal_date'],
                subject=parsed['subject'],
                from_addr=parsed['from_addr'],
                sha256=parsed['sha256'],
                status='rejected',
                failure_reason=rejection_reason
            )
            rejected += 1
            continue
        
        # Process each extracted event
        for extracted_event in extracted_events:
            # Normalize and upsert
            if not args.dry_run:
                source_config = {
                    'id': 'gmail_ingest',
                    'firm_name': extracted_event.get('firm_name', 'Email Source'),
                    'default_tags_json': ['Email', 'Macro']
                }
                
                normalized, norm_rejection = normalize_event(extracted_event, source_config)
                if normalized:
                    conn = get_db()
                    try:
                        upsert_event(
                            firm_name=normalized.get('firm_name'),
                            event_name=normalized.get('event_name'),
                            date_time=normalized.get('date_time'),
                            link=normalized.get('link'),
                            source_id=normalized.get('source_id', 'gmail_ingest'),
                            tags_json=normalized.get('tags_json', []),
                            format=normalized.get('format', 'Unknown'),
                            bank_participants_json=normalized.get('bank_participants_json', []),
                            # Intel classification fields (PHASE 1)
                            intel_type=normalized.get('intel_type'),
                            has_explicit_date=normalized.get('has_explicit_date'),
                            confidence_score=normalized.get('confidence_score')
                        )
                    finally:
                        conn.close()
                    
                    ingested += 1
                    record_ingested_email(
                        gmail_id=message_id,
                        thread_id=parsed['thread_id'],
                        internal_date=parsed['internal_date'],
                        subject=parsed['subject'],
                        from_addr=parsed['from_addr'],
                        sha256=parsed['sha256'],
                        status='ingested',
                        failure_reason=None
                    )
                    
                    # Track for summary
                    ingested_events.append({
                        'event_name': normalized.get('event_name'),
                        'intel_type': normalized.get('intel_type', 'unknown'),
                        'confidence_score': normalized.get('confidence_score', 0),
                        'firm_name': normalized.get('firm_name'),
                        'from_addr': parsed.get('from_addr', '')
                    })
                    
                    # Update sender statistics and newsletter quality (PHASE 4)
                    if not args.dry_run:
                        from_addr = parsed.get('from_addr', '')
                        # Try to match to newsletter target
                        newsletter_id = None
                        if args.use_newsletter_targets and args.mode == 'targets':
                            targets_data = load_newsletter_targets()
                            if targets_data:
                                for target in targets_data.get('targets', []):
                                    if target.get('status') == 'subscribed':
                                        expected_domains = target.get('expected_from_domains', [])
                                        discovered = target.get('discovered_senders', [])
                                        from_domain = from_addr.split('@')[-1] if '@' in from_addr else ''
                                        if from_domain in expected_domains or from_addr in discovered:
                                            newsletter_id = target.get('id')
                                            break
                        
                        # Update sender stats
                        update_sender_stats(from_addr, newsletter_id, intel_extracted=True)
                        
                        # Update newsletter quality
                        if newsletter_id:
                            update_newsletter_quality_stats(
                                newsletter_id,
                                email_processed=True,
                                intel_extracted=True,
                                rejected=False
                            )
                else:
                    rejected += 1
                    rejection_reasons[norm_rejection or 'normalization_failed'] = rejection_reasons.get(norm_rejection or 'normalization_failed', 0) + 1
                    record_ingested_email(
                        gmail_id=message_id,
                        thread_id=parsed['thread_id'],
                        internal_date=parsed['internal_date'],
                        subject=parsed['subject'],
                        from_addr=parsed['from_addr'],
                        sha256=parsed['sha256'],
                        status='rejected',
                        failure_reason=norm_rejection or 'normalization_failed'
                    )
                    
                    # Update sender stats for rejection (PHASE 4)
                    if not args.dry_run:
                        from_addr = parsed.get('from_addr', '')
                        newsletter_id = None
                        update_sender_stats(from_addr, newsletter_id, intel_extracted=False, rejected=True)
            else:
                ingested += 1  # Count for dry-run
    
    # Collect top from domains and subject tokens
    top_from_domains = Counter()
    top_subject_tokens = Counter()
    
    # Re-query to get domains and tokens (simplified - just from processed messages)
    # In production, could track during processing
    
    # Save run report
    report_data = {
        'query_used': query,
        'config_used': str(config_path) if config_path else 'default',
        'days': args.days,
        'max': args.max,
        'scanned': scanned,
        'ingested': ingested,
        'rejected': rejected,
        'skipped_dedup': skipped_dedup,
        'errors': errors,
        'top_rejection_reasons': dict(rejection_reasons.most_common(10)),
        'top_from_domains': dict(top_from_domains.most_common(10)),
        'top_subject_tokens': dict(top_subject_tokens.most_common(10)),
        'timestamp': datetime.now().isoformat()
    }
    
    report_dir = Path(backend_dir) / 'backend' / '_evidence' / 'email' / 'run_reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump(report_data, f, indent=2)
    
    # Post-ingest summary
    print()
    print("=" * 60)
    print("POST-INGEST SUMMARY")
    print("=" * 60)
    if args.dry_run:
        print("[DRY RUN - No database writes]")
        print()
    print(f"Scanned: {scanned}")
    print(f"Skipped (dedup): {skipped_dedup}")
    print(f"Ingested: {ingested}")
    print(f"Rejected: {rejected}")
    print(f"Errors: {errors}")
    print()
    
    # Counts by intel_type
    intel_type_counts = Counter()
    for event in ingested_events:
        intel_type = event.get('intel_type', 'unknown')
        intel_type_counts[intel_type] += 1
    
    if intel_type_counts:
        print("Counts by intel_type:")
        for intel_type, count in intel_type_counts.most_common():
            print(f"  {intel_type}: {count}")
        print()
    
    # Top rejection reasons
    if rejection_reasons:
        print("Top rejection reasons:")
        for reason, count in rejection_reasons.most_common(10):
            print(f"  {reason}: {count}")
        print()
    
    # Top contributing senders
    sender_counts = Counter()
    for event in ingested_events:
        from_addr = event.get('from_addr', '')
        if from_addr:
            sender_counts[from_addr] += 1
    
    if sender_counts:
        print("Top contributing senders:")
        for sender, count in sender_counts.most_common(5):
            print(f"  {sender}: {count} event(s)")
        print()
    
    # Example ingested items
    if ingested_events:
        print("Example ingested items (first 5):")
        for i, event in enumerate(ingested_events[:5]):
            event_name = event.get('event_name', 'Unknown')[:60]
            intel_type = event.get('intel_type', 'unknown')
            confidence = event.get('confidence_score', 0)
            print(f"  {i+1}. {event_name}")
            print(f"     Type: {intel_type}, Confidence: {confidence}")
        print()
    
    print(f"Run report saved to: {report_file}")
    print("=" * 60)


if __name__ == '__main__':
    main()
