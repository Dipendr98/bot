import asyncio
import hashlib
import json
import random
from typing import Any, Dict, Optional
import httpx


class ResponseCache:
    """Simple in-memory cache for HTTP responses"""

    def __init__(self):
        self._cache: Dict[str, Any] = {}

    def _generate_key(self, url: str, method: str = "GET", data: Any = None, json_data: Any = None) -> str:
        """Generate a unique cache key for a request"""
        key_parts = [method.upper(), url]

        if data:
            if isinstance(data, dict):
                key_parts.append(json.dumps(data, sort_keys=True))
            else:
                key_parts.append(str(data))

        if json_data:
            key_parts.append(json.dumps(json_data, sort_keys=True))

        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, url: str, method: str = "GET", data: Any = None, json_data: Any = None) -> Optional[Any]:
        """Get cached response if available"""
        key = self._generate_key(url, method, data, json_data)
        return self._cache.get(key)

    def set(self, url: str, response: Any, method: str = "GET", data: Any = None, json_data: Any = None):
        """Cache a response"""
        key = self._generate_key(url, method, data, json_data)
        self._cache[key] = response

    def clear(self):
        """Clear all cached responses"""
        self._cache.clear()


async def request_with_retry(
    session: httpx.AsyncClient,
    method: str,
    url: str,
    max_retries: int = 4,
    initial_delay: float = 2.0,
    cache: Optional[ResponseCache] = None,
    use_cache: bool = False,
    **kwargs
) -> httpx.Response:
    """
    Make an HTTP request with automatic retry on rate limiting (429) and network errors.
    Args:
        session: httpx AsyncClient session
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds (doubles with each retry)
        cache: Optional ResponseCache instance
        use_cache: Whether to use caching for this request
        **kwargs: Additional arguments to pass to the request
    Returns:
        httpx.Response object
    Raises:
        httpx.HTTPError: If all retries are exhausted
    """

    # Check cache first if enabled
    if use_cache and cache:
        cached_response = cache.get(
            url,
            method,
            kwargs.get('data'),
            kwargs.get('json')
        )
        if cached_response:
            return cached_response

    delay = initial_delay
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            # Make the request
            response = await session.request(method, url, **kwargs)

            # Check for rate limiting
            if response.status_code == 429:
                if attempt < max_retries:
                    # Get retry-after header if available
                    retry_after = response.headers.get('retry-after')
                    if retry_after:
                        try:
                            wait_time = float(retry_after)
                        except ValueError:
                            wait_time = delay
                    else:
                        wait_time = delay

                    jitter = random.uniform(0.2, 0.6)
                    wait_time = min(10.0, wait_time + jitter)

                    print(f"Rate limited (429). Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    delay = min(10.0, delay * 2)  # Exponential backoff with cap
                    continue
                else:
                    # Max retries reached, return the error response
                    print(f"Rate limited (429). Max retries ({max_retries}) exhausted.")
                    return response

            # For other errors, don't retry by default
            # Cache successful responses if caching is enabled
            if use_cache and cache and response.status_code < 400:
                cache.set(url, response, method, kwargs.get('data'), kwargs.get('json'))

            return response

        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            last_exception = e
            if attempt < max_retries:
                print(f"Network error: {type(e).__name__}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff
                continue
            else:
                print(f"Network error: {type(e).__name__}. Max retries ({max_retries}) exhausted.")
                raise

    # This should never be reached, but just in case
    if last_exception:
        raise last_exception
    raise Exception("Unexpected error in request_with_retry")


def safe_json_parse(response: httpx.Response, default: Any = None) -> Any:
    """
    Safely parse JSON response, handling errors gracefully.
    Args:
        response: httpx.Response object
        default: Default value to return if parsing fails
    Returns:
        Parsed JSON data or default value
    """
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: Failed to parse JSON response (status {response.status_code}): {e}")
        print(f"Response text: {response.text[:500]}")  # Print first 500 chars
        return default
