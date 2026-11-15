"""
Gmail Event Extraction

Extract macro-signal events from Gmail messages.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.gmail_parse import parse_gmail_message, extract_attachments_from_message
from utils.email_parse import parse_ics_attachment, extract_domain_from_email
from utils.email_rules import (
    validate_email_event, extract_participant_text, choose_best_link,
    infer_firm_name, extract_date_time_from_text
)
from utils.entity_match import extract_bank_participants_with_evidence
from utils.intel_classifier import (
    classify_intel_type, has_explicit_date, calculate_confidence_score,
    extract_macro_keyword_density, detect_speakers, detect_institutions
)


EVIDENCE_DIR = backend_dir / '_evidence' / 'email'


def extract_newsletter_blocks(body: str, html_body: str = '') -> List[Dict]:
    """
    Extract multiple event-like blocks from newsletter email.
    
    Detects common sections: "Upcoming events", "Webinars", "Register", 
    "Add to calendar", "Join us", etc.
    
    Returns:
        List of candidate event blocks with title, date/time, link, participants
    """
    import re
    from bs4 import BeautifulSoup
    
    blocks = []
    
    # Use HTML if available for better structure detection
    text_to_parse = html_body if html_body else body
    
    # Try HTML parsing first
    if html_body:
        try:
            soup = BeautifulSoup(html_body, 'html.parser')
            
            # Find common newsletter section headers
            section_keywords = [
                'upcoming events', 'upcoming event', 'events', 'webinars', 'webinar',
                'register', 'registration', 'join us', 'add to calendar',
                'save the date', 'mark your calendar', 'outlook', 'briefing'
            ]
            
            # Find sections by header text
            for keyword in section_keywords:
                headers = soup.find_all(['h1', 'h2', 'h3', 'h4', 'strong', 'b'], 
                                       string=re.compile(keyword, re.I))
                for header in headers:
                    # Get next sibling content
                    section = header.find_next_sibling(['div', 'p', 'ul', 'table'])
                    if section:
                        section_text = section.get_text(separator='\n', strip=True)
                        # Extract event-like items from section
                        items = _extract_items_from_section(section_text, section)
                        blocks.extend(items)
            
            # Also look for structured lists/divs with event-like patterns
            for elem in soup.find_all(['div', 'li', 'tr']):
                text = elem.get_text(separator=' ', strip=True)
                if _looks_like_event_block(text):
                    items = _extract_items_from_section(text, elem)
                    blocks.extend(items)
        except Exception:
            pass
    
    # Fallback to plain text parsing
    if not blocks:
        # Look for event-like patterns in plain text
        lines = body.split('\n')
        current_block = []
        
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            
            # Detect section headers
            if any(kw in line_lower for kw in ['upcoming', 'webinar', 'event', 'register', 'join us']):
                if current_block:
                    block_text = '\n'.join(current_block)
                    if _looks_like_event_block(block_text):
                        items = _extract_items_from_section(block_text, None)
                        blocks.extend(items)
                    current_block = []
                current_block.append(line)
            elif current_block:
                current_block.append(line)
                # If we've accumulated enough lines, try to extract
                if len(current_block) >= 3:
                    block_text = '\n'.join(current_block)
                    if _looks_like_event_block(block_text):
                        items = _extract_items_from_section(block_text, None)
                        blocks.extend(items)
                        current_block = []
    
    return blocks


def _looks_like_event_block(text: str) -> bool:
    """Check if text block looks like an event description."""
    import re
    text_lower = text.lower()
    
    # Must have event keywords
    event_keywords = ['webinar', 'conference', 'briefing', 'outlook', 'forum', 
                     'roundtable', 'panel', 'seminar', 'event', 'register', 'join']
    has_keyword = any(kw in text_lower for kw in event_keywords)
    
    # Should have date/time indicators or registration link
    has_date_indicators = bool(re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}[/-]\d{1,2})', text_lower))
    has_link = bool(re.search(r'https?://', text_lower))
    
    return has_keyword and (has_date_indicators or has_link)


def _extract_items_from_section(section_text: str, html_elem) -> List[Dict]:
    """Extract individual event items from a section."""
    import re
    from utils.email_rules import extract_date_time_from_text
    
    items = []
    
    # Try to split into individual items (by lines, bullets, etc.)
    lines = section_text.split('\n')
    current_item = []
    
    for line in lines:
        line = line.strip()
        if not line:
            if current_item:
                item_text = '\n'.join(current_item)
                if len(item_text) > 20:  # Minimum length
                    item = _parse_event_item(item_text, html_elem)
                    if item:
                        items.append(item)
                current_item = []
            continue
        
        # Detect new item (title-like line)
        if re.match(r'^[A-Z][^.!?]{10,}', line) and len(current_item) > 0:
            # Previous item is complete
            item_text = '\n'.join(current_item)
            if len(item_text) > 20:
                item = _parse_event_item(item_text, html_elem)
                if item:
                    items.append(item)
            current_item = [line]
        else:
            current_item.append(line)
    
    # Handle last item
    if current_item:
        item_text = '\n'.join(current_item)
        if len(item_text) > 20:
            item = _parse_event_item(item_text, html_elem)
            if item:
                items.append(item)
    
    return items


def _parse_event_item(item_text: str, html_elem) -> Optional[Dict]:
    """Parse a single event item from text."""
    import re
    from utils.email_rules import extract_date_time_from_text, choose_best_link
    
    # Extract title (first substantial line)
    lines = [l.strip() for l in item_text.split('\n') if l.strip()]
    if not lines:
        return None
    
    title = lines[0]
    if len(title) < 10:
        return None
    
    # Extract date/time
    date_time = extract_date_time_from_text(item_text)
    
    # Extract links
    links = []
    if html_elem:
        from bs4 import BeautifulSoup
        for a in html_elem.find_all('a', href=True):
            links.append((a['href'], a.get_text(strip=True)))
    else:
        # Extract from plain text
        url_pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+'
        for match in re.finditer(url_pattern, item_text):
            links.append((match.group(0), ''))
    
    link = choose_best_link(links) if links else ''
    
    # Extract participants (look for "with", "featuring", "speakers")
    participants = []
    participants_pattern = r'(?:with|featuring|speakers?|panelists?):\s*([^\n]+)'
    for match in re.finditer(participants_pattern, item_text, re.I):
        participants.append(match.group(1).strip())
    
    return {
        'title': title,
        'date_time': date_time,
        'link': link,
        'participants': '; '.join(participants) if participants else '',
        'description': '\n'.join(lines[1:])[:500]  # First 500 chars of description
    }


def extract_events_from_gmail_message(service, message: Dict) -> List[Dict]:
    """
    Extract multiple events from Gmail message (newsletter template parsing).
    
    Returns:
        List of EventRaw dicts (can be empty if no valid events found)
    """
    # Parse message
    parsed = parse_gmail_message(service, message)
    
    events = []
    
    # Priority 1: Check for ICS attachments (one event per ICS)
    ics_events = []
    for filename, content_type, content in parsed.get('attachments', []):
        if content_type == 'text/calendar' or filename.endswith('.ics'):
            ics_data = parse_ics_attachment(content)
            if ics_data:
                ics_event = _build_event_from_ics(parsed, ics_data)
                if ics_event:
                    ics_events.append(ics_event)
    
    # If we have ICS events, prefer them (but still check for additional events in body)
    if ics_events:
        events.extend(ics_events)
    
    # Priority 2: Extract newsletter blocks from body
    body = parsed.get('plain_body', '')
    html_body = parsed.get('html_body', '')
    blocks = extract_newsletter_blocks(body, html_body)
    
    # Convert blocks to events
    for block in blocks:
        event = _build_event_from_block(parsed, block)
        if event:
            events.append(event)
    
    # Priority 3: Fallback to single event extraction (original logic)
    if not events:
        single_event = _extract_single_event_fallback(parsed)
        if single_event:
            events.append(single_event)
    
    # Save evidence
    save_gmail_evidence(parsed.get('gmail_id'), parsed, events, None)
    
    return events


def _build_event_from_ics(parsed: Dict, ics_data: Dict) -> Optional[Dict]:
    """Build event dict from ICS attachment."""
    from utils.email_rules import infer_firm_name, choose_best_link
    from utils.entity_match import extract_bank_participants_with_evidence
    from utils.intel_classifier import (
        classify_intel_type, has_explicit_date, calculate_confidence_score,
        extract_macro_keyword_density, detect_speakers, detect_institutions
    )
    from utils.email_parse import extract_domain_from_email
    
    date_time = ics_data.get('dtstart')
    event_name = ics_data.get('summary', parsed.get('subject', ''))
    description = ics_data.get('description', '')
    ics_url = ics_data.get('url', '')
    
    # Extract links
    links = parsed.get('links', [])
    if ics_url:
        links.insert(0, (ics_url, 'Event URL'))
    link = choose_best_link(links)
    
    # Validate
    subject = parsed.get('subject', '')
    body = parsed.get('plain_body', '')
    is_valid, rejection_reason = validate_email_event(subject, body, date_time, links)
    if not is_valid:
        return None
    
    # Build event (same logic as original)
    return _build_final_event(parsed, event_name, date_time, link, description)


def _build_event_from_block(parsed: Dict, block: Dict) -> Optional[Dict]:
    """Build event dict from extracted newsletter block."""
    from utils.email_rules import validate_email_event, choose_best_link
    
    title = block.get('title', '')
    date_time = block.get('date_time')
    link = block.get('link', '')
    description = block.get('description', '')
    
    if not title or len(title) < 10:
        return None
    
    # Validate
    subject = parsed.get('subject', '')
    body = parsed.get('plain_body', '')
    links = [(link, '')] if link else []
    is_valid, rejection_reason = validate_email_event(subject, body, date_time, links)
    if not is_valid:
        return None
    
    return _build_final_event(parsed, title, date_time, link, description)


def _extract_single_event_fallback(parsed: Dict) -> Optional[Dict]:
    """Original single event extraction logic (fallback)."""
    # This is the original extract_event_from_gmail_message logic
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
    link = choose_best_link(links)
    
    # Validate
    subject = parsed.get('subject', '')
    body = parsed.get('plain_body', '')
    is_valid, rejection_reason = validate_email_event(subject, body, date_time, links)
    
    if not is_valid:
        save_gmail_evidence(parsed.get('gmail_id'), parsed, None, rejection_reason)
        return None
    
    return _build_final_event(parsed, event_name, date_time, link, body)


def _build_final_event(parsed: Dict, event_name: str, date_time: Optional[datetime], 
                       link: str, description: str) -> Dict:
    """Build final event dict with all classification fields."""
    from utils.email_rules import extract_participant_text, infer_firm_name
    from utils.entity_match import extract_bank_participants_with_evidence
    from utils.intel_classifier import (
        classify_intel_type, has_explicit_date, calculate_confidence_score,
        extract_macro_keyword_density, detect_speakers, detect_institutions
    )
    from utils.email_parse import extract_domain_from_email
    
    # Extract participants
    participants_text = extract_participant_text(description or parsed.get('plain_body', ''))
    
    # Entity matching for banks
    bank_participants = []
    if participants_text:
        matched_banks, _ = extract_bank_participants_with_evidence(
            participants_text, method='gmail_participants'
        )
        bank_participants = matched_banks
    else:
        body = parsed.get('plain_body', '')
        matched_banks, _ = extract_bank_participants_with_evidence(
            body[:5000], method='gmail_body'
        )
        bank_participants = matched_banks
    
    # Infer firm name
    from_addr = parsed.get('from_addr', '')
    firm_name = infer_firm_name(from_addr, description or parsed.get('plain_body', ''))
    
    # Infer format
    format_str = 'Unknown'
    body_lower = (description or parsed.get('plain_body', '')).lower()
    if 'online' in body_lower or 'webinar' in body_lower or 'virtual' in body_lower:
        format_str = 'Online'
    elif 'in-person' in body_lower or 'in person' in body_lower:
        format_str = 'In-person'
    elif 'hybrid' in body_lower:
        format_str = 'Hybrid'
    
    # Convert date_time to ISO string
    raw_date_text = ''
    if date_time:
        if date_time.tzinfo is None:
            from datetime import timezone
            date_time = date_time.replace(tzinfo=timezone.utc)
        date_time_iso = date_time.isoformat()
        raw_date_text = 'extracted_from_text'
    else:
        date_time_iso = None
    
    # Classify intel type and calculate confidence
    intel_type, base_confidence = classify_intel_type(
        event_name=event_name,
        description=(description or parsed.get('plain_body', ''))[:1000],
        date_time=date_time_iso,
        link=link
    )
    
    # Determine if date is explicit
    has_explicit = has_explicit_date(date_time_iso, raw_date_text)
    
    # Calculate macro keyword density
    subject = parsed.get('subject', '')
    body_text = description or parsed.get('plain_body', '')
    macro_density = extract_macro_keyword_density(f"{subject} {body_text[:2000]}")
    
    # Detect speakers and institutions
    has_speakers = detect_speakers(f"{subject} {body_text[:1000]}")
    has_institutions = detect_institutions(f"{subject} {body_text[:1000]}")
    
    # Calculate final confidence score
    confidence_score = calculate_confidence_score(
        intel_type=intel_type,
        has_explicit_date=has_explicit,
        macro_keyword_density=macro_density,
        has_speakers=has_speakers,
        has_institutions=has_institutions
    )
    
    # Build event/intel item
    event = {
        'event_name': event_name,
        'date_time': date_time_iso,
        'firm_name': firm_name,
        'link': link,
        'tags_json': ['Email', 'Macro'],
        'format': format_str,
        'bank_participants_json': bank_participants,
        'source_id': f"email:{extract_domain_from_email(from_addr)}",
        'source_type': 'email',
        'gmail_id': parsed.get('gmail_id'),
        'participants_text': participants_text,
        'evidence_path': str(EVIDENCE_DIR / parsed.get('gmail_id')),
        'intel_type': intel_type,
        'has_explicit_date': has_explicit,
        'confidence_score': confidence_score
    }
    
    return event


def extract_event_from_gmail_message(service, message: Dict) -> Optional[Dict]:
    """
    Extract event from Gmail message.
    
    Args:
        service: Gmail service object
        message: Message dict from Gmail API
    
    Returns:
        EventRaw dict if valid event, None if rejected
    """
    # Parse message
    parsed = parse_gmail_message(service, message)
    
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
    
    if not is_valid:
        # Save evidence for rejected
        save_gmail_evidence(parsed.get('gmail_id'), parsed, None, rejection_reason)
        return None
    
    # Extract participants
    participants_text = extract_participant_text(body)
    
    # Entity matching for banks
    bank_participants = []
    if participants_text:
        matched_banks, _ = extract_bank_participants_with_evidence(
            participants_text, method='gmail_participants'
        )
        bank_participants = matched_banks
    else:
        # Fallback: scan entire body
        matched_banks, _ = extract_bank_participants_with_evidence(
            body[:5000], method='gmail_body'
        )
        bank_participants = matched_banks
    
    # Infer firm name
    from_addr = parsed.get('from_addr', '')
    firm_name = infer_firm_name(from_addr, body)
    
    # Infer format
    format_str = 'Unknown'
    body_lower = body.lower()
    if 'online' in body_lower or 'webinar' in body_lower or 'virtual' in body_lower:
        format_str = 'Online'
    elif 'in-person' in body_lower or 'in person' in body_lower:
        format_str = 'In-person'
    elif 'hybrid' in body_lower:
        format_str = 'Hybrid'
    
    # Convert date_time to ISO string
    raw_date_text = ''
    if date_time:
        if date_time.tzinfo is None:
            from datetime import timezone
            date_time = date_time.replace(tzinfo=timezone.utc)
        date_time_iso = date_time.isoformat()
        # Check if date came from ICS (explicit) or text (inferred)
        if ics_data:
            raw_date_text = 'ics_attachment'
        else:
            raw_date_text = 'extracted_from_text'
    else:
        date_time_iso = None
    
    # Classify intel type and calculate confidence
    intel_type, base_confidence = classify_intel_type(
        event_name=event_name,
        description=body[:1000],  # Use first 1000 chars for classification
        date_time=date_time_iso,
        link=link
    )
    
    # Determine if date is explicit
    has_explicit = has_explicit_date(date_time_iso, raw_date_text)
    
    # Calculate macro keyword density
    macro_density = extract_macro_keyword_density(f"{subject} {body[:2000]}")
    
    # Detect speakers and institutions
    has_speakers = detect_speakers(f"{subject} {body[:1000]}")
    has_institutions = detect_institutions(f"{subject} {body[:1000]}")
    
    # Calculate final confidence score
    confidence_score = calculate_confidence_score(
        intel_type=intel_type,
        has_explicit_date=has_explicit,
        macro_keyword_density=macro_density,
        has_speakers=has_speakers,
        has_institutions=has_institutions
    )
    
    # Build event/intel item
    event = {
        'event_name': event_name,
        'date_time': date_time_iso,
        'firm_name': firm_name,
        'link': link,
        'tags_json': ['Email', 'Macro'],
        'format': format_str,
        'bank_participants_json': bank_participants,
        'source_id': f"email:{extract_domain_from_email(from_addr)}",
        'source_type': 'email',
        'gmail_id': parsed.get('gmail_id'),
        'participants_text': participants_text,
        'evidence_path': str(EVIDENCE_DIR / parsed.get('gmail_id')),
        # Intel classification fields (PHASE 1)
        'intel_type': intel_type,
        'has_explicit_date': has_explicit,
        'confidence_score': confidence_score
    }
    
    # Save evidence for accepted event
    save_gmail_evidence(parsed.get('gmail_id'), parsed, event, None)
    
    return event


def save_gmail_evidence(gmail_id: str, parsed: Dict, extracted_events: Optional[List[Dict]], rejection_reason: Optional[str]):
    """
    Save evidence folder for Gmail message.
    
    Args:
        gmail_id: Gmail message ID
        parsed: Parsed message data
        extracted_event: Extracted event (if accepted)
        rejection_reason: Rejection reason (if rejected)
    
    Returns:
        Path to evidence folder
    """
    evidence_folder = EVIDENCE_DIR / gmail_id
    evidence_folder.mkdir(parents=True, exist_ok=True)
    
    import json
    
    # Save headers.json
    headers_data = {
        'gmail_id': gmail_id,
        'thread_id': parsed.get('thread_id'),
        'internal_date': parsed.get('internal_date'),
        'subject': parsed.get('subject'),
        'from_addr': parsed.get('from_addr'),
        'from_name': parsed.get('from_name'),
        'sent_date': parsed.get('sent_date').isoformat() if parsed.get('sent_date') else None
    }
    with open(evidence_folder / 'headers.json', 'w') as f:
        json.dump(headers_data, f, indent=2, default=str)
    
    # Save body.txt
    body_text = parsed.get('plain_body', '')
    with open(evidence_folder / 'body.txt', 'w', encoding='utf-8') as f:
        f.write(body_text)
    
    # Save body.html if exists
    html_body = parsed.get('html_body', '')
    if html_body:
        with open(evidence_folder / 'body.html', 'w', encoding='utf-8') as f:
            f.write(html_body)
    
    # Save ICS attachments
    for filename, content_type, content in parsed.get('attachments', []):
        if content_type == 'text/calendar' or filename.endswith('.ics'):
            with open(evidence_folder / f'attachment_{filename}', 'wb') as f:
                f.write(content)
    
    # Save extracted_events.json (can be multiple from newsletter templates)
    if extracted_events:
        events_data = []
        for event in extracted_events:
            event_data = {
                'event_name': event.get('event_name'),
                'date_time': event.get('date_time'),
                'firm_name': event.get('firm_name'),
                'link': event.get('link'),
                'format': event.get('format'),
                'bank_participants_json': event.get('bank_participants_json', []),
                'participants_text': event.get('participants_text'),
                'intel_type': event.get('intel_type'),
                'confidence_score': event.get('confidence_score'),
                'has_explicit_date': event.get('has_explicit_date')
            }
            events_data.append(event_data)
        with open(evidence_folder / 'extract.json', 'w') as f:
            json.dump(events_data, f, indent=2, default=str)
    
    # Save rejection info if rejected
    if rejection_reason:
        with open(evidence_folder / 'rejection_reason.txt', 'w') as f:
            f.write(rejection_reason)
    
    return evidence_folder
