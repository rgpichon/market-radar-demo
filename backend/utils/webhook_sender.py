"""
Webhook notification sender.

Sends HTTP POST requests to configured webhook URLs with event data.
"""
import sys
from pathlib import Path
import requests
from typing import Dict, List, Optional
import json
import time

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def load_webhook_config() -> List[Dict]:
    """Load webhook configuration from preferences."""
    prefs_path = backend_dir / "preferences.json"
    
    if prefs_path.exists():
        try:
            with open(prefs_path) as f:
                prefs = json.load(f)
                channels = prefs.get('notification_channels', {})
                webhook_config = channels.get('webhook', {})
                return webhook_config.get('webhooks', [])
        except (json.JSONDecodeError, IOError):
            pass
    
    return []


def send_webhook_notification(event: Dict, webhook_url: str, config: Optional[Dict] = None) -> bool:
    """
    Send webhook notification for an event.
    
    Args:
        event: Event dict
        webhook_url: Webhook URL to POST to
        config: Optional webhook config dict with:
            - headers: Dict[str, str] (custom headers)
            - timeout: int (request timeout in seconds, default 10)
            - retry_count: int (number of retries, default 3)
            - retry_delay: float (seconds between retries, default 1.0)
    
    Returns:
        True if sent successfully, False otherwise
    """
    if not config:
        config = {}
    
    headers = config.get('headers', {'Content-Type': 'application/json'})
    timeout = config.get('timeout', 10)
    retry_count = config.get('retry_count', 3)
    retry_delay = config.get('retry_delay', 1.0)
    
    # Prepare payload
    payload = {
        'event': event,
        'notification_type': 'event_created',
        'timestamp': time.time()
    }
    
    # Try sending with retries
    for attempt in range(retry_count):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            return True  # Success
            
        except requests.RequestException as e:
            if attempt < retry_count - 1:
                time.sleep(retry_delay)
                continue  # Retry
            else:
                print(f"Webhook delivery failed after {retry_count} attempts: {e}")
                return False
    
    return False


def send_webhooks_for_event(event: Dict, webhook_configs: Optional[List[Dict]] = None) -> int:
    """
    Send webhooks to all configured webhook URLs for an event.
    
    Args:
        event: Event dict
        webhook_configs: List of webhook config dicts, or None to load from preferences
    
    Returns:
        Number of successful webhook deliveries
    """
    if not webhook_configs:
        webhook_configs = load_webhook_config()
    
    success_count = 0
    
    for webhook_config in webhook_configs:
        url = webhook_config.get('url')
        if not url:
            continue
        
        config = webhook_config.get('config', {})
        
        if send_webhook_notification(event, url, config):
            success_count += 1
    
    return success_count
