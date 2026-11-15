"""
Retry handler with exponential backoff for transient failures.

Handles retries for HTTP requests and other transient errors.
"""
import time
from typing import Callable, Type, Tuple, Optional, List
from functools import wraps
import requests


class RetryableError(Exception):
    """Error that should trigger a retry."""
    pass


class PermanentError(Exception):
    """Error that should not be retried."""
    pass


def is_transient_error(error: Exception) -> bool:
    """
    Determine if an error is transient (should retry) or permanent (skip).
    
    Args:
        error: Exception to check
    
    Returns:
        True if transient (retry), False if permanent (skip)
    """
    # Transient errors (retry)
    if isinstance(error, (requests.RequestException, requests.Timeout, requests.ConnectionError)):
        return True
    
    # Permanent errors (skip)
    if isinstance(error, requests.HTTPError):
        response = getattr(error, 'response', None)
        if response:
            status_code = response.status_code
            # 404, 403, 401 are permanent
            if status_code in [404, 403, 401]:
                return False
            # 500, 502, 503, 504 are transient
            if status_code in [500, 502, 503, 504]:
                return True
    
    # Check for HTTPError in response
    if hasattr(error, 'response'):
        response = error.response
        if hasattr(response, 'status_code'):
            status_code = response.status_code
            # 404, 403, 401 are permanent
            if status_code in [404, 403, 401]:
                return False
            # 500, 502, 503, 504 are transient
            if status_code in [500, 502, 503, 504]:
                return True
    
    # Default: treat as transient
    return True


def retry_with_backoff(
    func: Callable,
    max_attempts: int = 3,
    backoff_multiplier: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        func: Function to retry
        max_attempts: Maximum number of attempts (default 3)
        backoff_multiplier: Multiplier for exponential backoff (default 2.0)
        initial_delay: Initial delay in seconds (default 1.0)
        max_delay: Maximum delay in seconds (default 60.0)
        retryable_exceptions: Tuple of exception types to retry
    
    Returns:
        Wrapped function with retry logic
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        delay = initial_delay
        last_error = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except retryable_exceptions as e:
                last_error = e
                
                # Check if error is transient
                if not is_transient_error(e):
                    # Permanent error, don't retry
                    raise PermanentError(f"Permanent error: {e}") from e
                
                # Last attempt, raise error
                if attempt >= max_attempts:
                    raise RetryableError(f"Failed after {max_attempts} attempts: {e}") from e
                
                # Wait before retry
                time.sleep(min(delay, max_delay))
                delay *= backoff_multiplier
        
        # Should not reach here, but raise last error
        if last_error:
            raise last_error
        raise Exception("Retry failed without error")
    
    return wrapper


def retry_request(
    request_func: Callable,
    max_attempts: int = 3,
    backoff_multiplier: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    **request_kwargs
):
    """
    Execute HTTP request with retry logic.
    
    Args:
        request_func: requests.get, requests.post, etc.
        max_attempts: Maximum retry attempts
        backoff_multiplier: Backoff multiplier
        initial_delay: Initial delay
        max_delay: Maximum delay between retries
        **request_kwargs: Arguments to pass to request function
    
    Returns:
        Response object
    
    Raises:
        RetryableError: If all retries fail
        PermanentError: If error is permanent (no retry)
    """
    delay = initial_delay
    last_error = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            response = request_func(**request_kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            last_error = e
            
            # Check if permanent error
            if not is_transient_error(e):
                raise PermanentError(f"Permanent error: {e}") from e
            
            # Last attempt
            if attempt >= max_attempts:
                raise RetryableError(f"Request failed after {max_attempts} attempts: {e}") from e
            
            # Wait and retry
            time.sleep(min(delay, max_delay))
            delay *= backoff_multiplier
    
    # Should not reach here, but raise last error
    if last_error:
        raise RetryableError(f"Request failed after all retries: {last_error}") from last_error
    raise RetryableError("Request failed after all retries")
