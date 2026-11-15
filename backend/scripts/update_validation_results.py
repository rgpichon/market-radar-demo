#!/usr/bin/env python3
"""
Update validation results with current working status from database.

Usage:
    python update_validation_results.py
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from db import get_db, init_db, get_sources


RESULTS_FILE = backend_dir / "new_sources_validation_results.json"


def main():
    init_db()
    
    # Get all new sources
    sources = get_sources(active_only=False)
    new_sources = [
        s for s in sources
        if 'Generated from bulk discovery' in (s.get('comment') or '')
    ]
    
    # Get event counts from database
    conn = get_db()
    cursor = conn.cursor()
    
    results = []
    working_count = 0
    partial_count = 0
    no_events_count = 0
    
    for source in new_sources:
        source_id = source.get('id', '')
        active = source.get('active', 0) == 1
        
        # Get event count from database
        cursor.execute("SELECT COUNT(*) FROM events WHERE source_id = ?", (source_id,))
        event_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM events 
            WHERE source_id = ? AND date_time IS NOT NULL
        """, (source_id,))
        dated_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM events 
            WHERE source_id = ? AND date_time IS NOT NULL 
            AND date_time >= datetime('now')
        """, (source_id,))
        future_count = cursor.fetchone()[0]
        
        dated_ratio = dated_count / event_count if event_count > 0 else 0.0
        
        if event_count >= 3 and dated_ratio >= 0.70 and future_count >= 1:
            status = 'working'
            working_count += 1
        elif event_count > 0:
            status = 'partial'
            partial_count += 1
        else:
            status = 'no_events'
            no_events_count += 1
        
        results.append({
            'source_id': source_id,
            'firm_name': source.get('firm_name', ''),
            'url': source.get('url', ''),
            'adapter_type': source.get('adapter_type', ''),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': status,
            'events_found': event_count,
            'dated_count': dated_count,
            'future_count': future_count,
            'dated_ratio': dated_ratio,
            'active': active,
            'errors': [],
            'warnings': []
        })
    
    conn.close()
    
    # Update results file
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'summary': {
            'total': len(results),
            'working': working_count,
            'partial': partial_count,
            'no_events': no_events_count,
            'errors': 0
        },
        'results': results
    }
    
    with open(RESULTS_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"=== Updated Validation Results ===")
    print(f"Total sources: {len(results)}")
    print(f"  ✓ Working: {working_count}")
    print(f"  ⚠ Partial: {partial_count}")
    print(f"  ✗ No events: {no_events_count}")
    print()
    print(f"Working sources:")
    for r in results:
        if r['status'] == 'working':
            print(f"  {r['firm_name']} ({r['source_id']}): {r['events_found']} events, {r['future_count']} future, {r['dated_ratio']:.1%} dated")
    print()
    print(f"Results saved to: {RESULTS_FILE}")


if __name__ == '__main__':
    main()
