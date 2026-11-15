#!/usr/bin/env python3
"""
Backfill semantic fields for existing events in the database.
This script infers event_type, signal_level, and market_scope for all events
that don't have these fields set.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from db import get_db, get_sources
from utils.semantics import enrich_event_semantics
import json

def backfill_semantics():
    """Backfill semantic fields for all events."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all events without semantic fields
    cursor.execute("""
        SELECT id, firm_name, event_name, link, tags_json, source_id
        FROM events
        WHERE event_type IS NULL OR signal_level IS NULL OR market_scope_json IS NULL
    """)
    events_to_update = cursor.fetchall()
    
    if not events_to_update:
        print("All events already have semantic fields. Nothing to backfill.")
        return
    
    print(f"Found {len(events_to_update)} events to backfill...")
    
    # Get sources for firm_type lookup
    sources = get_sources(active_only=False)
    source_map = {s['id']: s.get('firm_type') for s in sources}
    
    updated_count = 0
    
    for event_row in events_to_update:
        event_id = event_row['id']
        firm_name = event_row['firm_name']
        event_name = event_row['event_name']
        link = event_row['link']
        tags_json = event_row['tags_json']
        source_id = event_row['source_id']
        
        # Parse tags
        tags = []
        if tags_json:
            try:
                tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
            except:
                pass
        
        # Build event dict
        event = {
            'firm_name': firm_name,
            'event_name': event_name,
            'link': link,
            'tags': tags
        }
        
        # Get firm_type from source
        firm_type = source_map.get(source_id)
        
        # Enrich with semantics
        event = enrich_event_semantics(event, firm_type=firm_type)
        
        # Update database
        cursor.execute("""
            UPDATE events
            SET event_type = ?,
                signal_level = ?,
                market_scope_json = ?
            WHERE id = ?
        """, (
            event.get('event_type'),
            event.get('signal_level'),
            event.get('market_scope_json'),
            event_id
        ))
        
        updated_count += 1
        
        if updated_count % 100 == 0:
            print(f"  Updated {updated_count}/{len(events_to_update)}...")
    
    conn.commit()
    conn.close()
    
    print(f"\n✓ Backfilled semantic fields for {updated_count} events.")
    
    # Show summary
    cursor = get_db().cursor()
    cursor.execute("SELECT event_type, COUNT(*) as cnt FROM events WHERE event_type IS NOT NULL GROUP BY event_type")
    event_type_counts = {row['event_type']: row['cnt'] for row in cursor.fetchall()}
    
    cursor.execute("SELECT signal_level, COUNT(*) as cnt FROM events WHERE signal_level IS NOT NULL GROUP BY signal_level")
    signal_level_counts = {row['signal_level']: row['cnt'] for row in cursor.fetchall()}
    
    print(f"\nSummary:")
    print(f"  Event Types: {dict(sorted(event_type_counts.items()))}")
    print(f"  Signal Levels: {dict(sorted(signal_level_counts.items()))}")

if __name__ == '__main__':
    backfill_semantics()
