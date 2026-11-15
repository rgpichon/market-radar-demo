"""
Provider-Level Throttling

Tracks per-host cooldown periods and automatically reduces concurrency
when rate limits (429/503) are detected.
"""
import json
import time
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse


THROTTLE_STATE_FILE = Path(__file__).parent.parent / "_cache" / "host_throttle.json"
DEFAULT_COOLDOWN = 60  # 1 minute default cooldown
MAX_COOLDOWN = 3600  # 1 hour max cooldown
CONCURRENCY_REDUCTION_FACTOR = 0.5  # Reduce concurrency by 50% when throttled


class HostThrottle:
    """Manages per-host throttling state."""
    
    def __init__(self, state_file: Path = THROTTLE_STATE_FILE):
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load throttle state from file."""
        if not self.state_file.exists():
            return {}
        
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    
    def _save_state(self):
        """Save throttle state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def _get_host(self, url: str) -> str:
        """Extract host from URL."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split('/')[0]
    
    def is_throttled(self, url: str) -> bool:
        """Check if host is currently throttled."""
        host = self._get_host(url)
        host_state = self.state.get(host, {})
        
        cooldown_until = host_state.get('cooldown_until')
        if not cooldown_until:
            return False
        
        try:
            cooldown_time = datetime.fromisoformat(cooldown_until)
            if cooldown_time > datetime.now(timezone.utc):
                return True
        except Exception:
            pass
        
        # Cooldown expired, clear it
        if 'cooldown_until' in host_state:
            del host_state['cooldown_until']
            self._save_state()
        
        return False
    
    def record_rate_limit(self, url: str, status_code: int, retry_after: Optional[int] = None):
        """Record a rate limit event and set cooldown."""
        host = self._get_host(url)
        
        if host not in self.state:
            self.state[host] = {
                'rate_limit_count': 0,
                'last_rate_limit': None,
                'concurrency': 1.0
            }
        
        host_state = self.state[host]
        host_state['rate_limit_count'] = host_state.get('rate_limit_count', 0) + 1
        host_state['last_rate_limit'] = datetime.now(timezone.utc).isoformat()
        
        # Calculate cooldown
        if retry_after:
            cooldown_seconds = min(retry_after, MAX_COOLDOWN)
        else:
            # Exponential backoff based on rate limit count
            count = host_state['rate_limit_count']
            cooldown_seconds = min(DEFAULT_COOLDOWN * (2 ** min(count - 1, 5)), MAX_COOLDOWN)
        
        cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
        host_state['cooldown_until'] = cooldown_until.isoformat()
        
        # Reduce concurrency
        current_concurrency = host_state.get('concurrency', 1.0)
        host_state['concurrency'] = max(0.1, current_concurrency * CONCURRENCY_REDUCTION_FACTOR)
        
        self._save_state()
    
    def record_success(self, url: str):
        """Record a successful request (gradually restore concurrency)."""
        host = self._get_host(url)
        
        if host not in self.state:
            return
        
        host_state = self.state[host]
        
        # Gradually restore concurrency on success
        current_concurrency = host_state.get('concurrency', 1.0)
        if current_concurrency < 1.0:
            # Increase by 10% per success, up to 1.0
            host_state['concurrency'] = min(1.0, current_concurrency * 1.1)
            self._save_state()
    
    def get_concurrency(self, url: str) -> float:
        """Get current concurrency multiplier for host (0.0 to 1.0)."""
        host = self._get_host(url)
        host_state = self.state.get(host, {})
        return host_state.get('concurrency', 1.0)
    
    def get_wait_time(self, url: str) -> float:
        """Get remaining wait time in seconds if throttled."""
        if not self.is_throttled(url):
            return 0.0
        
        host = self._get_host(url)
        host_state = self.state.get(host, {})
        cooldown_until = host_state.get('cooldown_until')
        
        if not cooldown_until:
            return 0.0
        
        try:
            cooldown_time = datetime.fromisoformat(cooldown_until)
            remaining = (cooldown_time - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, remaining)
        except Exception:
            return 0.0


# Global instance
_throttle = None


def get_throttle() -> HostThrottle:
    """Get global throttle instance."""
    global _throttle
    if _throttle is None:
        _throttle = HostThrottle()
    return _throttle
