#!/usr/bin/env python3
"""
Gmail Ingestion Sanity Check (Local Mode)

Tests Gmail extraction logic on local .eml files without requiring Gmail credentials.
"""
import sys
import argparse
from pathlib import Path
from collections import Counter

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.utils.email_parse import parse_eml_file
from backend.utils.gmail_event_extract import extract_event_from_gmail_message
from backend.utils.contracts import normalize_event


def main():
    parser = argparse.ArgumentParser(description='Test Gmail extraction on local .eml files')
    parser.add_argument('--dir', type=str, default='backend/_email_ingest', help='Directory with .eml files')
    parser.add_argument('--max', type=int, default=10, help='Max files to process')
    args = parser.parse_args()
    
    eml_dir = Path(backend_dir) / args.dir
    if not eml_dir.exists():
        print(f"Directory not found: {eml_dir}")
        print("Place .eml files in backend/_email_ingest/ to test extraction")
        return 0
    
    eml_files = list(eml_dir.glob('*.eml'))[:args.max]
    
    if not eml_files:
        print(f"No .eml files found in {eml_dir}")
        return 0
    
    print(f"Processing {len(eml_files)} .eml file(s)")
    print()
    
    scanned = 0
    extracted = 0
    rejected = 0
    rejection_reasons = Counter()
    
    for eml_path in eml_files:
        scanned += 1
        print(f"[{scanned}/{len(eml_files)}] {eml_path.name}")
        
        try:
            # Parse .eml file
            parsed = parse_eml_file(str(eml_path))
            if not parsed:
                rejected += 1
                rejection_reasons['parse_failed'] += 1
                print(f"  ✗ Parse failed")
                continue
            
            # Simulate Gmail message format
            gmail_message = {
                'id': f'local_{eml_path.stem}',
                'threadId': 'local_thread',
                'internalDate': str(int(parsed.get('sent_date', 0).timestamp() * 1000)) if parsed.get('sent_date') else '0',
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': parsed.get('from_addr', '')},
                        {'name': 'Subject', 'value': parsed.get('subject', '')},
                        {'name': 'Date', 'value': str(parsed.get('sent_date', ''))}
                    ],
                    'parts': []
                }
            }
            
            # Extract event (mock service - not used for local files)
            class MockService:
                pass
            
            # Build event dict from parsed .eml
            from backend.utils.email_rules import (
                validate_email_event, extract_participant_text, choose_best_link,
                infer_firm_name, extract_date_time_from_text
            )
            from backend.utils.entity_match import extract_bank_participants_with_evidence
            from backend.utils.intel_classifier import (
                classify_intel_type, has_explicit_date, calculate_confidence_score,
                extract_macro_keyword_density, detect_speakers, detect_institutions
            )
            
            subject = parsed.get('subject', '')
            body = parsed.get('plain_body', '')
            links = parsed.get('links', [])
            date_time = extract_date_time_from_text(body)
            
            # Validate
            is_valid, rejection_reason = validate_email_event(subject, body, date_time, links)
            if not is_valid:
                rejected += 1
                rejection_reasons[rejection_reason or 'validation_failed'] += 1
                print(f"  ✗ Rejected: {rejection_reason}")
                continue
            
            # Extract event details
            link = choose_best_link(links) if links else ''
            firm_name = infer_firm_name(parsed.get('from_addr', ''), body)
            participants_text = extract_participant_text(body)
            bank_participants = []
            if participants_text:
                matched_banks, _ = extract_bank_participants_with_evidence(participants_text, method='gmail_participants')
                bank_participants = matched_banks
            
            # Classify intel
            date_time_iso = date_time.isoformat() if date_time else None
            intel_type, base_confidence = classify_intel_type(
                event_name=subject,
                description=body[:1000],
                date_time=date_time_iso,
                link=link
            )
            has_explicit = has_explicit_date(date_time_iso, '')
            macro_density = extract_macro_keyword_density(f"{subject} {body[:2000]}")
            has_speakers = detect_speakers(f"{subject} {body[:1000]}")
            has_institutions = detect_institutions(f"{subject} {body[:1000]}")
            confidence_score = calculate_confidence_score(
                intel_type=intel_type,
                has_explicit_date=has_explicit,
                macro_keyword_density=macro_density,
                has_speakers=has_speakers,
                has_institutions=has_institutions
            )
            
            extracted += 1
            print(f"  ✓ Extracted: {subject[:60]}")
            print(f"    Firm: {firm_name}")
            print(f"    Type: {intel_type}, Confidence: {confidence_score}")
            print(f"    Date: {date_time_iso or 'undated'}")
            
        except Exception as e:
            rejected += 1
            rejection_reasons[f'error: {str(e)[:30]}'] += 1
            print(f"  ✗ Error: {e}")
    
    print()
    print("=" * 60)
    print("SANITY CHECK SUMMARY")
    print("=" * 60)
    print(f"Scanned: {scanned}")
    print(f"Extracted: {extracted}")
    print(f"Rejected: {rejected}")
    print()
    if rejection_reasons:
        print("Top rejection reasons:")
        for reason, count in rejection_reasons.most_common(5):
            print(f"  {reason}: {count}")
    print("=" * 60)


if __name__ == '__main__':
    main()
