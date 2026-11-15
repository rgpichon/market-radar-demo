#!/usr/bin/env python3
"""
Source Status Report

Generates human-readable report of source status and writes md/SOURCE_STATUS.md
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

from backend.utils.source_registry import load_registry
from backend.utils.lanes import infer_lane_from_source


def load_source_stats():
    """Load source_stats.json."""
    stats_path = Path(backend_dir) / 'backend' / 'source_stats.json'
    if not stats_path.exists():
        return {}
    try:
        with open(stats_path) as f:
            return json.load(f)
    except Exception:
        return {}


def generate_report():
    """Generate source status report."""
    registry = load_registry()
    stats = load_source_stats()
    
    # Group by lane
    lane_counts = Counter()
    lane_future_events = Counter()
    
    # Group by status
    status_counts = Counter()
    
    # Top sources by future events
    sources_by_future = []
    
    # Worst sources by kept_ratio
    sources_by_kept_ratio = []
    
    for source_id, reg_entry in registry.items():
        lane = reg_entry.get('lane', 'unknown')
        status = reg_entry.get('acquisition_status', 'unknown')
        active = reg_entry.get('active', 0)
        
        lane_counts[lane] += 1
        status_counts[status] += 1
        
        source_stat = stats.get(source_id, {})
        future_count = source_stat.get('future_count', 0)
        kept_ratio = source_stat.get('kept_ratio', 0.0)
        
        if active:
            lane_future_events[lane] += future_count
        
        if future_count > 0:
            sources_by_future.append({
                'id': source_id,
                'firm_name': reg_entry.get('firm_name', ''),
                'lane': lane,
                'future_count': future_count,
                'kept_ratio': kept_ratio
            })
        
        if source_stat:
            sources_by_kept_ratio.append({
                'id': source_id,
                'firm_name': reg_entry.get('firm_name', ''),
                'kept_ratio': kept_ratio,
                'raw_count': source_stat.get('raw_count', 0),
                'kept_count': source_stat.get('kept_count', 0),
                'top_rejection_reasons': source_stat.get('top_rejection_reasons', {})
            })
    
    # Sort
    sources_by_future.sort(key=lambda x: x['future_count'], reverse=True)
    sources_by_kept_ratio.sort(key=lambda x: x['kept_ratio'])
    
    # Generate markdown
    report_lines = []
    report_lines.append("# Source Status Report")
    report_lines.append("")
    report_lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    
    # Summary
    active_count = sum(1 for r in registry.values() if r.get('active'))
    total_count = len(registry)
    report_lines.append("## Summary")
    report_lines.append("")
    report_lines.append(f"- **Total Sources**: {total_count}")
    report_lines.append(f"- **Active Sources**: {active_count}")
    report_lines.append(f"- **Inactive Sources**: {total_count - active_count}")
    report_lines.append("")
    
    # Lane Coverage
    report_lines.append("## Lane Coverage")
    report_lines.append("")
    report_lines.append("| Lane | Total Sources | Active Sources | Future Events |")
    report_lines.append("|------|---------------|---------------|---------------|")
    for lane in sorted(lane_counts.keys()):
        total = lane_counts[lane]
        active = sum(1 for r in registry.values() if r.get('lane') == lane and r.get('active'))
        future = lane_future_events[lane]
        report_lines.append(f"| {lane} | {total} | {active} | {future} |")
    report_lines.append("")
    
    # Status Distribution
    report_lines.append("## Status Distribution")
    report_lines.append("")
    for status, count in status_counts.most_common():
        report_lines.append(f"- **{status}**: {count}")
    report_lines.append("")
    
    # Top Sources by Future Events
    report_lines.append("## Top Sources by Future Events")
    report_lines.append("")
    report_lines.append("| Source | Lane | Future Events | Kept Ratio |")
    report_lines.append("|--------|------|---------------|------------|")
    for source in sources_by_future[:10]:
        report_lines.append(f"| {source['firm_name']} ({source['id']}) | {source['lane']} | {source['future_count']} | {source['kept_ratio']:.1%} |")
    report_lines.append("")
    
    # Worst Sources by Kept Ratio
    report_lines.append("## Sources with Low Kept Ratio")
    report_lines.append("")
    report_lines.append("| Source | Kept Ratio | Raw | Kept | Top Rejection Reasons |")
    report_lines.append("|--------|------------|-----|------|----------------------|")
    for source in sources_by_kept_ratio[:10]:
        reasons = source.get('top_rejection_reasons', {})
        reasons_str = ', '.join([f"{k}({v})" for k, v in list(reasons.items())[:3]])
        report_lines.append(f"| {source['firm_name']} ({source['id']}) | {source['kept_ratio']:.1%} | {source['raw_count']} | {source['kept_count']} | {reasons_str} |")
    report_lines.append("")
    
    # Starving Lanes
    report_lines.append("## Lane Recommendations")
    report_lines.append("")
    for lane in sorted(lane_counts.keys()):
        active = sum(1 for r in registry.values() if r.get('lane') == lane and r.get('active'))
        future = lane_future_events[lane]
        if active == 0:
            report_lines.append(f"- **{lane}**: No active sources - consider adding sources for this lane")
        elif future < 10:
            report_lines.append(f"- **{lane}**: Low future event count ({future}) - consider expanding coverage")
    report_lines.append("")
    
    # Write report
    report_path = Path(backend_dir) / 'md' / 'SOURCE_STATUS.md'
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, 'w') as f:
        f.write('\n'.join(report_lines))
    
    # Print summary
    print("=" * 60)
    print("SOURCE STATUS REPORT")
    print("=" * 60)
    print()
    print(f"Total Sources: {total_count}")
    print(f"Active: {active_count}")
    print()
    print("Top Sources by Future Events:")
    for source in sources_by_future[:5]:
        print(f"  {source['firm_name']}: {source['future_count']} events")
    print()
    print("Worst Sources by Kept Ratio:")
    for source in sources_by_kept_ratio[:5]:
        print(f"  {source['firm_name']}: {source['kept_ratio']:.1%} ({source['kept_count']}/{source['raw_count']})")
    print()
    print("Lane Coverage:")
    for lane in sorted(lane_counts.keys()):
        active = sum(1 for r in registry.values() if r.get('lane') == lane and r.get('active'))
        future = lane_future_events[lane]
        print(f"  {lane}: {active} active, {future} future events")
    print()
    print(f"Report written to: {report_path}")
    print("=" * 60)


if __name__ == '__main__':
    generate_report()
