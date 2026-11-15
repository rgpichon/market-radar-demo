"""
Email Parsing Utilities

Parse .eml files, extract text, links, and ICS attachments.
"""
import sys
import re
import email
import email.policy
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from email.utils import parsedate_to_datetime

try:
    import html2text
except ImportError:
    html2text = None

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from icalendar import Calendar, Event as ICalEvent
except ImportError:
    Calendar = None
    ICalEvent = None


def parse_eml_file(eml_path: Path) -> Dict:
    """
    Parse a .eml file and extract structured data.
    
    Args:
        eml_path: Path to .eml file
    
    Returns:
        Dict with keys:
            - from_addr: sender email address
            - from_name: sender name (if available)
            - subject: email subject
            - sent_date: datetime object (if parseable)
            - plain_body: plain text body
            - html_body: HTML body (if present)
            - links: list of (url, text) tuples
            - attachments: list of (filename, content_type, content) tuples
    """
    with open(eml_path, 'rb') as f:
        msg = email.message_from_bytes(f.read(), policy=email.policy.default)
    
    # Extract from
    from_header = msg.get('From', '')
    from_addr = from_header
    from_name = None
    if '<' in from_header:
        # "Name <email@domain.com>"
        match = re.match(r'^(.+?)\s*<(.+?)>$', from_header)
        if match:
            from_name = match.group(1).strip('"\'')
            from_addr = match.group(2).strip()
    else:
        from_addr = from_header.strip()
    
    # Extract subject
    subject = msg.get('Subject', '')
    
    # Extract sent date
    sent_date = None
    date_header = msg.get('Date')
    if date_header:
        try:
            sent_date = parsedate_to_datetime(date_header)
        except (ValueError, TypeError):
            pass
    
    # Extract body
    plain_body = ''
    html_body = ''
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        plain_body = payload.decode('utf-8', errors='replace')
                    except:
                        plain_body = payload.decode('latin-1', errors='replace')
            elif content_type == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        html_body = payload.decode('utf-8', errors='replace')
                    except:
                        html_body = payload.decode('latin-1', errors='replace')
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                body_text = payload.decode('utf-8', errors='replace')
            except:
                body_text = payload.decode('latin-1', errors='replace')
            
            if content_type == 'text/html':
                html_body = body_text
            else:
                plain_body = body_text
    
    # Convert HTML to text if needed
    if html_body and not plain_body:
        if html2text:
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = True
            plain_body = h.handle(html_body)
        else:
            # Fallback: simple HTML stripping
            plain_body = re.sub(r'<[^>]+>', '', html_body)
    
    # Extract links from HTML
    links = []
    if html_body:
        # Extract href links
        href_pattern = r'href=["\']([^"\']+)["\']'
        for match in re.finditer(href_pattern, html_body, re.IGNORECASE):
            url = match.group(1)
            # Find link text (simple heuristic)
            text = ''
            link_start = match.start()
            # Look for text between > and < after the href
            after_href = html_body[link_start:link_start+200]
            text_match = re.search(r'>([^<]+)<', after_href)
            if text_match:
                text = text_match.group(1).strip()
            links.append((url, text))
    
    # Extract raw URLs from plain text
    url_pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+'
    for match in re.finditer(url_pattern, plain_body):
        url = match.group(0).rstrip('.,;!?)')
        if url not in [l[0] for l in links]:
            links.append((url, ''))
    
    # Extract attachments
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = part.get('Content-Disposition', '')
            if 'attachment' in content_disposition:
                filename = part.get_filename()
                content_type = part.get_content_type()
                payload = part.get_payload(decode=True)
                if filename and payload:
                    attachments.append((filename, content_type, payload))
    
    return {
        'from_addr': from_addr,
        'from_name': from_name,
        'subject': subject,
        'sent_date': sent_date,
        'plain_body': plain_body,
        'html_body': html_body,
        'links': links,
        'attachments': attachments
    }


def parse_ics_attachment(ics_content: bytes) -> Optional[Dict]:
    """
    Parse an ICS attachment and extract event data.
    
    Args:
        ics_content: Raw ICS file content
    
    Returns:
        Dict with keys:
            - dtstart: datetime object
            - summary: event title
            - location: location string
            - description: description text
            - url: event URL
        Or None if parsing fails
    """
    if not Calendar:
        return None
    
    try:
        cal = Calendar.from_ical(ics_content)
        for component in cal.walk():
            if component.name == 'VEVENT':
                result = {}
                
                # DTSTART
                dtstart = component.get('dtstart')
                if dtstart:
                    dt = dtstart.dt
                    if isinstance(dt, datetime):
                        result['dtstart'] = dt
                    else:
                        # date only
                        result['dtstart'] = datetime.combine(dt, datetime.min.time())
                
                # SUMMARY
                summary = component.get('summary')
                if summary:
                    result['summary'] = str(summary)
                
                # LOCATION
                location = component.get('location')
                if location:
                    result['location'] = str(location)
                
                # DESCRIPTION
                description = component.get('description')
                if description:
                    result['description'] = str(description)
                
                # URL
                url = component.get('url')
                if url:
                    result['url'] = str(url)
                
                if result:
                    return result
    except Exception:
        pass
    
    return None


def extract_domain_from_email(email_addr: str) -> str:
    """
    Extract domain from email address.
    
    Args:
        email_addr: Email address string
    
    Returns:
        Domain string (e.g., "example.com")
    """
    if '@' in email_addr:
        return email_addr.split('@')[1].lower()
    return 'unknown'


def normalize_email_body(body: str) -> str:
    """
    Normalize email body text.
    
    Args:
        body: Raw body text
    
    Returns:
        Normalized text (cleaned, deduplicated whitespace)
    """
    # Remove excessive whitespace
    body = re.sub(r'\s+', ' ', body)
    # Remove leading/trailing whitespace
    body = body.strip()
    return body
