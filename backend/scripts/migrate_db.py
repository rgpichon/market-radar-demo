#!/usr/bin/env python3
"""
Database Migration Script

Runs all pending migrations to add new columns for macro conversation intelligence features.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import init_db, get_db
import sqlite3


def run_migrations():
    """Run all database migrations."""
    print("Running database migrations...")
    print("=" * 60)
    
    # Initialize database (this runs migrations in init_db)
    init_db()
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check current schema
    cursor.execute("PRAGMA table_info(events)")
    columns = {row[1]: row for row in cursor.fetchall()}
    
    print("\nCurrent events table columns:")
    for col_name in sorted(columns.keys()):
        print(f"  ✓ {col_name}")
    
    # Verify new columns exist
    new_columns = {
        'description': 'Phase 3: Description extraction',
        'participant_roles_json': 'Phase 4: Participant role detection',
        'signal_score': 'Phase 6: Signal quality scoring',
        'intel_type': 'Phase 1: Conversation type classification',
        'confidence_score': 'Phase 1: Classification confidence',
        'location_text': 'Priority 2 Phase 3: Location extraction',
        'location_city': 'Priority 2 Phase 3: Location city',
        'location_country': 'Priority 2 Phase 3: Location country',
        'registration_type': 'Priority 2 Phase 4: Registration type',
        'registration_url': 'Priority 2 Phase 4: Registration URL',
        'registration_deadline': 'Priority 2 Phase 4: Registration deadline',
        'registration_fee': 'Priority 2 Phase 4: Registration fee',
        'speakers_json': 'Priority 2 Phase 2: Structured speaker data'
    }
    
    print("\nVerifying new columns:")
    missing = []
    for col_name, phase in new_columns.items():
        if col_name in columns:
            print(f"  ✓ {col_name} ({phase})")
        else:
            print(f"  ✗ {col_name} ({phase}) - MISSING")
            missing.append(col_name)
    
    if missing:
        print(f"\n⚠️  WARNING: {len(missing)} columns are missing!")
        print("   Run init_db() to add them.")
        conn.close()
        return False
    
    # Check sample data
    cursor.execute("SELECT COUNT(*) FROM events")
    total_events = cursor.fetchone()[0]
    
    if total_events > 0:
        # Check how many have new fields populated
        cursor.execute("SELECT COUNT(*) FROM events WHERE description IS NOT NULL")
        with_description = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM events WHERE intel_type IS NOT NULL")
        with_intel_type = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM events WHERE signal_score IS NOT NULL")
        with_signal_score = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM events WHERE participant_roles_json IS NOT NULL")
        with_roles = cursor.fetchone()[0]
        
        print(f"\nData status (out of {total_events} total events):")
        print(f"  Events with description: {with_description}")
        print(f"  Events with intel_type: {with_intel_type}")
        print(f"  Events with signal_score: {with_signal_score}")
        print(f"  Events with participant_roles: {with_roles}")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("✅ Migration check complete!")
    return True


if __name__ == '__main__':
    success = run_migrations()
    sys.exit(0 if success else 1)
