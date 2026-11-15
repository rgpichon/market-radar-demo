"""
Email notification sender using SMTP.

Sends notification emails with event details.
"""
import sys
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
import json

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def load_email_config() -> Dict:
    """Load email configuration from preferences or config file."""
    prefs_path = backend_dir / "preferences.json"
    
    if prefs_path.exists():
        try:
            with open(prefs_path) as f:
                prefs = json.load(f)
                channels = prefs.get('notification_channels', {})
                return channels.get('email', {})
        except (json.JSONDecodeError, IOError):
            pass
    
    return {}


def create_email_html(event: Dict) -> str:
    """Create HTML email body for event notification."""
    event_name = event.get('event_name', 'Event')
    firm_name = event.get('firm_name', 'Unknown Firm')
    date_time = event.get('date_time', 'TBD')
    link = event.get('link', '#')
    description = event.get('description', '')
    tags = event.get('tags', [])
    
    tags_html = ', '.join(tags) if tags else 'None'
    
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2>New Event: {event_name}</h2>
        <p><strong>Organizer:</strong> {firm_name}</p>
        <p><strong>Date:</strong> {date_time}</p>
        <p><strong>Tags:</strong> {tags_html}</p>
        {f'<p><strong>Description:</strong> {description[:500]}</p>' if description else ''}
        <p><a href="{link}">View Event Details</a></p>
    </body>
    </html>
    """
    return html


def create_email_text(event: Dict) -> str:
    """Create plain text email body for event notification."""
    event_name = event.get('event_name', 'Event')
    firm_name = event.get('firm_name', 'Unknown Firm')
    date_time = event.get('date_time', 'TBD')
    link = event.get('link', '#')
    
    text = f"""
New Event: {event_name}

Organizer: {firm_name}
Date: {date_time}

View Event: {link}
    """
    return text.strip()


def send_notification_email(event: Dict, recipient: str, config: Optional[Dict] = None) -> bool:
    """
    Send notification email for an event.
    
    Args:
        event: Event dict with event details
        recipient: Email address to send to
        config: Email config dict with:
            - smtp_host: str
            - smtp_port: int
            - smtp_user: str (optional, for auth)
            - smtp_password: str (optional, for auth)
            - from_address: str
            - from_name: str (optional)
    
    Returns:
        True if sent successfully, False otherwise
    """
    if not config:
        config = load_email_config()
    
    if not config.get('smtp_host'):
        return False  # Email not configured
    
    smtp_host = config['smtp_host']
    smtp_port = config.get('smtp_port', 587)
    smtp_user = config.get('smtp_user')
    smtp_password = config.get('smtp_password')
    from_address = config.get('from_address', 'notifications@marketradar.local')
    from_name = config.get('from_name', 'Market Radar')
    
    # Create email message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"New Event: {event.get('event_name', 'Event')}"
    msg['From'] = f"{from_name} <{from_address}>"
    msg['To'] = recipient
    
    # Create HTML email body
    html_body = create_email_html(event)
    text_body = create_email_text(event)
    
    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        # Send email
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_user and smtp_password:
                server.starttls()
                server.login(smtp_user, smtp_password)
            
            server.send_message(msg)
            return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def send_batch_email(events: List[Dict], recipient: str, config: Optional[Dict] = None) -> bool:
    """
    Send batch email notification for multiple events.
    
    Args:
        events: List of event dicts
        recipient: Email address
        config: Email config dict
    
    Returns:
        True if sent successfully
    """
    if not config:
        config = load_email_config()
    
    if not config.get('smtp_host') or not events:
        return False
    
    smtp_host = config['smtp_host']
    smtp_port = config.get('smtp_port', 587)
    smtp_user = config.get('smtp_user')
    smtp_password = config.get('smtp_password')
    from_address = config.get('from_address', 'notifications@marketradar.local')
    from_name = config.get('from_name', 'Market Radar')
    
    # Create aggregated email
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"{len(events)} New Events from Market Radar"
    msg['From'] = f"{from_name} <{from_address}>"
    msg['To'] = recipient
    
    # Create HTML body with event list
    html_parts = [f"<h2>{len(events)} New Events</h2>"]
    for event in events:
        event_name = event.get('event_name', 'Event')
        firm_name = event.get('firm_name', 'Unknown')
        date_time = event.get('date_time', 'TBD')
        link = event.get('link', '#')
        html_parts.append(f"""
        <div style="margin-bottom: 20px; padding: 10px; border: 1px solid #ddd;">
            <h3>{event_name}</h3>
            <p><strong>Organizer:</strong> {firm_name}</p>
            <p><strong>Date:</strong> {date_time}</p>
            <p><a href="{link}">View Details</a></p>
        </div>
        """)
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        {''.join(html_parts)}
    </body>
    </html>
    """
    
    # Plain text version
    text_parts = [f"{len(events)} New Events\n"]
    for event in events:
        text_parts.append(f"""
{event.get('event_name', 'Event')}
Organizer: {event.get('firm_name', 'Unknown')}
Date: {event.get('date_time', 'TBD')}
Link: {event.get('link', '#')}
        """)
    text_body = '\n'.join(text_parts)
    
    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_user and smtp_password:
                server.starttls()
                server.login(smtp_user, smtp_password)
            
            server.send_message(msg)
            return True
    except Exception as e:
        print(f"Error sending batch email: {e}")
        return False
