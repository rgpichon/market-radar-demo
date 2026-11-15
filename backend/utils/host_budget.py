"""
Host-aware network budget management.

Tracks per-host request limits and delays to prevent rate limiting during batch operations.
Supports file-backed cooldown persistence across runs.
"""
import json
import time
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from pathlib import Path


class HostBudgetExceeded(Exception):
    """Raised when host budget is exceeded."""
    pass


class HostBudget:
    """Manages per-host request budgets with file-backed cooldown persistence."""
    
    def __init__(
        self,
        min_delay_seconds: float = 1.0,
        max_requests_per_run: int = 20,
        default_cooldown_seconds: int = 60,
        cooldown_registry_file: Optional[Path] = None
    ):
        self.min_delay_seconds = min_delay_seconds
        self.max_requests_per_run = max_requests_per_run
        self.default_cooldown_seconds = default_cooldown_seconds
        
        # File-backed cooldown registry
        if cooldown_registry_file is None:
            cooldown_registry_file = Path(__file__).parent.parent / "_cache" / "host_cooldowns.json"
        self.cooldown_registry_file = cooldown_registry_file
        self._load_cooldown_registry()
        
        # Per-host state: {host: {'requests': int, 'last_request': timestamp, 'cooldown_until': timestamp}}
        self._hosts: Dict[str, Dict] = {}
        
        # Diagnostics
        self._diagnostics: Dict[str, Dict] = {}  # {host: {'requests': int, '429_count': int, '503_count': int, 'blocked': bool}}
    
    def _get_host(self, url: str) -> str:
        """Extract host from URL."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split('/')[0]
    
    def _load_cooldown_registry(self):
        """Load persistent cooldown registry from file."""
        self._cooldown_registry: Dict[str, Dict] = {}
        if self.cooldown_registry_file.exists():
            try:
                with open(self.cooldown_registry_file, 'r') as f:
                    data = json.load(f)
                    # Validate and filter expired cooldowns
                    now = datetime.now(timezone.utc)
                    for host, host_data in data.items():
                        cooldown_until = host_data.get('cooldown_until')
                        if cooldown_until:
                            try:
                                if isinstance(cooldown_until, str):
                                    cooldown_time = datetime.fromisoformat(cooldown_until)
                                else:
                                    continue
                                if cooldown_time > now:
                                    self._cooldown_registry[host] = host_data
                            except Exception:
                                pass
            except Exception:
                pass
    
    def _save_cooldown_registry(self):
        """Save cooldown registry to file."""
        self.cooldown_registry_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.cooldown_registry_file, 'w') as f:
                json.dump(self._cooldown_registry, f, indent=2)
        except Exception:
            pass
    
    def is_host_in_cooldown(self, url: str) -> bool:
        """Check if host is in persistent cooldown (from previous runs)."""
        host = self._get_host(url)
        if host not in self._cooldown_registry:
            return False
        
        host_data = self._cooldown_registry[host]
        cooldown_until = host_data.get('cooldown_until')
        if not cooldown_until:
            return False
        
        try:
            if isinstance(cooldown_until, str):
                cooldown_time = datetime.fromisoformat(cooldown_until)
            else:
                return False
            
            if cooldown_time > datetime.now(timezone.utc):
                return True
            else:
                # Expired, remove from registry
                del self._cooldown_registry[host]
                self._save_cooldown_registry()
                return False
        except Exception:
            return False
    
    def get_cooldown_remaining(self, url: str) -> float:
        """Get remaining cooldown time in seconds (from persistent registry)."""
        host = self._get_host(url)
        if host not in self._cooldown_registry:
            return 0.0
        
        host_data = self._cooldown_registry[host]
        cooldown_until = host_data.get('cooldown_until')
        if not cooldown_until:
            return 0.0
        
        try:
            if isinstance(cooldown_until, str):
                cooldown_time = datetime.fromisoformat(cooldown_until)
            else:
                return 0.0
            
            now = datetime.now(timezone.utc)
            if cooldown_time > now:
                return (cooldown_time - now).total_seconds()
            else:
                return 0.0
        except Exception:
            return 0.0
    
    def acquire(self, url: str) -> float:
        """
        Acquire permission to make a request to this host.
        
        Returns:
            sleep_seconds: How long to sleep before making the request
        
        Raises:
            HostBudgetExceeded: If host budget is exceeded
        """
        host = self._get_host(url)
        now = datetime.now(timezone.utc)
        
        # Initialize host state if needed
        if host not in self._hosts:
            self._hosts[host] = {
                'requests': 0,
                'last_request': None,
                'cooldown_until': None
            }
            self._diagnostics[host] = {
                'requests': 0,
                '429_count': 0,
                '503_count': 0,
                'blocked': False
            }
        
        host_state = self._hosts[host]
        diag = self._diagnostics[host]
        
        # Check persistent cooldown registry first
        if self.is_host_in_cooldown(url):
            remaining = self.get_cooldown_remaining(url)
            diag['blocked'] = True
            raise HostBudgetExceeded(
                f"Host {host} is in persistent cooldown ({remaining/3600:.1f}h remaining)"
            )
        
        # Check in-memory cooldown
        if host_state.get('cooldown_until'):
            cooldown_until = host_state['cooldown_until']
            if isinstance(cooldown_until, str):
                cooldown_until = datetime.fromisoformat(cooldown_until)
            
            if cooldown_until > now:
                remaining = (cooldown_until - now).total_seconds()
                diag['blocked'] = True
                raise HostBudgetExceeded(
                    f"Host {host} is in cooldown until {cooldown_until.isoformat()} "
                    f"({remaining:.1f}s remaining)"
                )
            else:
                # Cooldown expired, clear it
                host_state['cooldown_until'] = None
                diag['blocked'] = False
        
        # Check request limit
        if host_state['requests'] >= self.max_requests_per_run:
            diag['blocked'] = True
            raise HostBudgetExceeded(
                f"Host {host} has exceeded max_requests_per_run ({self.max_requests_per_run})"
            )
        
        # Calculate sleep time based on last request
        sleep_seconds = 0.0
        if host_state.get('last_request'):
            last_request = host_state['last_request']
            if isinstance(last_request, str):
                last_request = datetime.fromisoformat(last_request)
            
            time_since_last = (now - last_request).total_seconds()
            if time_since_last < self.min_delay_seconds:
                sleep_seconds = self.min_delay_seconds - time_since_last
        
        # Update state
        host_state['requests'] += 1
        host_state['last_request'] = now.isoformat()
        diag['requests'] = host_state['requests']
        
        return sleep_seconds
    
    def record_result(
        self,
        url: str,
        status_code: Optional[int] = None,
        error_class: Optional[str] = None
    ):
        """
        Record the result of a request.
        
        Args:
            url: The URL that was requested
            status_code: HTTP status code (if available)
            error_class: Error classification (e.g., 'deferred_transient_network', 'blocked_hard')
        """
        host = self._get_host(url)
        if host not in self._diagnostics:
            return
        
        diag = self._diagnostics[host]
        
        # Track status codes
        if status_code == 429:
            diag['429_count'] = diag.get('429_count', 0) + 1
            # Set cooldown (in-memory and persistent)
            cooldown_seconds = self.default_cooldown_seconds * (2 ** min(diag['429_count'] - 1, 3))
            self._set_cooldown(host, cooldown_seconds)
            self._set_persistent_cooldown(host, cooldown_seconds)
        elif status_code == 503:
            diag['503_count'] = diag.get('503_count', 0) + 1
            # Set cooldown (in-memory and persistent)
            cooldown_seconds = self.default_cooldown_seconds * (2 ** min(diag['503_count'] - 1, 3))
            self._set_cooldown(host, cooldown_seconds)
            self._set_persistent_cooldown(host, cooldown_seconds)
        
        # Track error classes
        if error_class in ['deferred_transient_network', 'blocked_hard']:
            diag['blocked'] = True
            if error_class == 'blocked_hard':
                # Longer cooldown for hard blocks (persist for 24 hours)
                cooldown_seconds = self.default_cooldown_seconds * 10
                self._set_cooldown(host, cooldown_seconds)
                self._set_persistent_cooldown(host, 24 * 3600)  # 24 hours
            elif error_class == 'deferred_transient_network':
                # Moderate cooldown for transient errors (persist for 2 hours)
                cooldown_seconds = self.default_cooldown_seconds * 5
                self._set_cooldown(host, cooldown_seconds)
                self._set_persistent_cooldown(host, 2 * 3600)  # 2 hours
    
    def _set_cooldown(self, host: str, seconds: int):
        """Set in-memory cooldown for a host."""
        if host not in self._hosts:
            self._hosts[host] = {'requests': 0, 'last_request': None, 'cooldown_until': None}
        
        cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self._hosts[host]['cooldown_until'] = cooldown_until.isoformat()
    
    def _set_persistent_cooldown(self, host: str, seconds: int):
        """Set persistent cooldown for a host (saved to file)."""
        cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self._cooldown_registry[host] = {
            'cooldown_until': cooldown_until.isoformat(),
            'set_at': datetime.now(timezone.utc).isoformat(),
            'duration_seconds': seconds
        }
        self._save_cooldown_registry()
    
    def get_diagnostics(self) -> Dict[str, Dict]:
        """Get diagnostics for all hosts."""
        return self._diagnostics.copy()
    
    def get_host_diagnostics(self, url: str) -> Optional[Dict]:
        """Get diagnostics for a specific host."""
        host = self._get_host(url)
        return self._diagnostics.get(host)
    
    def reset(self):
        """Reset in-memory budgets (for new run). Does not clear persistent cooldowns."""
        self._hosts.clear()
        self._diagnostics.clear()
    
    def get_cooldown_registry(self) -> Dict[str, Dict]:
        """Get current cooldown registry (for inspection)."""
        return self._cooldown_registry.copy()


# Global instance
_global_budget: Optional[HostBudget] = None


def get_budget(
    min_delay_seconds: float = 1.0,
    max_requests_per_run: int = 20,
    default_cooldown_seconds: int = 60
) -> HostBudget:
    """Get global budget instance."""
    global _global_budget
    if _global_budget is None:
        _global_budget = HostBudget(
            min_delay_seconds=min_delay_seconds,
            max_requests_per_run=max_requests_per_run,
            default_cooldown_seconds=default_cooldown_seconds
        )
    return _global_budget


def reset_budget():
    """Reset global budget."""
    global _global_budget
    if _global_budget:
        _global_budget.reset()
