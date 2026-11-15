import re
from urllib.parse import urljoin, urlparse


def normalize_string(s):
    """Normalize string for comparison/hashing."""
    if not s:
        return ""
    # Lowercase, strip, collapse whitespace
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def normalize_url(url, base_url=None):
    """Normalize and optionally join URL."""
    if not url:
        return ""
    
    # If relative and base_url provided, join
    if base_url and not url.startswith(('http://', 'https://')):
        url = urljoin(base_url, url)
    
    # Parse and reconstruct to normalize
    parsed = urlparse(url)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    if parsed.fragment:
        normalized += f"#{parsed.fragment}"
    
    return normalized

