#!/usr/bin/env python3
"""
Phase 5 & 6: Quality Assurance and Maintenance Monitoring

This script implements the monitoring tasks from Phase 5 and Phase 6:
- Phase 5: Quality Assurance (verify event quality, check for issues)
- Phase 6: Maintenance (identify sources needing re-testing)

Run this script weekly/monthly to catch issues early.
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import Counter

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_sources


def check_source_health():
    """Phase 5: Check source health and identify issues."""
    sources_file = backend_dir / "sources.json"
    db_path = backend_dir / "events.db"
    
    if not sources_file.exists() or not db_path.exists():
        print("❌ Required files not found")
        return {}
    
    with open(sources_file, 'r') as f:
        sources = json.load(f)
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    issues = {
        'zero_event_sources': [],
        'low_event_sources': [],
        'past_events': [],
        'duplicates': [],
        'missing_tags': []
    }
    
    # Check each active source
    active_sources = [s for s in sources if s.get('active', 0) == 1]
    
    for source in active_sources:
        source_id = source.get('id')
        firm_name = source.get('firm_name')
        
        cursor.execute('SELECT COUNT(*) FROM events WHERE firm_name = ?', (firm_name,))
        count = cursor.fetchone()[0]
        
        if count == 0:
            issues['zero_event_sources'].append({
                'id': source_id,
                'firm_name': firm_name,
                'url': source.get('url', 'N/A'),
                'adapter_type': source.get('adapter_type', 'unknown')
            })
        elif count < 3:
            issues['low_event_sources'].append({
                'id': source_id,
                'firm_name': firm_name,
                'count': count
            })
    
    # Check for past events
    cursor.execute('''
        SELECT firm_name, event_name, date_time 
        FROM events 
        WHERE date_time IS NOT NULL AND date_time < datetime('now')
        LIMIT 20
    ''')
    issues['past_events'] = cursor.fetchall()
    
    # Check for duplicates
    cursor.execute('''
        SELECT firm_name, event_name, COUNT(*) as cnt
        FROM events
        GROUP BY firm_name, event_name
        HAVING cnt > 1
        ORDER BY cnt DESC
        LIMIT 20
    ''')
    issues['duplicates'] = cursor.fetchall()
    
    conn.close()
    return issues, active_sources


def generate_maintenance_checklist(active_sources):
    """Phase 6: Generate monthly maintenance checklist."""
    checklist = []
    
    for source in active_sources:
        checklist.append({
            'id': source.get('id'),
            'firm_name': source.get('firm_name'),
            'adapter_type': source.get('adapter_type', 'unknown'),
            'url': source.get('url', 'N/A'),
            'test_command': f"python scripts/test_source.py {source.get('id')} 5"
        })
    
    return checklist


def generate_report(issues, checklist):
    """Generate markdown report."""
    report_lines = []
    report_lines.append("# Phase 5 & 6: Quality Assurance & Maintenance Report")
    report_lines.append("")
    report_lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    
    # Phase 5: Quality Assurance
    report_lines.append("## Phase 5: Quality Assurance")
    report_lines.append("")
    
    # Zero event sources
    report_lines.append("### ❌ Sources with 0 Events (RED FLAG)")
    report_lines.append("")
    if issues['zero_event_sources']:
        report_lines.append("These sources are active but extracting 0 events. Selectors may be broken.")
        report_lines.append("")
        report_lines.append("| Source | Adapter | Action |")
        report_lines.append("|--------|---------|--------|")
        for source in issues['zero_event_sources']:
            report_lines.append(f"| {source['firm_name']} ({source['id']}) | {source['adapter_type']} | `python scripts/test_source.py {source['id']} 5` |")
        report_lines.append("")
    else:
        report_lines.append("✅ No sources with 0 events")
        report_lines.append("")
    
    # Low event sources
    if issues['low_event_sources']:
        report_lines.append("### ⚠️ Sources with <3 Events")
        report_lines.append("")
        report_lines.append("| Source | Event Count |")
        report_lines.append("|--------|-------------|")
        for source in issues['low_event_sources']:
            report_lines.append(f"| {source['firm_name']} ({source['id']}) | {source['count']} |")
        report_lines.append("")
    
    # Past events
    report_lines.append("### Past Events Check")
    report_lines.append("")
    past_count = len(issues['past_events'])
    if past_count > 0:
        report_lines.append(f"⚠️ Found {past_count} past events in database")
        report_lines.append("")
        report_lines.append("Note: Past events should be filtered by the pipeline. This may be expected if events were added before filtering was implemented.")
        report_lines.append("")
    else:
        report_lines.append("✅ No past events found")
        report_lines.append("")
    
    # Duplicates
    report_lines.append("### Duplicate Events Check")
    report_lines.append("")
    dup_count = len(issues['duplicates'])
    if dup_count > 0:
        report_lines.append(f"⚠️ Found {dup_count} potential duplicate events (same title from same firm)")
        report_lines.append("")
        report_lines.append("Top duplicates:")
        report_lines.append("")
        for firm_name, event_name, cnt in issues['duplicates'][:10]:
            report_lines.append(f"- **{firm_name}**: \"{event_name[:60]}\" ({cnt} times)")
        report_lines.append("")
        report_lines.append("Note: Some duplicates may be legitimate (e.g., recurring events with same title)")
        report_lines.append("")
    else:
        report_lines.append("✅ No obvious duplicates found")
        report_lines.append("")
    
    # Phase 6: Maintenance
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## Phase 6: Maintenance")
    report_lines.append("")
    report_lines.append("### Monthly Re-test Checklist")
    report_lines.append("")
    report_lines.append(f"Total active sources to monitor: {len(checklist)}")
    report_lines.append("")
    report_lines.append("**Recommended**: Re-test all sources monthly to catch broken selectors early.")
    report_lines.append("")
    report_lines.append("| # | Source | Adapter | Test Command |")
    report_lines.append("|---|--------|---------|---------------|")
    for i, source in enumerate(checklist[:20], 1):
        report_lines.append(f"| {i} | {source['firm_name']} ({source['id']}) | {source['adapter_type']} | `{source['test_command']}` |")
    report_lines.append("")
    
    if len(checklist) > 20:
        report_lines.append(f"... and {len(checklist) - 20} more sources")
        report_lines.append("")
    
    report_lines.append("### Weekly Tasks")
    report_lines.append("")
    report_lines.append("- Check source health report: `python scripts/report_sources.py`")
    report_lines.append("- Review this monitoring report")
    report_lines.append("")
    
    report_lines.append("### Monthly Tasks")
    report_lines.append("")
    report_lines.append("- Re-test sources with 0 events")
    report_lines.append("- Re-test sources with declining event counts")
    report_lines.append("- Review and update selectors if needed")
    report_lines.append("")
    
    report_lines.append("### Quarterly Tasks")
    report_lines.append("")
    report_lines.append("- Review all sources with <10 events")
    report_lines.append("- Update selectors for sources with declining event counts")
    report_lines.append("- Check for new adapter types or methods")
    report_lines.append("")
    
    return '\n'.join(report_lines)


def main():
    """Main function."""
    print("=" * 60)
    print("PHASE 5 & 6: QUALITY ASSURANCE & MAINTENANCE MONITORING")
    print("=" * 60)
    print()
    
    # Phase 5: Quality checks
    issues, active_sources = check_source_health()
    
    # Phase 6: Maintenance checklist
    checklist = generate_maintenance_checklist(active_sources)
    
    # Print summary
    print("=== Phase 5: Quality Assurance ===")
    print()
    
    if issues['zero_event_sources']:
        print(f"❌ RED FLAG: {len(issues['zero_event_sources'])} sources with 0 events:")
        for source in issues['zero_event_sources']:
            print(f"   - {source['firm_name']} ({source['id']})")
        print()
    else:
        print("✅ No sources with 0 events")
        print()
    
    if issues['low_event_sources']:
        print(f"⚠️ {len(issues['low_event_sources'])} sources with <3 events")
        print()
    
    past_count = len(issues['past_events'])
    if past_count > 0:
        print(f"⚠️ Found {past_count} past events in database")
        print()
    else:
        print("✅ No past events found")
        print()
    
    dup_count = len(issues['duplicates'])
    if dup_count > 0:
        print(f"⚠️ Found {dup_count} potential duplicate events")
        print()
    else:
        print("✅ No obvious duplicates")
        print()
    
    print("=== Phase 6: Maintenance ===")
    print()
    print(f"Total active sources to monitor: {len(checklist)}")
    print()
    print("Recommended monthly re-test (first 5):")
    for i, source in enumerate(checklist[:5], 1):
        print(f"  {i}. {source['firm_name']} ({source['id']})")
        print(f"     Run: {source['test_command']}")
    print()
    
    # Generate report
    report_content = generate_report(issues, checklist)
    report_path = backend_dir.parent / "md" / "PHASE_5_6_MONITORING.md"
    report_path.parent.mkdir(exist_ok=True)
    
    with open(report_path, 'w') as f:
        f.write(report_content)
    
    print(f"✅ Report written to: {report_path}")
    print()
    print("=" * 60)


if __name__ == '__main__':
    main()
