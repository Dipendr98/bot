"""
Async HTTP Client with Connection Pooling, Semaphore Control, and TTL Cache.

Prevents thread locks by using:
- aiohttp with persistent session (connection pooling)
- Semaphore to control max concurrent requests
- TTL-based cache with automatic cleanup
- Exponential backoff retry logic

Usage:
    async with AsyncHTTPClient(max_concurrent=100) as client:
        results = await client.batch_request(urls_and_data)
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import aiohttp
from aiohttp import ClientTimeout, TCPConnector


@dataclass
class CacheEntry:
    """Cache entry with TTL support."""
    value: Any
    expires_at: float

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class TTLCache:
    """Thread-safe TTL cache with automatic cleanup."""

    def __init__(self, default_ttl: int = 300, max_size: int = 10000):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._cleanup_task: Optional[asyncio.Task] = None

    def _generate_key(
        self,
        url: str,
        method: str = "GET",
        data: Any = None,
        json_data: Any = None
    ) -> str:
        """Generate unique cache key from request parameters."""
        key_parts = [method.upper(), url]
        if data:
            key_parts.append(
                json.dumps(data, sort_keys=True) if isinstance(data, dict) else str(data)
            )
        if json_data:
            key_parts.append(json.dumps(json_data, sort_keys=True))
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()

    async def get(
        self,
        url: str,
        method: str = "GET",
        data: Any = None,
        json_data: Any = None
    ) -> Optional[Any]:
        """Get cached value if exists and not expired."""
        key = self._generate_key(url, method, data, json_data)
        async with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.is_expired:
                return entry.value
            elif entry:
                del self._cache[key]
        return None

    async def set(
        self,
        url: str,
        value: Any,
        method: str = "GET",
        data: Any = None,
        json_data: Any = None,
        ttl: Optional[int] = None
    ) -> None:
        """Cache a value with TTL."""
        key = self._generate_key(url, method, data, json_data)
        expires_at = time.time() + (ttl or self._default_ttl)

        async with self._lock:
            # Evict oldest if at max size
            if len(self._cache) >= self._max_size:
                await self._evict_expired()
                if len(self._cache) >= self._max_size:
                    # Remove oldest entry
                    oldest_key = min(self._cache, key=lambda k: self._cache[k].expires_at)
                    del self._cache[oldest_key]

            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)

    async def _evict_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        now = time.time()
        expired_keys = [k for k, v in self._cache.items() if v.expires_at < now]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    async def clear(self) -> None:
        """Clear all cached entries."""
        async with self._lock:
            self._cache.clear()

    async def start_cleanup_task(self, interval: int = 60) -> None:
        """Start background cleanup task."""
        async def cleanup_loop():
            while True:
                await asyncio.sleep(interval)
                async with self._lock:
                    await self._evict_expired()

        self._cleanup_task = asyncio.create_task(cleanup_loop())

    async def stop_cleanup_task(self) -> None:
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None


@dataclass
class RequestConfig:
    """Configuration for a single request."""
    url: str
    method: str = "POST"
    data: Optional[Dict[str, Any]] = None
    json_data: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, str]] = None
    timeout: int = 30
    use_cache: bool = False
    cache_ttl: Optional[int] = None
    callback: Optional[Callable] = None
    context: Any = None  # Pass-through context for callback


@dataclass
class RequestResult:
    """Result of an HTTP request."""
    url: str
    status: Optional[int] = None
    data: Any = None
    error: Optional[str] = None
    elapsed: float = 0.0
    from_cache: bool = False
    context: Any = None


class AsyncHTTPClient:
    """
    High-performance async HTTP client with:
    - Connection pooling via persistent aiohttp session
    - Semaphore-based concurrency control (prevents thread explosion)
    - Exponential backoff retry with rate limit handling
    - TTL-based response caching
    """

    def __init__(
        self,
        max_concurrent: int = 100,
        max_connections: int = 100,
        max_connections_per_host: int = 10,
        default_timeout: int = 30,
        max_retries: int = 4,
        initial_retry_delay: float = 2.0,
        cache_ttl: int = 300,
        cache_max_size: int = 10000,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self._max_concurrent = max_concurrent
        self._max_connections = max_connections
        self._max_connections_per_host = max_connections_per_host
        self._default_timeout = default_timeout
        self._max_retries = max_retries
        self._initial_retry_delay = initial_retry_delay
        self._default_headers = default_headers or {}

        self._semaphore: Optional[asyncio.Semaphore] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache = TTLCache(default_ttl=cache_ttl, max_size=cache_max_size)
        self._stats_lock = asyncio.Lock()
        self._stats = {
            "total_requests": 0,
            "successful": 0,
            "failed": 0,
            "retries": 0,
            "cache_hits": 0,
        }

    async def __aenter__(self) -> "AsyncHTTPClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Initialize session and semaphore."""
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        connector = TCPConnector(
            limit=self._max_connections,
            limit_per_host=self._max_connections_per_host,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )

        timeout = ClientTimeout(total=self._default_timeout)

        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=self._default_headers,
        )

        await self._cache.start_cleanup_task()

    async def close(self) -> None:
        """Clean up resources."""
        await self._cache.stop_cleanup_task()
        if self._session:
            await self._session.close()
            self._session = None

    async def _update_stats(self, **kwargs) -> None:
        """Thread-safe stats update."""
        async with self._stats_lock:
            for key, value in kwargs.items():
                if key in self._stats:
                    self._stats[key] += value

    async def request(
        self,
        url: str,
        method: str = "POST",
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        use_cache: bool = False,
        cache_ttl: Optional[int] = None,
    ) -> RequestResult:
        """
        Make a single HTTP request with retry logic.

        Uses semaphore to control concurrency - won't block the event loop.
        """
        if not self._session:
            raise RuntimeError("Client not started. Use 'async with' or call start()")

        start_time = time.time()
        await self._update_stats(total_requests=1)

        # Check cache first
        if use_cache:
            cached = await self._cache.get(url, method, data, json_data)
            if cached is not None:
                await self._update_stats(cache_hits=1, successful=1)
                return RequestResult(
                    url=url,
                    status=200,
                    data=cached,
                    elapsed=time.time() - start_time,
                    from_cache=True,
                )

        # Acquire semaphore - this is the key to preventing thread lock
        async with self._semaphore:
            delay = self._initial_retry_delay
            last_error = None

            for attempt in range(self._max_retries + 1):
                try:
                    request_timeout = ClientTimeout(total=timeout or self._default_timeout)

                    async with self._session.request(
                        method=method,
                        url=url,
                        data=data,
                        json=json_data,
                        headers=headers,
                        timeout=request_timeout,
                    ) as response:
                        # Handle rate limiting
                        if response.status == 429:
                            if attempt < self._max_retries:
                                retry_after = response.headers.get("Retry-After")
                                wait_time = float(retry_after) if retry_after else delay
                                await self._update_stats(retries=1)
                                await asyncio.sleep(wait_time)
                                delay *= 2
                                continue

                        # Parse response
                        try:
                            response_data = await response.json()
                        except (json.JSONDecodeError, aiohttp.ContentTypeError):
                            response_data = await response.text()

                        # Cache successful responses
                        if use_cache and response.status < 400:
                            await self._cache.set(
                                url, response_data, method, data, json_data, cache_ttl
                            )

                        elapsed = time.time() - start_time

                        if response.status < 400:
                            await self._update_stats(successful=1)
                        else:
                            await self._update_stats(failed=1)

                        return RequestResult(
                            url=url,
                            status=response.status,
                            data=response_data,
                            elapsed=elapsed,
                        )

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last_error = str(e)
                    if attempt < self._max_retries:
                        await self._update_stats(retries=1)
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue

            # All retries exhausted
            await self._update_stats(failed=1)
            return RequestResult(
                url=url,
                error=last_error or "Max retries exhausted",
                elapsed=time.time() - start_time,
            )

    async def batch_request(
        self,
        requests: List[Union[Tuple[str, Dict], RequestConfig]],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[RequestResult]:
        """
        Execute multiple requests concurrently with controlled parallelism.

        The semaphore ensures we never exceed max_concurrent active requests,
        preventing thread explosion and event loop blocking.

        Args:
            requests: List of (url, data) tuples or RequestConfig objects
            progress_callback: Optional callback(completed, total) for progress updates

        Returns:
            List of RequestResult in same order as input
        """
        # Normalize input to RequestConfig
        configs: List[RequestConfig] = []
        for req in requests:
            if isinstance(req, RequestConfig):
                configs.append(req)
            elif isinstance(req, tuple):
                url, data = req[0], req[1] if len(req) > 1 else None
                configs.append(RequestConfig(url=url, json_data=data))
            else:
                raise ValueError(f"Invalid request format: {type(req)}")

        total = len(configs)
        completed = 0
        completed_lock = asyncio.Lock()

        async def make_request_with_progress(config: RequestConfig) -> RequestResult:
            nonlocal completed

            result = await self.request(
                url=config.url,
                method=config.method,
                data=config.data,
                json_data=config.json_data,
                headers=config.headers,
                timeout=config.timeout,
                use_cache=config.use_cache,
                cache_ttl=config.cache_ttl,
            )

            result.context = config.context

            # Call per-request callback if provided
            if config.callback:
                try:
                    await config.callback(result) if asyncio.iscoroutinefunction(config.callback) else config.callback(result)
                except Exception:
                    pass

            # Update progress
            async with completed_lock:
                completed += 1
                if progress_callback:
                    try:
                        progress_callback(completed, total)
                    except Exception:
                        pass

            return result

        # Create tasks - semaphore controls actual concurrency
        tasks = [make_request_with_progress(config) for config in configs]

        # gather maintains order
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to RequestResult
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(RequestResult(
                    url=configs[i].url,
                    error=str(result),
                    context=configs[i].context,
                ))
            else:
                final_results.append(result)

        return final_results

    def get_stats(self) -> Dict[str, int]:
        """Get current statistics."""
        return self._stats.copy()

    async def reset_stats(self) -> None:
        """Reset statistics."""
        async with self._stats_lock:
            for key in self._stats:
                self._stats[key] = 0


# Convenience function matching user's pattern
async def make_request(
    session: aiohttp.ClientSession,
    url: str,
    data: Dict[str, Any],
    semaphore: Optional[asyncio.Semaphore] = None,
) -> Optional[Dict[str, Any]]:
    """
    Simple request function with optional semaphore control.

    Use this for quick integration with existing code.
    For better performance, use AsyncHTTPClient instead.
    """
    async def _do_request():
        try:
            async with session.post(url, json=data) as response:
                return await response.json()
        except Exception as e:
            print(f"Error: {e}")
            return None

    if semaphore:
        async with semaphore:
            return await _do_request()
    return await _do_request()


async def batch_requests(
    urls_and_data: List[Tuple[str, Dict[str, Any]]],
    max_concurrent: int = 100,
    timeout: int = 30,
) -> List[Optional[Dict[str, Any]]]:
    """
    Execute batch requests with controlled concurrency.

    Example:
        urls_and_data = [
            ("https://api.example.com/check", {"user": "user1"}),
            ("https://api.example.com/check", {"user": "user2"}),
            ("https://api.example.com/check", {"user": "user3"}),
        ]
        results = await batch_requests(urls_and_data, max_concurrent=50)
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    connector = TCPConnector(
        limit=max_concurrent,
        limit_per_host=10,
        ttl_dns_cache=300,
    )

    timeout_config = ClientTimeout(total=timeout)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout_config,
    ) as session:
        tasks = [
            make_request(session, url, data, semaphore)
            for url, data in urls_and_data
        ]
        results = await asyncio.gather(*tasks)

    return results


# Example usage
if __name__ == "__main__":
    async def main():
        # Method 1: Using AsyncHTTPClient (recommended)
        async with AsyncHTTPClient(max_concurrent=100) as client:
            urls_and_data = [
                ("https://httpbin.org/post", {"user": f"user{i}"})
                for i in range(10)
            ]

            results = await client.batch_request(urls_and_data)

            print(f"Completed: {len(results)} requests")
            print(f"Stats: {client.get_stats()}")

        # Method 2: Using simple batch function
        results = await batch_requests(
            [("https://httpbin.org/post", {"user": f"user{i}"}) for i in range(5)],
            max_concurrent=50,
        )
        print(f"Simple batch: {len(results)} results")

    asyncio.run(main())
