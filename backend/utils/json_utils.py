"""JSON utilities for handling fields that may be stored as strings."""
import json


def ensure_dict(x):
    """
    Ensure x is a dict.
    - If x is a string, try json.loads
    - If x is already a dict, return it
    - Otherwise return {}
    """
    if x is None:
        return {}
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            result = json.loads(x)
            if isinstance(result, dict):
                return result
            return {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def ensure_list(x):
    """
    Ensure x is a list.
    - If x is a string, try json.loads
    - If x is already a list, return it
    - Otherwise return []
    """
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        try:
            result = json.loads(x)
            if isinstance(result, list):
                return result
            return []
        except (json.JSONDecodeError, TypeError):
            return []
    return []

