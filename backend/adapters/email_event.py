"""
Email Event Adapter

Extracts macro-signal events from email invitations (.eml files).
"""
import sys
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.email_parse import (
    parse_eml_file, parse_ics_attachment, extract_domain_from_email,
    normalize_email_body
)
from utils.email_rules import (
    validate_email_event, extract_participant_text, choose_best_link,
    infer_firm_name, extract_date_time_from_text
)
from utils.entity_match import extract_bank_participants_with_evidence


EVIDENCE_DIR = Path(backend_dir) / '_evidence' / 'email'


def compute_email_id(from_addr: str, subject: str, sent_date: Optional[datetime], body_preview: str) -> str:
    """
    Compute stable ID for email.
    
    Args:
        from_addr: Sender email
        subject: Email subject
        sent_date: Sent date (or None)
        body_preview: First 2000 chars of body
    
    Returns:
        SHA256 hash string
    """
    date_str = sent_date.isoformat() if sent_date else ''
    content = f"{from_addr}|{subject}|{date_str}|{body_preview[:2000]}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def save_email_evidence(email_id: str, eml_path: Path, parsed_data: Dict, extracted_event: Optional[Dict], rejection_reason: Optional[str]) -> Path:
    """
    Save evidence folder for processed email.
    
    Args:
        email_id: Stable email ID
        eml_path: Path to original .eml file
        parsed_data: Parsed email data
        extracted_event: Extracted event (if accepted)
        rejection_reason: Rejection reason (if rejected)
    
    Returns:
        Path to evidence folder
    """
    evidence_folder = EVIDENCE_DIR / email_id
    evidence_folder.mkdir(parents=True, exist_ok=True)
    
    # Save raw .eml
    raw_eml_path = evidence_folder / 'raw.eml'
    if eml_path.exists():
        import shutil
        shutil.copy2(eml_path, raw_eml_path)
    
    # Save parsed.json
    parsed_json = {
        'from': parsed_data.get('from_addr'),
        'from_name': parsed_data.get('from_name'),
        'subject': parsed_data.get('subject'),
        'sent_date': parsed_data.get('sent_date').isoformat() if parsed_data.get('sent_date') else None,
        'links': parsed_data.get('links', []),
        'chosen_link': extracted_event.get('link') if extracted_event else None,
        'date_time': extracted_event.get('date_time') if extracted_event else None,
        'participants_text': extracted_event.get('participants_text') if extracted_event else None,
        'rejection_reason': rejection_reason,
        'accepted': extracted_event is not None
    }
    
    with open(evidence_folder / 'parsed.json', 'w') as f:
        json.dump(parsed_json, f, indent=2, default=str)
    
    # Save body.txt
    body_text = parsed_data.get('plain_body', '')
    with open(evidence_folder / 'body.txt', 'w', encoding='utf-8') as f:
        f.write(body_text)
    
    # Save ics.json if ICS was parsed
    if 'ics_data' in parsed_data and parsed_data['ics_data']:
        with open(evidence_folder / 'ics.json', 'w') as f:
            json.dump(parsed_data['ics_data'], f, indent=2, default=str)
    
    return evidence_folder


def extract_events(eml_path: Path, source_config: Optional[Dict] = None) -> List[Dict]:
    """
    Extract events from a .eml file.
    
    Args:
        eml_path: Path to .eml file
        source_config: Optional source config (not used in Mode A)
    
    Returns:
        List of EventRaw dicts (empty if rejected)
    """
    # Parse email
    try:
        parsed = parse_eml_file(eml_path)
    except Exception as e:
        # If parsing fails, still create evidence
        email_id = hashlib.sha256(str(eml_path).encode()).hexdigest()
        evidence_folder = save_email_evidence(
            email_id, eml_path, {}, None, f'parse_error: {str(e)}'
        )
        return []
    
    # Check for ICS attachment
    ics_data = None
    date_time = None
    event_name = None
    ics_url = None
    
    for filename, content_type, content in parsed.get('attachments', []):
        if content_type == 'text/calendar' or filename.endswith('.ics'):
            ics_data = parse_ics_attachment(content)
            if ics_data:
                if 'dtstart' in ics_data:
                    dt = ics_data['dtstart']
                    if isinstance(dt, datetime):
                        date_time = dt
                if 'summary' in ics_data:
                    event_name = ics_data['summary']
                if 'url' in ics_data:
                    ics_url = ics_data['url']
            break
    
    # If no ICS, try to extract from text
    if not date_time:
        body = parsed.get('plain_body', '')
        date_time = extract_date_time_from_text(body)
    
    # If no event name from ICS, use subject
    if not event_name:
        event_name = parsed.get('subject', '')
    
    # Extract links
    links = parsed.get('links', [])
    if ics_url:
        links.insert(0, (ics_url, 'Event URL'))
    
    # Choose best link
    link = choose_best_link(links)
    
    # Validate
    subject = parsed.get('subject', '')
    body = parsed.get('plain_body', '')
    is_valid, rejection_reason = validate_email_event(subject, body, date_time, links)
    
    # Compute email ID
    email_id = compute_email_id(
        parsed.get('from_addr', ''),
        subject,
        parsed.get('sent_date'),
        body
    )
    
    # Extract participants
    participants_text = extract_participant_text(body)
    
    # Entity matching for banks
    bank_participants = []
    if participants_text:
        matched_banks, _ = extract_bank_participants_with_evidence(
            participants_text, method='email_participants'
        )
        bank_participants = matched_banks
    else:
        # Fallback: scan entire body
        matched_banks, _ = extract_bank_participants_with_evidence(
            body[:5000], method='email_body'
        )
        bank_participants = matched_banks
    
    # Infer firm name
    from_addr = parsed.get('from_addr', '')
    firm_name = infer_firm_name(from_addr, body)
    
    # Infer format (simple heuristic)
    format_str = 'Unknown'
    body_lower = body.lower()
    if 'online' in body_lower or 'webinar' in body_lower or 'virtual' in body_lower:
        format_str = 'Online'
    elif 'in-person' in body_lower or 'in person' in body_lower:
        format_str = 'In-person'
    elif 'hybrid' in body_lower:
        format_str = 'Hybrid'
    
    # Prepare extracted event
    extracted_event = None
    if is_valid:
        # Convert date_time to ISO string
        if date_time:
            if date_time.tzinfo is None:
                from datetime import timezone
                date_time = date_time.replace(tzinfo=timezone.utc)
            date_time_iso = date_time.isoformat()
        else:
            date_time_iso = None
        
        extracted_event = {
            'event_name': event_name,
            'date_time': date_time_iso,
            'firm_name': firm_name,
            'link': link,
            'tags_json': ['Email', 'Macro'],
            'format': format_str,
            'bank_participants_json': bank_participants,
            'source_id': f"email:{extract_domain_from_email(from_addr)}",
            'source_type': 'email',
            'participants_text': participants_text,
            'evidence_path': str(EVIDENCE_DIR / email_id)
        }
    
    # Save evidence
    parsed['ics_data'] = ics_data
    evidence_folder = save_email_evidence(
        email_id, eml_path, parsed, extracted_event, rejection_reason
    )
    
    if extracted_event:
        # Update evidence_path with actual path
        extracted_event['evidence_path'] = str(evidence_folder)
        return [extracted_event]
    
    return []
