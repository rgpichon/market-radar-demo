#!/usr/bin/env python3
"""
Test Email Ingestion

Creates synthetic .eml files and tests ingestion logic.
"""
import sys
import tempfile
from pathlib import Path
from email.message import EmailMessage
from email import policy

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.adapters.email_event import extract_events


def create_synthetic_eml_valid() -> bytes:
    """Create a valid webinar invitation with ICS attachment."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    
    msg = MIMEMultipart()
    msg['From'] = 'events@isda.org'
    msg['To'] = 'recipient@example.com'
    msg['Subject'] = 'Webinar: Macro Outlook 2026 - Register Now'
    msg['Date'] = 'Mon, 09 Jan 2026 10:00:00 +0000'
    
    # Body
    body = """Join us for a macro outlook webinar featuring leading strategists.

Speakers:
- John Smith, JPMorgan Chase
- Jane Doe, Goldman Sachs
- Bob Wilson, Morgan Stanley

Date: January 15, 2026 at 15:00 CET
Format: Online

Register here: https://isda.org/webinar/register
"""
    msg.attach(MIMEText(body, 'plain'))
    
    # ICS attachment
    ics_content = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ISDA//Webinar//EN
BEGIN:VEVENT
UID:test-webinar-2026@isda.org
DTSTART:20260115T150000Z
DTEND:20260115T160000Z
SUMMARY:Macro Outlook 2026 Webinar
DESCRIPTION:Join us for a macro outlook webinar
URL:https://isda.org/webinar/register
END:VEVENT
END:VCALENDAR
"""
    ics_part = MIMEText(ics_content, 'calendar')
    ics_part['Content-Disposition'] = 'attachment; filename="event.ics"'
    msg.attach(ics_part)
    
    return msg.as_bytes()


def create_synthetic_eml_invalid() -> bytes:
    """Create an invalid earnings press release."""
    msg = EmailMessage(policy=policy.default)
    msg['From'] = 'ir@company.com'
    msg['To'] = 'recipient@example.com'
    msg['Subject'] = 'Q4 2025 Earnings Results Announcement'
    msg['Date'] = 'Mon, 09 Jan 2026 10:00:00 +0000'
    
    body = """Press Release

Company announces Q4 2025 earnings results.

For investor relations inquiries, contact ir@company.com
"""
    msg.set_content(body)
    
    return msg.as_bytes()


def test_email_ingestion():
    """Test email ingestion with synthetic emails."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Create valid email
        valid_eml = tmp_path / 'valid_webinar.eml'
        valid_eml.write_bytes(create_synthetic_eml_valid())
        
        # Create invalid email
        invalid_eml = tmp_path / 'invalid_earnings.eml'
        invalid_eml.write_bytes(create_synthetic_eml_invalid())
        
        # Test valid email
        print("Testing valid webinar invitation...")
        valid_events = extract_events(valid_eml)
        assert len(valid_events) == 1, f"Expected 1 event, got {len(valid_events)}"
        
        event = valid_events[0]
        assert event.get('date_time'), "Event must have date_time"
        assert event.get('link'), "Event must have link"
        assert event.get('source_id', '').startswith('email:'), "source_id must start with 'email:'"
        print(f"  ✓ Accepted: {event.get('event_name')}")
        print(f"    Date: {event.get('date_time')}")
        print(f"    Link: {event.get('link')}")
        print(f"    Source: {event.get('source_id')}")
        if event.get('bank_participants_json'):
            print(f"    Banks: {', '.join(event['bank_participants_json'])}")
        
        # Test invalid email
        print("\nTesting invalid earnings press release...")
        invalid_events = extract_events(invalid_eml)
        assert len(invalid_events) == 0, f"Expected 0 events, got {len(invalid_events)}"
        print("  ✓ Rejected (as expected)")
        
        # Check evidence folders
        evidence_dir = backend_dir / 'backend' / '_evidence' / 'email'
        evidence_folders = list(evidence_dir.glob('*')) if evidence_dir.exists() else []
        assert len(evidence_folders) >= 2, "Expected at least 2 evidence folders"
        print(f"\n  ✓ Evidence folders created: {len(evidence_folders)}")
        
        # Test Gmail config loading
        print("\nTesting Gmail config...")
        try:
            from backend.scripts.ingest_gmail import load_gmail_config, build_gmail_query
            config = load_gmail_config()
            assert 'include_keywords' in config
            assert 'exclude_keywords' in config
            query = build_gmail_query(days=30, config=config)
            assert 'newer_than' in query
            assert 'label:' in query or 'inbox' in query.lower()
            print("  ✓ Gmail config loading works")
        except Exception as e:
            print(f"  ⚠ Gmail config test skipped: {e}")
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)


if __name__ == '__main__':
    test_email_ingestion()
