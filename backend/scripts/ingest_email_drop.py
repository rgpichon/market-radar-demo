#!/usr/bin/env python3
"""
Email Ingestion Script (Mode A: Manual Drop Folder)

Scans backend/_email_ingest/*.eml and ingests valid event invitations.
"""
import sys
import argparse
from pathlib import Path
from collections import Counter

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.adapters.email_event import extract_events
from backend.db import get_db, upsert_event
from backend.utils.contracts import normalize_event


def ingest_eml_file(eml_path: Path, move_processed: bool = False) -> dict:
    """
    Ingest a single .eml file.
    
    Args:
        eml_path: Path to .eml file
        move_processed: If True, move to _processed folder after ingestion
    
    Returns:
        Dict with keys: accepted, rejected, rejection_reason
    """
    try:
        events = extract_events(eml_path)
        
        if events:
            # Process through pipeline normalization
            source_config = {
                'id': 'email_ingest',
                'firm_name': events[0].get('firm_name', 'Email Source'),
                'default_tags_json': ['Email', 'Macro']
            }
            
            # Normalize and upsert
            for event_raw in events:
                normalized, rejection_reason = normalize_event(event_raw, source_config)
                if normalized:
                    # Upsert to database
                    conn = get_db()
                    try:
                        upsert_event(
                            conn,
                            event_name=normalized.get('event_name'),
                            firm_name=normalized.get('firm_name'),
                            date_time=normalized.get('date_time'),
                            link=normalized.get('link'),
                            source_id=normalized.get('source_id', 'email_ingest'),
                            tags_json=normalized.get('tags_json', []),
                            format=normalized.get('format', 'Unknown'),
                            bank_participants_json=normalized.get('bank_participants_json', [])
                        )
                    finally:
                        conn.close()
            
            # Move to processed if requested
            if move_processed:
                processed_dir = eml_path.parent / '_processed'
                processed_dir.mkdir(exist_ok=True)
                new_path = processed_dir / eml_path.name
                eml_path.rename(new_path)
            
            return {'accepted': len(events), 'rejected': 0, 'rejection_reason': None}
        else:
            # Rejected (evidence already saved by extract_events)
            return {'accepted': 0, 'rejected': 1, 'rejection_reason': 'validation_failed'}
    
    except Exception as e:
        return {'accepted': 0, 'rejected': 1, 'rejection_reason': f'error: {str(e)}'}


def main():
    parser = argparse.ArgumentParser(description='Ingest email invitations from drop folder')
    parser.add_argument('--move-processed', action='store_true',
                       help='Move processed .eml files to _processed folder')
    args = parser.parse_args()
    
    email_ingest_dir = Path(backend_dir) / 'backend' / '_email_ingest'
    
    if not email_ingest_dir.exists():
        print(f"Error: {email_ingest_dir} does not exist")
        sys.exit(1)
    
    # Find all .eml files
    eml_files = list(email_ingest_dir.glob('*.eml'))
    
    if not eml_files:
        print("No .eml files found in drop folder")
        return
    
    print(f"Found {len(eml_files)} .eml file(s)")
    print()
    
    total_accepted = 0
    total_rejected = 0
    rejection_reasons = Counter()
    bank_detections = 0
    
    for eml_path in eml_files:
        print(f"Processing: {eml_path.name}")
        result = ingest_eml_file(eml_path, move_processed=args.move_processed)
        
        if result['accepted'] > 0:
            total_accepted += result['accepted']
            print(f"  ✓ Accepted: {result['accepted']} event(s)")
            
            # Check for bank participants
            events = extract_events(eml_path)
            for event in events:
                if event.get('bank_participants_json'):
                    bank_detections += len(event['bank_participants_json'])
        else:
            total_rejected += result['rejected']
            reason = result['rejection_reason'] or 'unknown'
            rejection_reasons[reason] += 1
            print(f"  ✗ Rejected: {reason}")
    
    print()
    print("=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)
    print(f"Total .eml files: {len(eml_files)}")
    print(f"Accepted: {total_accepted}")
    print(f"Rejected: {total_rejected}")
    print()
    
    if rejection_reasons:
        print("Top rejection reasons:")
        for reason, count in rejection_reasons.most_common(5):
            print(f"  {reason}: {count}")
        print()
    
    if bank_detections > 0:
        print(f"Bank detections: {bank_detections}")
    
    print("=" * 60)


if __name__ == '__main__':
    main()
