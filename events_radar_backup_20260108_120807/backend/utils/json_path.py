"""
Simple dot-path getter for JSON data extraction.
Supports dict keys and list indices.
"""


def get_path(data, path, default=None):
    """
    Get a value from nested dict/list using dot-path notation.
    
    Examples:
        get_path({'a': {'b': 1}}, 'a.b') => 1
        get_path({'items': [{'name': 'x'}]}, 'items.0.name') => 'x'
        get_path({'results': [1,2,3]}, 'results') => [1,2,3]
    
    Args:
        data: dict or list to traverse
        path: dot-separated path string (e.g., 'results.0.title')
        default: value to return if path not found
    
    Returns:
        Value at path or default
    """
    if not path:
        return data if data is not None else default
    
    if data is None:
        return default
    
    parts = path.split('.')
    current = data
    
    for part in parts:
        if current is None:
            return default
        
        # Try as dict key first
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return default
        # Try as list index
        elif isinstance(current, list):
            try:
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return default
            except ValueError:
                # Not a valid index
                return default
        else:
            return default
    
    return current


def extract_list(data, list_path):
    """
    Extract a list from data at the given path.
    Returns empty list if path not found or not a list.
    """
    result = get_path(data, list_path)
    if isinstance(result, list):
        return result
    return []
