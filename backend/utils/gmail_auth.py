"""
Gmail Authentication Utilities

Handles OAuth flow for Gmail API access.
"""
import sys
import os
from pathlib import Path
from typing import Optional

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    Request = None
    Credentials = None
    InstalledAppFlow = None


# Gmail API scopes (read-only)
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

SECRETS_DIR = backend_dir / '_secrets'
CREDENTIALS_FILE = SECRETS_DIR / 'credentials.json'
TOKEN_FILE = SECRETS_DIR / 'token.json'


def get_gmail_service():
    """
    Get authenticated Gmail service.
    
    Returns:
        Gmail service object or None if credentials not available
    """
    if not Request or not Credentials or not InstalledAppFlow:
        return None
    
    creds = None
    
    # Load existing token
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            pass
    
    # If no valid credentials, do OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        
        if not creds:
            if not CREDENTIALS_FILE.exists():
                return None
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # Save token for next run
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
    # Build service
    try:
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception:
        return None


def check_credentials_available() -> bool:
    """
    Check if Gmail credentials are available.
    
    Returns:
        True if credentials.json exists
    """
    return CREDENTIALS_FILE.exists()
