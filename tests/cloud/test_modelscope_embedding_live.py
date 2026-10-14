"""Optional live smoke for the shipped ModelScope embedding model."""

from __future__ import annotations

import math
import os
from importlib.util import find_spec

import pytest

from sci_rag.config import Settings

pytestmark = [
    pytest.mark.cloud,
    pytest.mark.skipif(
        os.environ.get("SCI_RAG_RUN_CLOUD_TESTS") != "1",
        reason="set SCI_RAG_RUN_CLOUD_TESTS=1 for live embedding checks",
    ),
]


async def test_modelscope_embedding_returns_the_configured_dimension() -> None:
    missing = [name for name in ("modelscope", "sentence_transformers") if find_spec(name) is None]
    if missing:
        pytest.skip(
            "missing ModelScope embedding dependencies: "
            + ", ".join(missing)
            + ". Install them with `uv sync --extra modelscope-embedding`."
        )

    from sci_rag.embed.modelscope import ModelScopeEmbedder

    settings = Settings(
        _env_file=None,
        embedding_provider="modelscope",
        embedding_dim=1024,
    )
    embedder = ModelScopeEmbedder(settings)
    vectors = await embedder.embed(["Rice straw is a scientific feedstock."], task="document")

    assert len(vectors) == 1
    assert len(vectors[0]) == settings.embedding_dim
    assert all(math.isfinite(value) for value in vectors[0])
