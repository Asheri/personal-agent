"""The embedding provider interface.

Three implementations ship with the kit:

* :class:`~sci_rag.embed.google.GoogleEmbedder` produces real semantic
  vectors with ``gemini-embedding-001`` through either an AI Studio API
  key or Vertex AI credentials.
* :class:`~sci_rag.embed.modelscope.ModelScopeEmbedder` loads the shipped
  Qwen3 model locally through the optional ModelScope extra.
* :class:`~sci_rag.embed.local_hash.LocalHashEmbedder` is deterministic and
  fully offline. It exists so you can exercise the entire pipeline (and run
  the test suite) with no credentials; its similarity is lexical, so do not
  judge retrieval quality with it.

Every provider states its ``version``. That string is stamped onto each
chunk at embedding time, which is what makes a later model upgrade findable
("re-embed everything whose version is not current") instead of silent.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Literal

EmbeddingTask = Literal["document", "query"]


class EmbeddingDimensionError(RuntimeError):
    """A provider returned a vector that does not match the configured dimension."""


class EmbeddingProvider(ABC):
    """Turns text into fixed-dimension vectors."""

    #: Identifier stamped onto chunks, e.g. "Qwen/Qwen3-Embedding-0.6B@1024".
    version: str
    #: The dimension every returned vector must have.
    dim: int

    @abstractmethod
    async def embed(self, texts: list[str], *, task: EmbeddingTask) -> list[list[float]]:
        """Embed a batch of texts.

        ``task`` distinguishes corpus text ("document") from a user question
        ("query"); asymmetric embedding models use the hint to place both in
        a shared space.
        """

    def assert_dimension(self, vector: list[float]) -> list[float]:
        """Fail loudly on a dimension mismatch instead of letting it surface
        later as an opaque database error."""
        if len(vector) != self.dim:
            raise EmbeddingDimensionError(
                f"{self.version} returned a {len(vector)}-dimension vector but the "
                f"database column is vector({self.dim}). Check SCI_RAG_EMBEDDING_DIM "
                "and SCI_RAG_EMBEDDING_MODEL."
            )
        return vector


def l2_normalize(vector: list[float]) -> list[float]:
    """Scale a vector to unit length (no-op if it already is).

    Reduced-dimension ("Matryoshka") embeddings are truncations of a longer
    vector and are not unit length, but cosine ranking assumes they are, so
    we normalize everything defensively.
    """
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]
