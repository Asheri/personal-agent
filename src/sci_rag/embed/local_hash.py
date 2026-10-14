"""A deterministic, offline embedder for tests and dry runs.

It hashes word unigrams and character trigrams into a fixed number of
buckets with alternating signs (the classic feature-hashing trick), then
normalizes to unit length. Two texts that share vocabulary land near each
other, so the retrieval plumbing behaves sensibly end to end, entirely
offline, with bit-for-bit reproducible vectors.

It is a plumbing tool, not a semantic model. Never compare quality numbers
produced with this embedder to numbers produced with a real one.
"""

from __future__ import annotations

import hashlib
import math
import re

from sci_rag.embed.provider import EmbeddingProvider, EmbeddingTask

_WORD_RE = re.compile(r"[a-z0-9]+")


class LocalHashEmbedder(EmbeddingProvider):
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.version = f"local-hash-v1@{dim}"

    async def embed(self, texts: list[str], *, task: EmbeddingTask) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for feature, weight in self._features(text):
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign * weight
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            # An empty or non-alphanumeric text: return a stable arbitrary unit
            # vector so downstream math never divides by zero.
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    def _features(self, text: str) -> list[tuple[str, float]]:
        words = _WORD_RE.findall(text.lower())
        features: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
        for word in words:
            padded = f"^{word}$"
            features.extend((f"c3:{padded[i : i + 3]}", 0.5) for i in range(len(padded) - 2))
        return features
