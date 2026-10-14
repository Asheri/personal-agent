"""A small in-process cache for query embeddings.

During an interactive exchange the same question (or a light edit of it)
gets embedded repeatedly; caching for a minute trims latency and API spend.
Keys are SHA-256 hashes of (provider version, task, text), so raw query
text is never held as a key. Values expire on a monotonic clock and the
cache lives only in process memory.
"""

from __future__ import annotations

import hashlib
import time

from sci_rag.embed.provider import EmbeddingProvider, EmbeddingTask


class QueryEmbeddingCache:
    def __init__(
        self, provider: EmbeddingProvider, *, ttl_s: float = 60.0, max_entries: int = 512
    ) -> None:
        self._provider = provider
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._entries: dict[str, tuple[float, list[float]]] = {}

    async def embed_query(self, text: str, *, use_cache: bool = True) -> list[float]:
        key = self._key(text, "query")
        now = time.monotonic()
        if use_cache:
            hit = self._entries.get(key)
            if hit is not None and now - hit[0] < self._ttl_s:
                return hit[1]
        [vector] = await self._provider.embed([text], task="query")
        if use_cache:
            if len(self._entries) >= self._max_entries:
                self._evict_expired(now)
            if len(self._entries) < self._max_entries:
                self._entries[key] = (now, vector)
        return vector

    def _evict_expired(self, now: float) -> None:
        expired = [k for k, (t, _) in self._entries.items() if now - t >= self._ttl_s]
        for k in expired:
            del self._entries[k]
        if not expired and self._entries:
            # Everything is fresh but we are full; drop the oldest entry.
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            del self._entries[oldest]

    def _key(self, text: str, task: EmbeddingTask) -> str:
        raw = f"{self._provider.version}|{task}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
