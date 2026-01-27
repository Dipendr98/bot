import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional
import httpx


# HTTP status code descriptions for better error messages
HTTP_STATUS_CODES = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found (Redirect)",
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    422: "Unprocessable Entity",
    429: "Too Many Requests (Rate Limited)",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


@dataclass
class APIErrorDetails:
    """Structured error information from API responses"""
    status_code: int
    status_description: str
    error_type: str  # 'http_error', 'empty_response', 'invalid_json', 'api_error'
    message: str
    raw_response: str
    headers: Dict[str, str]
    url: str

    def __str__(self) -> str:
        return (
            f"[{self.error_type.upper()}] {self.status_code} {self.status_description}\n"
            f"URL: {self.url}\n"
            f"Message: {self.message}\n"
            f"Response: {self.raw_response[:500]}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status_code": self.status_code,
            "status_description": self.status_description,
            "error_type": self.error_type,
            "message": self.message,
            "raw_response": self.raw_response,
            "headers": self.headers,
            "url": self.url,
        }


def get_status_description(status_code: int) -> str:
    """Get human-readable description for HTTP status code"""
    return HTTP_STATUS_CODES.get(status_code, f"Unknown Status ({status_code})")


def handle_api_response(response: httpx.Response, url: str = None) -> tuple[bool, Any, Optional[APIErrorDetails]]:
    """
    Handle API response with detailed error information.

    Args:
        response: httpx.Response object
        url: Optional URL for error context (uses response.url if not provided)

    Returns:
        Tuple of (success: bool, data: Any, error: Optional[APIErrorDetails])
        - On success: (True, parsed_json_or_text, None)
        - On error: (False, None, APIErrorDetails)

    Usage:
        response = session.post(url, data=data)
        success, data, error = handle_api_response(response)
        if not success:
            print(error)  # Detailed error info
            return
        # Use data...
    """
    request_url = url or str(response.url)
    status_desc = get_status_description(response.status_code)
    headers_dict = dict(response.headers)

    # Check for HTTP errors (non-2xx status codes)
    if response.status_code >= 400:
        return False, None, APIErrorDetails(
            status_code=response.status_code,
            status_description=status_desc,
            error_type="http_error",
            message=f"HTTP {response.status_code}: {status_desc}",
            raw_response=response.text[:1000] if response.text else "",
            headers=headers_dict,
            url=request_url,
        )

    # Check for empty response
    if not response.text:
        return False, None, APIErrorDetails(
            status_code=response.status_code,
            status_description=status_desc,
            error_type="empty_response",
            message="Empty response body - likely blocked or filtered",
            raw_response="",
            headers=headers_dict,
            url=request_url,
        )

    # Try to parse JSON
    try:
        data = response.json()

        # Check for API-level errors in JSON response
        if isinstance(data, dict):
            # Common error field patterns
            error_msg = (
                data.get("error") or
                data.get("errors") or
                data.get("message") if data.get("success") is False else None or
                data.get("error_message") or
                data.get("errorMessage")
            )
            if error_msg:
                if isinstance(error_msg, list):
                    error_msg = error_msg[0] if error_msg else "Unknown API error"
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))

                return False, data, APIErrorDetails(
                    status_code=response.status_code,
                    status_description=status_desc,
                    error_type="api_error",
                    message=str(error_msg),
                    raw_response=response.text[:1000],
                    headers=headers_dict,
                    url=request_url,
                )

        return True, data, None

    except (json.JSONDecodeError, ValueError) as e:
        return False, None, APIErrorDetails(
            status_code=response.status_code,
            status_description=status_desc,
            error_type="invalid_json",
            message=f"Failed to parse JSON: {str(e)}",
            raw_response=response.text[:1000],
            headers=headers_dict,
            url=request_url,
        )


def handle_api_response_sync(response, url: str = None) -> tuple[bool, Any, Optional[APIErrorDetails]]:
    """
    Handle API response for requests library (sync version).
    Works with both httpx.Response and requests.Response.

    Args:
        response: Response object (requests or httpx)
        url: Optional URL for error context

    Returns:
        Tuple of (success: bool, data: Any, error: Optional[APIErrorDetails])
    """
    request_url = url or str(getattr(response, 'url', 'unknown'))
    status_desc = get_status_description(response.status_code)

    # Handle headers dict extraction
    try:
        headers_dict = dict(response.headers)
    except Exception:
        headers_dict = {}

    # Check for HTTP errors
    if response.status_code >= 400:
        return False, None, APIErrorDetails(
            status_code=response.status_code,
            status_description=status_desc,
            error_type="http_error",
            message=f"HTTP {response.status_code}: {status_desc}",
            raw_response=response.text[:1000] if response.text else "",
            headers=headers_dict,
            url=request_url,
        )

    # Check for empty response
    if not response.text:
        return False, None, APIErrorDetails(
            status_code=response.status_code,
            status_description=status_desc,
            error_type="empty_response",
            message="Empty response body - likely blocked or filtered",
            raw_response="",
            headers=headers_dict,
            url=request_url,
        )

    # Try to parse JSON
    try:
        data = response.json()

        # Check for API-level errors
        if isinstance(data, dict):
            error_msg = (
                data.get("error") or
                data.get("errors") or
                data.get("message") if data.get("success") is False else None or
                data.get("error_message") or
                data.get("errorMessage")
            )
            if error_msg:
                if isinstance(error_msg, list):
                    error_msg = error_msg[0] if error_msg else "Unknown API error"
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))

                return False, data, APIErrorDetails(
                    status_code=response.status_code,
                    status_description=status_desc,
                    error_type="api_error",
                    message=str(error_msg),
                    raw_response=response.text[:1000],
                    headers=headers_dict,
                    url=request_url,
                )

        return True, data, None

    except (json.JSONDecodeError, ValueError) as e:
        return False, None, APIErrorDetails(
            status_code=response.status_code,
            status_description=status_desc,
            error_type="invalid_json",
            message=f"Failed to parse JSON: {str(e)}",
            raw_response=response.text[:1000],
            headers=headers_dict,
            url=request_url,
        )


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

                    print(f"Rate limited (429). Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    delay *= 2  # Exponential backoff
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
