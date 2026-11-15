#!/usr/bin/env python3
"""
Newsletter Targets Status Report

Generates human-readable report of newsletter target status and writes md/NEWSLETTER_TARGETS_STATUS.md
"""
import sys
import json
from pathlib import Path
from collections import Counter
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def load_newsletter_targets():
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


def validate_targets(data):
    """Validate newsletter targets registry."""
    errors = []
    
    # Check required top-level keys
    required_keys = ['owner_email', 'updated_at', 'targets']
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required key: {key}")
    
    if 'targets' not in data:
        return errors
    
    # Validate each target
    seen_ids = set()
    valid_statuses = ['todo', 'subscribed', 'subscribed_candidate', 'validated', 'paused', 'rejected', 'unknown', 'requires_manual', 'confirmed']
    valid_priorities = ['p0', 'p1', 'p2']
    valid_categories = ['bulge_bracket', 'asset_manager', 'think_tank', 'association', 'other']
    valid_confidence = ['low', 'medium', 'high']
    
    for i, target in enumerate(data['targets']):
        target_id = target.get('id', f'<missing_id_{i}>')
        
        # Check duplicate IDs
        if target_id in seen_ids:
            errors.append(f"Duplicate target ID: {target_id}")
        seen_ids.add(target_id)
        
        # Check required fields
        required_fields = ['id', 'org_name', 'category', 'priority', 'status']
        for field in required_fields:
            if field not in target:
                errors.append(f"Target {target_id}: missing required field '{field}'")
        
        # Validate status
        status = target.get('status')
        if status and status not in valid_statuses:
            errors.append(f"Target {target_id}: invalid status '{status}' (must be one of {valid_statuses})")
        
        # Validate priority
        priority = target.get('priority')
        if priority and priority not in valid_priorities:
            errors.append(f"Target {target_id}: invalid priority '{priority}' (must be one of {valid_priorities})")
        
        # Validate category
        category = target.get('category')
        if category and category not in valid_categories:
            errors.append(f"Target {target_id}: invalid category '{category}' (must be one of {valid_categories})")
        
        # Validate confidence (optional field)
        confidence = target.get('sender_confidence')
        if confidence and confidence not in valid_confidence:
            errors.append(f"Target {target_id}: invalid sender_confidence '{confidence}' (must be one of {valid_confidence})")
    
    return errors


def generate_report():
    """Generate newsletter targets status report."""
    data = load_newsletter_targets()
    
    # Validate
    errors = validate_targets(data)
    if errors:
        print("Validation errors:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    
    targets = data.get('targets', [])
    
    # Group by status
    status_counts = Counter()
    category_counts = Counter()
    priority_counts = Counter()
    
    # P0 targets
    p0_targets = []
    
    # Subscribed targets (for allowlist suggestions)
    subscribed_targets = []
    
    # All targets (for keyword aggregation)
    all_targets = []
    
    for target in targets:
        status = target.get('status', 'unknown')
        category = target.get('category', 'unknown')
        priority = target.get('priority', 'unknown')
        
        status_counts[status] += 1
        category_counts[category] += 1
        priority_counts[priority] += 1
        
        if priority == 'p0':
            p0_targets.append(target)
        
        if status == 'subscribed':
            subscribed_targets.append(target)
        
        all_targets.append(target)
    
    # Aggregate allowlist domains/emails from subscribed targets
    allowlist_domains = set()
    allowlist_emails = set()
    for target in subscribed_targets:
        allowlist_domains.update(target.get('expected_from_domains', []))
        allowlist_emails.update(target.get('expected_from_emails', []))
    
    # Aggregate keywords from all targets
    include_keywords = set()
    exclude_keywords = set()
    for target in all_targets:
        include_keywords.update(target.get('subject_include_any', []))
        exclude_keywords.update(target.get('subject_exclude_any', []))
    
    # Generate markdown
    report_lines = []
    report_lines.append("# Newsletter Targets Status Report")
    report_lines.append("")
    report_lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"**Owner Email**: {data.get('owner_email', 'N/A')}")
    report_lines.append(f"**Last Updated**: {data.get('updated_at', 'N/A')}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    
    # Summary by Status
    report_lines.append("## Summary by Status")
    report_lines.append("")
    report_lines.append("| Status | Count |")
    report_lines.append("|--------|-------|")
    for status in ['todo', 'subscribed', 'rejected', 'unknown', 'requires_manual', 'confirmed']:
        count = status_counts.get(status, 0)
        report_lines.append(f"| {status} | {count} |")
    report_lines.append("")
    
    # Summary by Category
    report_lines.append("## Summary by Category")
    report_lines.append("")
    report_lines.append("| Category | Count |")
    report_lines.append("|----------|-------|")
    for category in sorted(category_counts.keys()):
        count = category_counts[category]
        report_lines.append(f"| {category} | {count} |")
    report_lines.append("")
    
    # Summary by Priority
    report_lines.append("## Summary by Priority")
    report_lines.append("")
    report_lines.append("| Priority | Count |")
    report_lines.append("|----------|-------|")
    for priority in ['p0', 'p1', 'p2']:
        count = priority_counts.get(priority, 0)
        report_lines.append(f"| {priority} | {count} |")
    report_lines.append("")
    
    # Missing signup_url
    missing_signup = [t for t in targets if t.get('signup_url') == 'FILL_ME' or not t.get('signup_url')]
    if missing_signup:
        report_lines.append("## Missing Signup URL")
        report_lines.append("")
        report_lines.append("| Org | ID | Priority |")
        report_lines.append("|-----|----|----------|")
        for target in sorted(missing_signup, key=lambda t: (t.get('priority', ''), t.get('org_name', ''))):
            org_name = target.get('org_name', '')
            target_id = target.get('id', '')
            priority = target.get('priority', 'unknown')
            report_lines.append(f"| {org_name} | {target_id} | {priority} |")
        report_lines.append("")
    
    # Subscribed candidates
    subscribed_candidates = [t for t in targets if t.get('status') == 'subscribed_candidate']
    if subscribed_candidates:
        report_lines.append("## Subscribed Candidates (Seen in Gmail but Not Confirmed)")
        report_lines.append("")
        report_lines.append("| Org | ID | Confidence | Discovered Senders | Last Seen |")
        report_lines.append("|-----|----|------------|-------------------|-----------|")
        for target in sorted(subscribed_candidates, key=lambda t: t.get('org_name', '')):
            org_name = target.get('org_name', '')
            target_id = target.get('id', '')
            confidence = target.get('sender_confidence', 'low')
            discovered = target.get('discovered_senders', [])
            discovered_str = ', '.join(discovered[:3])
            if len(discovered) > 3:
                discovered_str += f' (+{len(discovered) - 3} more)'
            last_seen = target.get('last_seen_at', 'Never')
            if last_seen:
                try:
                    dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                    last_seen = dt.strftime('%Y-%m-%d')
                except:
                    pass
            report_lines.append(f"| {org_name} | {target_id} | {confidence} | {discovered_str} | {last_seen} |")
        report_lines.append("")
    
    # Subscribed (high confidence)
    subscribed_high = [t for t in targets if t.get('status') == 'subscribed' and t.get('sender_confidence') == 'high']
    if subscribed_high:
        report_lines.append("## Subscribed (High Confidence)")
        report_lines.append("")
        report_lines.append("| Org | ID | Discovered Senders | Last Seen |")
        report_lines.append("|-----|----|-------------------|-----------|")
        for target in sorted(subscribed_high, key=lambda t: t.get('org_name', '')):
            org_name = target.get('org_name', '')
            target_id = target.get('id', '')
            discovered = target.get('discovered_senders', [])
            discovered_str = ', '.join(discovered[:5])
            if len(discovered) > 5:
                discovered_str += f' (+{len(discovered) - 5} more)'
            last_seen = target.get('last_seen_at', 'Never')
            if last_seen:
                try:
                    dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                    last_seen = dt.strftime('%Y-%m-%d')
                except:
                    pass
            report_lines.append(f"| {org_name} | {target_id} | {discovered_str} | {last_seen} |")
        report_lines.append("")
    
    # Discovered/Learned Senders table (compact)
    report_lines.append("## Discovered Senders (Learned from Gmail)")
    report_lines.append("")
    report_lines.append("| Org | Confidence | Discovered Senders | Last Seen |")
    report_lines.append("|-----|------------|-------------------|-----------|")
    for target in sorted(targets, key=lambda t: (t.get('sender_confidence') or 'low', t.get('org_name', '')), reverse=True):
        org_name = target.get('org_name', '')
        discovered = target.get('discovered_senders', [])
        confidence = target.get('sender_confidence', 'low')
        last_seen = target.get('last_seen_at')
        if last_seen:
            try:
                dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                last_seen = dt.strftime('%Y-%m-%d')
            except:
                last_seen = 'Never'
        else:
            last_seen = 'Never'
        discovered_str = ', '.join(discovered[:3]) if discovered else '-'
        if len(discovered) > 3:
            discovered_str += f' (+{len(discovered) - 3})'
        report_lines.append(f"| {org_name} | {confidence} | {discovered_str} | {last_seen} |")
    report_lines.append("")
    
    # Per-bank acquisition status (NEW: Clear status with reasons)
    report_lines.append("## Per-Bank Acquisition Status")
    report_lines.append("")
    report_lines.append("| Org | Acquisition Mode | Newsletter Path | Event Portal | Status | Reason |")
    report_lines.append("|-----|----------------|-----------------|--------------|--------|--------|")
    
    for target in sorted(p0_targets, key=lambda t: t.get('org_name', '')):
        org_name = target.get('org_name', '')
        target_id = target.get('id', '')
        acquisition_mode = target.get('acquisition_mode', 'both')
        status = target.get('status', 'unknown')
        
        # Determine newsletter path status
        newsletter_path = 'N/A'
        if acquisition_mode in ['newsletter', 'both']:
            discovered_senders = target.get('discovered_senders', [])
            if discovered_senders:
                newsletter_path = f'usable ({len(discovered_senders)} senders)'
            elif status in ['subscribed', 'confirmed']:
                newsletter_path = 'subscribed (no senders yet)'
            else:
                newsletter_path = 'requires_manual'
        else:
            newsletter_path = 'not_applicable'
        
        # Determine event portal status
        event_portal = 'N/A'
        if acquisition_mode in ['events_portal', 'both']:
            acq = target.get('acquisition', {})
            discovered_pages = acq.get('discovered_signup_pages', [])
            # Check if any page passed validation
            validated_pages = [p for p in discovered_pages if p.get('event_validation', {}).get('valid')]
            if validated_pages:
                event_portal = f'usable ({len(validated_pages)} validated pages)'
            elif discovered_pages:
                event_portal = 'discovered (not validated)'
            else:
                event_portal = 'not_discovered'
        else:
            event_portal = 'not_applicable'
        
        # Overall status
        overall_status = 'unknown'
        reason = ''
        if newsletter_path.startswith('usable') or event_portal.startswith('usable'):
            overall_status = 'usable'
            reasons = []
            if newsletter_path.startswith('usable'):
                reasons.append('newsletter')
            if event_portal.startswith('usable'):
                reasons.append('event_portal')
            reason = '/'.join(reasons)
        elif newsletter_path == 'requires_manual' or event_portal == 'not_discovered':
            overall_status = 'requires_manual'
            reason = 'needs_discovery_or_subscription'
        elif status == 'rejected':
            overall_status = 'rejected'
            reason = 'governance_rejection'
        else:
            overall_status = status
            reason = 'pending'
        
        report_lines.append(f"| {org_name} | {acquisition_mode} | {newsletter_path} | {event_portal} | {overall_status} | {reason} |")
    
    report_lines.append("")
    
    # Last seen table
    report_lines.append("## All Targets by Last Seen")
    report_lines.append("")
    report_lines.append("| Org | ID | Status | Confidence | Last Seen |")
    report_lines.append("|-----|----|--------|------------|-----------|")
    for target in sorted(targets, key=lambda t: (t.get('last_seen_at') or '', t.get('org_name', '')), reverse=True):
        org_name = target.get('org_name', '')
        target_id = target.get('id', '')
        status = target.get('status', 'unknown')
        last_seen = target.get('last_seen_at', 'Never')
        if last_seen and last_seen != 'Never':
            try:
                dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                last_seen = dt.strftime('%Y-%m-%d')
            except:
                pass
        confidence = target.get('sender_confidence', 'low')
        report_lines.append(f"| {org_name} | {target_id} | {status} | {confidence} | {last_seen} |")
    report_lines.append("")
    
    # Recommended next actions - grouped by action type
    report_lines.append("## Recommended Next Actions")
    report_lines.append("")
    
    # Group 1: Fill signup URLs
    missing_url_targets = [t for t in targets if t.get('signup_url') == 'FILL_ME' or not t.get('signup_url')]
    if missing_url_targets:
        report_lines.append("### 1. Fill Signup URLs")
        report_lines.append("")
        for target in sorted(missing_url_targets, key=lambda t: t.get('priority', '')):
            report_lines.append(f"- [ ] {target.get('org_name')} (`{target.get('id')}`)")
        report_lines.append("")
    
    # Group 2: Subscribe manually
    need_subscribe = [t for t in targets if t.get('status') == 'todo' and t.get('signup_url') != 'FILL_ME' and t.get('signup_url')]
    if need_subscribe:
        report_lines.append("### 2. Subscribe Manually (using rdr.events.rp@gmail.com)")
        report_lines.append("")
        for target in sorted(need_subscribe, key=lambda t: t.get('priority', '')):
            url = target.get('signup_url', '')
            report_lines.append(f"- [ ] {target.get('org_name')}: [{url}]({url})")
        report_lines.append("")
    
    # Group 3: Run discovery
    need_discovery = [t for t in targets if t.get('status') in ['todo', 'subscribed'] and not t.get('discovered_senders')]
    if need_discovery:
        report_lines.append("### 3. Run Sender Discovery")
        report_lines.append("")
        report_lines.append("Run `python backend/scripts/discover_newsletter_senders.py --apply --report` for:")
        report_lines.append("")
        for target in sorted(need_discovery, key=lambda t: t.get('priority', ''))[:5]:
            report_lines.append(f"- {target.get('org_name')}")
        if len(need_discovery) > 5:
            report_lines.append(f"- ...and {len(need_discovery) - 5} more")
        report_lines.append("")
    
    # Group 4: Validate/confirm
    need_validation = [t for t in targets if t.get('sender_confidence') in ['medium'] and t.get('discovered_senders')]
    if need_validation:
        report_lines.append("### 4. Validate Medium-Confidence Targets")
        report_lines.append("")
        report_lines.append("Run discovery again in 7 days or wait for more emails:")
        report_lines.append("")
        for target in need_validation:
            discovered = target.get('discovered_senders', [])
            report_lines.append(f"- {target.get('org_name')}: currently {', '.join(discovered[:2])}")
        report_lines.append("")
    
    # Group 5: Ready for ingestion
    ready_targets = [t for t in targets if t.get('sender_confidence') == 'high' and t.get('discovered_senders')]
    if ready_targets:
        report_lines.append("### 5. Ready for Ingestion (High Confidence)")
        report_lines.append("")
        report_lines.append("Run: `python backend/scripts/ingest_gmail.py --mode targets --days 30 --max 200`")
        report_lines.append("")
        report_lines.append("Targets included:")
        for target in ready_targets:
            discovered = target.get('discovered_senders', [])
            report_lines.append(f"- {target.get('org_name')}: {', '.join(discovered[:3])}")
        report_lines.append("")
    
    # Summary command
    report_lines.append("### Quick Commands")
    report_lines.append("")
    report_lines.append("```bash")
    report_lines.append("# Generate this report")
    report_lines.append("python backend/scripts/report_newsletter_targets.py")
    report_lines.append("")
    report_lines.append("# Discover senders from Gmail")
    report_lines.append("python backend/scripts/discover_newsletter_senders.py --days 30 --apply --report")
    report_lines.append("")
    report_lines.append("# Dry-run ingestion")
    report_lines.append("python backend/scripts/ingest_gmail.py --mode targets --dry-run")
    report_lines.append("")
    report_lines.append("# Full ingestion")
    report_lines.append("python backend/scripts/ingest_gmail.py --mode targets --days 30 --max 200")
    report_lines.append("```")
    report_lines.append("")
    
    # P0 Subscription Checklist
    report_lines.append("## P0 Subscription Checklist")
    report_lines.append("")
    report_lines.append("| Org | ID | Signup URL | Status | Notes |")
    report_lines.append("|-----|----|-----------|--------|-------|")
    for target in sorted(p0_targets, key=lambda t: t.get('org_name', '')):
        org_name = target.get('org_name', '')
        target_id = target.get('id', '')
        signup_url = target.get('signup_url', 'FILL_ME')
        status = target.get('status', 'unknown')
        notes = target.get('notes', '')
        # Truncate notes if too long
        if len(notes) > 50:
            notes = notes[:47] + '...'
        report_lines.append(f"| {org_name} | {target_id} | {signup_url} | {status} | {notes} |")
    report_lines.append("")
    
    # Sender Allowlist Suggestions
    report_lines.append("## Sender Allowlist Suggestions")
    report_lines.append("")
    report_lines.append("These domains/emails are from subscribed targets and can be added to Gmail ingestion config.")
    report_lines.append("")
    
    if allowlist_domains:
        report_lines.append("### Domains")
        report_lines.append("")
        for domain in sorted(allowlist_domains):
            report_lines.append(f"- `{domain}`")
        report_lines.append("")
    
    if allowlist_emails:
        report_lines.append("### Email Addresses")
        report_lines.append("")
        for email in sorted(allowlist_emails):
            report_lines.append(f"- `{email}`")
        report_lines.append("")
    
    if not allowlist_domains and not allowlist_emails:
        report_lines.append("*No subscribed targets yet. Allowlist will populate as targets are subscribed.*")
        report_lines.append("")
    
    # Keyword Suggestions
    report_lines.append("## Keyword Suggestions")
    report_lines.append("")
    report_lines.append("These keywords are aggregated from all targets and can inform Gmail query building.")
    report_lines.append("")
    
    if include_keywords:
        report_lines.append("### Include Keywords (subject_include_any)")
        report_lines.append("")
        for keyword in sorted(include_keywords):
            report_lines.append(f"- `{keyword}`")
        report_lines.append("")
    
    if exclude_keywords:
        report_lines.append("### Exclude Keywords (subject_exclude_any)")
        report_lines.append("")
        for keyword in sorted(exclude_keywords):
            report_lines.append(f"- `{keyword}`")
        report_lines.append("")
    
    # Add governance decision status section (GOVERNANCE)
    from backend.db import get_decision
    report_lines.append("## Governance Decision Status")
    report_lines.append("")
    report_lines.append("| Org | Decision | Score | Status | Next Action |")
    report_lines.append("|-----|----------|-------|--------|-------------|")
    for target in sorted(targets, key=lambda t: t.get('org_name', '')):
        org_name = target.get('org_name', '')
        target_id = target.get('id')
        decision = get_decision(target_id) if target_id else None
        
        if decision:
            decision_status = decision.get('decision_status', 'unknown')
            decision_score = decision.get('decision_score', 0)
            recommended_action = decision.get('recommended_next_action', '-')
            paused = decision.get('paused', 0)
            cooldown_until = decision.get('cooldown_until')
            
            status_flags = []
            if paused:
                status_flags.append('PAUSED')
            if cooldown_until:
                status_flags.append('COOLDOWN')
            status_str = ', '.join(status_flags) if status_flags else 'active'
            
            report_lines.append(f"| {org_name} | {decision_status} | {decision_score} | {status_str} | {recommended_action} |")
        else:
            report_lines.append(f"| {org_name} | not_evaluated | - | - | evaluate |")
    report_lines.append("")
    
    # Add acquisition status section
    report_lines.append("## Acquisition Pipeline Status")
    report_lines.append("")
    report_lines.append("| Org | Feasibility | Pages | Forms | Top Candidate (score) |")
    report_lines.append("|-----|-------------|-------|-------|----------------------|")
    for target in sorted(targets, key=lambda t: t.get('org_name', '')):
        org_name = target.get('org_name', '')
        acq = target.get('acquisition', {})
        feasibility = acq.get('automation_feasibility', 'unknown')
        pages = acq.get('discovered_signup_pages', [])
        pages_count = len(pages)
        forms_count = len(acq.get('discovered_forms', []))
        
        # Get top candidate (only real discovered pages, not placeholders)
        top_candidate = '-'
        real_pages = [p for p in pages if p.get('url', '').startswith('http')]
        if real_pages:
            sorted_pages = sorted(real_pages, key=lambda p: -p.get('score', 0))
            top = sorted_pages[0]
            url_short = top.get('url', '')[:50]
            if len(top.get('url', '')) > 50:
                url_short += '...'
            top_candidate = f"{url_short} ({top.get('score', 0)})"
        
        report_lines.append(f"| {org_name} | {feasibility} | {pages_count} | {forms_count} | {top_candidate} |")
    report_lines.append("")
    
    # Add actionable next steps by category
    report_lines.append("## Next Actions by Category")
    report_lines.append("")
    
    # Categorize targets
    auto_possible = []
    manual_required = []
    blocked = []
    no_candidates = []
    
    for target in targets:
        acq = target.get('acquisition', {})
        feasibility = acq.get('automation_feasibility', 'unknown')
        pages = acq.get('discovered_signup_pages', [])
        
        if feasibility == 'feasible_http_post':
            auto_possible.append(target)
        elif feasibility == 'requires_manual':
            manual_required.append(target)
        elif feasibility in ['captcha_blocked', 'login_required', 'js_heavy_form']:
            blocked.append(target)
        elif not pages:
            no_candidates.append(target)
        else:
            manual_required.append(target)
    
    if auto_possible:
        report_lines.append("### Auto-Subscribe Possible")
        report_lines.append("")
        report_lines.append("Run: `python backend/scripts/subscribe_newsletters.py --priority p0 --apply`")
        report_lines.append("")
        for t in auto_possible:
            acq = t.get('acquisition', {})
            pages = sorted(acq.get('discovered_signup_pages', []), key=lambda p: -p.get('score', 0))
            if pages:
                report_lines.append(f"- **{t.get('org_name')}**: {pages[0].get('url', '')}")
        report_lines.append("")
    
    if manual_required:
        report_lines.append("### Manual Subscribe Required")
        report_lines.append("")
        report_lines.append("Visit these pages manually and subscribe with rdr.events.rp@gmail.com:")
        report_lines.append("")
        for t in manual_required:
            acq = t.get('acquisition', {})
            real_pages = [p for p in acq.get('discovered_signup_pages', []) if p.get('url', '').startswith('http')]
            pages = sorted(real_pages, key=lambda p: -p.get('score', 0))
            if pages:
                report_lines.append(f"- **{t.get('org_name')}**: [{pages[0].get('url', '')[:60]}...]({pages[0].get('url', '')})")
            else:
                report_lines.append(f"- **{t.get('org_name')}**: No pages found - add more seed URLs")
        report_lines.append("")
    
    if blocked:
        report_lines.append("### Blocked (CAPTCHA/Login/JS)")
        report_lines.append("")
        report_lines.append("These require manual intervention or Playwright:")
        report_lines.append("")
        for t in blocked:
            acq = t.get('acquisition', {})
            feasibility = acq.get('automation_feasibility', 'unknown')
            real_pages = [p for p in acq.get('discovered_signup_pages', []) if p.get('url', '').startswith('http')]
            pages = sorted(real_pages, key=lambda p: -p.get('score', 0))
            url = pages[0].get('url', 'N/A') if pages else 'N/A'
            report_lines.append(f"- **{t.get('org_name')}** ({feasibility}): {url[:60]}")
        report_lines.append("")
    
    if no_candidates:
        report_lines.append("### No Candidates Found")
        report_lines.append("")
        report_lines.append("Add more discovery_seed_urls to newsletter_targets.json for:")
        report_lines.append("")
        for t in no_candidates:
            report_lines.append(f"- **{t.get('org_name')}** (`{t.get('id')}`)")
        report_lines.append("")
    
    # Add governance summary (GOVERNANCE)
    from backend.db import get_db
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT decision_status, COUNT(*) as count
        FROM newsletter_decisions
        GROUP BY decision_status
    """)
    status_counts = {row['decision_status']: row['count'] for row in cursor.fetchall()}
    
    cursor.execute("""
        SELECT COUNT(*) as paused_count
        FROM newsletter_decisions
        WHERE paused = 1
    """)
    paused_count = cursor.fetchone()['paused_count'] or 0
    
    cursor.execute("""
        SELECT COUNT(*) as cooldown_count
        FROM newsletter_decisions
        WHERE cooldown_until IS NOT NULL AND cooldown_until > datetime('now')
    """)
    cooldown_count = cursor.fetchone()['cooldown_count'] or 0
    conn.close()
    
    report_lines.append("## Governance Summary")
    report_lines.append("")
    report_lines.append("| Category | Count |")
    report_lines.append("|----------|-------|")
    report_lines.append(f"| Auto-subscribe candidates | {status_counts.get('auto_subscribe', 0)} |")
    report_lines.append(f"| Manual review required | {status_counts.get('manual_review', 0)} |")
    report_lines.append(f"| Rejected | {status_counts.get('rejected', 0)} |")
    report_lines.append(f"| Paused | {paused_count} |")
    report_lines.append(f"| Cooldown | {cooldown_count} |")
    report_lines.append("")
    report_lines.append("**Note**: Run `python backend/scripts/evaluate_decisions.py` to update decisions.")
    report_lines.append("")
    
    # Write report to runbook (append status section)
    report_path = Path(backend_dir) / 'md' / 'NEWSLETTER_INGESTION_RUNBOOK.md'
    report_path.parent.mkdir(exist_ok=True)
    
    # Read existing runbook
    runbook_content = ""
    if report_path.exists():
        with open(report_path, 'r') as f:
            runbook_content = f.read()
    
    # Find and replace status section or append
    status_marker = "<!-- AUTO-GENERATED STATUS SECTION -->"
    status_end_marker = "<!-- END AUTO-GENERATED STATUS SECTION -->"
    
    status_section = f"\n{status_marker}\n\n"
    status_section += '\n'.join(report_lines)
    status_section += f"\n\n{status_end_marker}\n"
    
    if status_marker in runbook_content:
        # Replace existing section
        import re
        pattern = f"{re.escape(status_marker)}.*?{re.escape(status_end_marker)}"
        runbook_content = re.sub(pattern, status_section.strip(), runbook_content, flags=re.DOTALL)
    else:
        # Append section
        runbook_content += status_section
    
    with open(report_path, 'w') as f:
        f.write(runbook_content)
    
    # Print summary
    print("=" * 60)
    print("NEWSLETTER TARGETS STATUS REPORT")
    print("=" * 60)
    print()
    print(f"Total Targets: {len(targets)}")
    print()
    print("By Status:")
    for status in ['todo', 'subscribed', 'rejected', 'unknown', 'requires_manual', 'confirmed']:
        count = status_counts.get(status, 0)
        if count > 0:
            print(f"  {status}: {count}")
    print()
    print("By Category:")
    for category in sorted(category_counts.keys()):
        count = category_counts[category]
        print(f"  {category}: {count}")
    print()
    print(f"P0 Targets: {len(p0_targets)}")
    print(f"Subscribed Targets: {len(subscribed_targets)}")
    print()
    print(f"Report written to: {report_path}")
    print("=" * 60)


if __name__ == '__main__':
    generate_report()
