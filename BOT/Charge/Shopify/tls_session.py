import asyncio
from typing import Any, Dict, Optional

import tls_client


class TLSAsyncSession:
    def __init__(
        self,
        client_identifier: str = "chrome_120",
        timeout_seconds: int = 90,
        proxy: Optional[str] = None,
        **default_request_kwargs: Any,
    ) -> None:
        self._session = tls_client.Session(client_identifier=client_identifier)
        self._timeout_seconds = timeout_seconds
        self._default_request_kwargs = default_request_kwargs
        
        # Set proxy if provided
        if proxy:
            self._session.proxies = {
                "http": proxy,
                "https": proxy
            }

    def _normalize_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        normalized = {**self._default_request_kwargs, **kwargs}
        if "follow_redirects" in normalized and "allow_redirects" not in normalized:
            normalized["allow_redirects"] = normalized.pop("follow_redirects")
        if "timeout" in normalized and "timeout_seconds" not in normalized:
            normalized["timeout_seconds"] = normalized.pop("timeout")
        normalized.setdefault("timeout_seconds", self._timeout_seconds)
        return normalized

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Generic request method that supports any HTTP method."""
        normalized = self._normalize_kwargs(kwargs)
        method_lower = method.lower()

        # Get the appropriate method from the underlying session
        session_method = getattr(self._session, method_lower, None)
        if session_method is None:
            raise ValueError(f"Unsupported HTTP method: {method}")

        return await asyncio.to_thread(session_method, url, **normalized)

    async def get(self, url: str, **kwargs: Any) -> Any:
        normalized = self._normalize_kwargs(kwargs)
        return await asyncio.to_thread(self._session.get, url, **normalized)

    async def post(self, url: str, **kwargs: Any) -> Any:
        normalized = self._normalize_kwargs(kwargs)
        return await asyncio.to_thread(self._session.post, url, **normalized)

    async def put(self, url: str, **kwargs: Any) -> Any:
        normalized = self._normalize_kwargs(kwargs)
        return await asyncio.to_thread(self._session.put, url, **normalized)

    async def patch(self, url: str, **kwargs: Any) -> Any:
        normalized = self._normalize_kwargs(kwargs)
        return await asyncio.to_thread(self._session.patch, url, **normalized)

    async def delete(self, url: str, **kwargs: Any) -> Any:
        normalized = self._normalize_kwargs(kwargs)
        return await asyncio.to_thread(self._session.delete, url, **normalized)

    async def head(self, url: str, **kwargs: Any) -> Any:
        normalized = self._normalize_kwargs(kwargs)
        return await asyncio.to_thread(self._session.head, url, **normalized)

    async def options(self, url: str, **kwargs: Any) -> Any:
        normalized = self._normalize_kwargs(kwargs)
        return await asyncio.to_thread(self._session.options, url, **normalized)

    async def close(self) -> None:
        close = getattr(self._session, "close", None)
        if close:
            await asyncio.to_thread(close)

    async def __aenter__(self) -> "TLSAsyncSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
