"""
Gmail Message Parsing

Parse Gmail API message objects into structured data.
"""
import sys
import base64
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from email.utils import parsedate_to_datetime

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from utils.email_parse import parse_ics_attachment, normalize_email_body
from utils.email_rules import extract_date_time_from_text
import re


def normalize_sender_email(email: str) -> str:
    """
    Normalize sender email to canonical form.
    
    Handles:
    - "via" senders (mailing lists)
    - Name <email> format
    - Lowercase normalization
    
    Returns:
        Canonical email address
    """
    if not email:
        return ''
    
    # Extract email from "Name <email>" format
    match = re.search(r'<([^>]+)>', email)
    if match:
        email = match.group(1)
    else:
        # Remove name if present
        email = email.split('<')[0].strip()
    
    # Handle "via" senders - extract original sender if possible
    if ' via ' in email.lower():
        # Try to extract original sender from format: "original@domain.com via list@domain.com"
        parts = email.lower().split(' via ')
        if len(parts) > 1:
            # Prefer first part (original sender)
            email = parts[0].strip()
    
    # Normalize to lowercase
    email = email.lower().strip()
    
    return email

try:
    import html2text
except ImportError:
    html2text = None


def decode_message_body(message_parts: List[Dict]) -> Tuple[str, str]:
    """
    Decode Gmail message parts into plain text and HTML.
    
    Args:
        message_parts: List of message part dicts from Gmail API
    
    Returns:
        (plain_body, html_body) tuple
    """
    plain_body = ''
    html_body = ''
    
    def extract_part(part: Dict):
        nonlocal plain_body, html_body
        
        mime_type = part.get('mimeType', '')
        body_data = part.get('body', {})
        data = body_data.get('data')
        
        if data:
            try:
                decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
                if mime_type == 'text/plain':
                    plain_body = decoded
                elif mime_type == 'text/html':
                    html_body = decoded
            except Exception:
                pass
        
        # Recurse into nested parts
        nested_parts = part.get('parts', [])
        for nested in nested_parts:
            extract_part(nested)
    
    for part in message_parts:
        extract_part(part)
    
    # Convert HTML to text if needed
    if html_body and not plain_body:
        if html2text:
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = True
            plain_body = h.handle(html_body)
        else:
            import re
            plain_body = re.sub(r'<[^>]+>', '', html_body)
    
    return plain_body, html_body


def extract_attachments_from_message(service, user_id: str, message_id: str, message_parts: List[Dict]) -> List[Tuple[str, str, bytes]]:
    """
    Extract attachments from Gmail message.
    
    Args:
        service: Gmail service object
        user_id: Gmail user ID (usually 'me')
        message_id: Message ID
        message_parts: List of message part dicts
    
    Returns:
        List of (filename, content_type, content) tuples
    """
    attachments = []
    
    def extract_part(part: Dict):
        attachment_id = part.get('body', {}).get('attachmentId')
        filename = part.get('filename', '')
        mime_type = part.get('mimeType', '')
        
        if attachment_id and filename:
            try:
                attachment = service.users().messages().attachments().get(
                    userId=user_id,
                    messageId=message_id,
                    id=attachment_id
                ).execute()
                
                data = attachment.get('data', '')
                if data:
                    content = base64.urlsafe_b64decode(data)
                    attachments.append((filename, mime_type, content))
            except Exception:
                pass
        
        # Recurse into nested parts
        nested_parts = part.get('parts', [])
        for nested in nested_parts:
            extract_part(nested)
    
    for part in message_parts:
        extract_part(part)
    
    return attachments


def parse_gmail_message(service, message: Dict) -> Dict:
    """
    Parse a Gmail API message object into structured data.
    
    Args:
        service: Gmail service object
        message: Message dict from Gmail API
    
    Returns:
        Dict with keys:
            - gmail_id: Message ID
            - thread_id: Thread ID
            - internal_date: Internal date timestamp
            - subject: Email subject
            - from_addr: Sender email
            - from_name: Sender name
            - sent_date: Parsed sent date
            - plain_body: Plain text body
            - html_body: HTML body
            - links: List of (url, text) tuples
            - attachments: List of (filename, content_type, content) tuples
            - sha256: Hash of message content for deduplication
    """
    gmail_id = message['id']
    thread_id = message.get('threadId', '')
    internal_date = message.get('internalDate', '')
    
    # Extract headers
    headers = message.get('payload', {}).get('headers', [])
    subject = ''
    from_addr = ''
    from_name = None
    date_header = ''
    
    for header in headers:
        name = header.get('name', '').lower()
        value = header.get('value', '')
        if name == 'subject':
            subject = value
        elif name == 'from':
            from_addr = value
            # Parse "Name <email@domain.com>"
            if '<' in value:
                import re
                match = re.match(r'^(.+?)\s*<(.+?)>$', value)
                if match:
                    from_name = match.group(1).strip('"\'')
                    from_addr = match.group(2).strip()
        elif name == 'reply-to':
            # Handle "via" senders - prefer reply-to if from contains "via"
            if 'via' in from_addr.lower() and value:
                from_addr = value
        elif name == 'date':
            date_header = value
    
    # Parse sent date
    sent_date = None
    if date_header:
        try:
            sent_date = parsedate_to_datetime(date_header)
        except (ValueError, TypeError):
            pass
    
    # Extract body
    payload = message.get('payload', {})
    parts = payload.get('parts', [])
    if not parts:
        # Single part message
        parts = [payload]
    
    plain_body, html_body = decode_message_body(parts)
    plain_body = normalize_email_body(plain_body)
    
    # Extract links from HTML
    links = []
    if html_body:
        import re
        href_pattern = r'href=["\']([^"\']+)["\']'
        for match in re.finditer(href_pattern, html_body, re.IGNORECASE):
            url = match.group(1)
            links.append((url, ''))
    
    # Extract raw URLs from plain text
    import re
    url_pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+'
    for match in re.finditer(url_pattern, plain_body):
        url = match.group(0).rstrip('.,;!?)')
        if url not in [l[0] for l in links]:
            links.append((url, ''))
    
    # Extract attachments
    attachments = extract_attachments_from_message(service, 'me', gmail_id, parts)
    
    # Normalize sender email (canonical form)
    from_addr = normalize_sender_email(from_addr)
    
    # Compute SHA256 for deduplication (use normalized sender)
    content_for_hash = f"{from_addr}|{subject}|{internal_date}|{plain_body[:2000]}"
    sha256 = hashlib.sha256(content_for_hash.encode('utf-8')).hexdigest()
    
    return {
        'gmail_id': gmail_id,
        'thread_id': thread_id,
        'internal_date': internal_date,
        'subject': subject,
        'from_addr': from_addr,
        'from_name': from_name,
        'sent_date': sent_date,
        'plain_body': plain_body,
        'html_body': html_body,
        'links': links,
        'attachments': attachments,
        'sha256': sha256
    }
