"""Token counting for chunk sizing.

Chunk boundaries need a consistent measure more than a perfect one. If
``tiktoken`` is installed (the ``tokenizers`` extra) we use its
``cl100k_base`` encoding; otherwise we fall back to a fast offline estimate
(English text averages roughly four characters per token). Both paths are
deterministic, so chunking is reproducible either way; just do not mix the
two within one corpus if you care about perfectly stable chunk boundaries.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache


@lru_cache(maxsize=1)
def get_token_counter() -> Callable[[str], int]:
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")

        def count_exact(text: str) -> int:
            return len(encoding.encode(text))

        return count_exact
    except Exception:
        return estimate_tokens


def estimate_tokens(text: str) -> int:
    """Offline approximation: ~4 characters per token, floor of 1 for non-empty."""
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def count_tokens(text: str) -> int:
    return get_token_counter()(text)
