"""Polite, rate-limited HTTP access shared by enrichment and campaigns."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx

import sci_rag

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class PoliteHttpClient:
    """Fetch JSON with a contact identity and bounded retry behavior."""

    def __init__(
        self,
        *,
        mailto: str,
        client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
        max_retries: int = 3,
        requests_per_second: float | None = 5.0,
    ) -> None:
        if not mailto or "@" not in mailto:
            raise ValueError("mailto must be a contact email address")
        self.mailto = mailto
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._sleep = sleep
        self._clock = clock
        self.max_retries = max_retries
        if requests_per_second is not None and requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second if requests_per_second is not None else None
        self._next_request_at = clock()
        self._rate_lock = asyncio.Lock()

    async def __aenter__(self) -> PoliteHttpClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_json(
        self, url: str, *, params: Mapping[str, str | int] | None = None
    ) -> dict[str, Any]:
        query = dict(params or {})
        if "email" not in query:
            query.setdefault("mailto", self.mailto)
        headers = {
            "User-Agent": f"sci-rag-kit/{sci_rag.__version__} (mailto:{self.mailto})",
            "Accept": "application/json",
        }
        for attempt in range(self.max_retries + 1):
            await self._wait_for_slot()
            response = await self._client.get(url, params=query, headers=headers)
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("JSON response must be an object")
                return payload
            if attempt == self.max_retries:
                response.raise_for_status()
            await self._sleep(_retry_delay(response, attempt))
        raise AssertionError("retry loop exhausted without returning or raising")

    @asynccontextmanager
    async def stream(self, url: str) -> AsyncIterator[httpx.Response]:
        """Stream a non-API resource with the same rate and retry bounds."""
        headers = {
            "User-Agent": f"sci-rag-kit/{sci_rag.__version__}",
            "Accept": "application/pdf",
        }
        for attempt in range(self.max_retries + 1):
            await self._wait_for_slot()
            request = self._client.build_request("GET", url, headers=headers)
            response = await self._client.send(request, stream=True, follow_redirects=True)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.max_retries:
                    try:
                        response.raise_for_status()
                    finally:
                        await response.aclose()
                delay = _retry_delay(response, attempt)
                await response.aclose()
                await self._sleep(delay)
                continue
            try:
                response.raise_for_status()
                yield response
            finally:
                await response.aclose()
            return
        raise AssertionError("retry loop exhausted without yielding or raising")

    async def _wait_for_slot(self) -> None:
        if self._interval is None:
            return
        async with self._rate_lock:
            now = self._clock()
            delay = max(0.0, self._next_request_at - now)
            if delay:
                await self._sleep(delay)
                now = self._clock()
            self._next_request_at = max(now, self._next_request_at) + self._interval


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return min(8.0, 0.5 * (2**attempt))
