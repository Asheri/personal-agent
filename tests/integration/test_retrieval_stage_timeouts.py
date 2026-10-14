"""A stage that runs out of budget must not take the others down with it.

Each stage is its own task with its own budget, which is what lets a request
degrade instead of failing. That property is only worth having if it holds
for the expensive optional layers, because those are the ones that run out:
HyDE generates a passage and embeds it before it queries anything, so it is
the slowest layer on every live provider. A completed vector result has to
survive it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from sci_rag.config import Settings
from sci_rag.embed.provider import EmbeddingProvider, EmbeddingTask
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm.client import LLMClient
from sci_rag.retrieve import Retriever

pytestmark = pytest.mark.integration


class SlowLLM(LLMClient):
    """A provider that never answers inside the budget under test."""

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        await asyncio.sleep(30)
        return "unreachable"

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        await asyncio.sleep(30)
        yield "unreachable"

    async def generate_json(self, prompt: str, **kwargs: Any) -> Any:
        await asyncio.sleep(30)
        return {}


class SlowEmbedder(EmbeddingProvider):
    """A real embedder behind a delay, standing in for a slow region."""

    def __init__(self, inner: EmbeddingProvider, *, delay_s: float) -> None:
        self._inner = inner
        self._delay_s = delay_s
        self.version = inner.version
        self.dim = inner.dim

    async def embed(
        self, texts: list[str], *, task: EmbeddingTask = "document"
    ) -> list[list[float]]:
        await asyncio.sleep(self._delay_s)
        return await self._inner.embed(texts, task=task)


@pytest.fixture()
async def corpus(clean_tables, local_embedder, tmp_path: Path):  # type: ignore[no-untyped-def]
    path = tmp_path / "straw.md"
    path.write_text(
        "Rice straw availability in the Colusa Basin was near 310,000 tons in 2023.",
        encoding="utf-8",
    )
    await ingest_entries(
        [CorpusEntry(path=path, title="Colusa straw", license_class="public", source="tests")],
        embedder=local_embedder,
    )


def _budgeted(settings, **overrides):  # type: ignore[no-untyped-def]
    return Settings(
        _env_file=None,
        embedding_provider="local-hash",
        embedding_dim=settings.embedding_dim,
        database_url=settings.database_url,
        domain_dir=settings.domain_dir,
        **overrides,
    )


async def test_a_query_embedding_slower_than_the_database_budget_still_returns(  # type: ignore[no-untyped-def]
    corpus, settings, local_embedder
) -> None:
    """F-016, scaled down: the embedding outlasts the database budget alone.

    Live, this was a 32,945 ms query embedding against a 30-second budget on
    a supported Vertex project. Every stage waiting on that embedding failed
    together and the answer command reported an empty knowledge base. Here
    the embedder sleeps past the database budget and inside the provider
    budget, which is the shape that has to succeed.
    """
    budgeted = _budgeted(settings, deep_stage_timeout_s=0.5, provider_call_timeout_s=5.0)
    retriever = Retriever(
        settings=budgeted, embedder=SlowEmbedder(local_embedder, delay_s=1.5), llm=SlowLLM()
    )

    result = await retriever.retrieve("rice straw availability", profile="deep")

    statuses = {trace.stage: trace.status for trace in result.traces}
    assert statuses["vector"] == "success"
    assert result.items, "the documented route has to retrieve evidence without an override"


async def test_a_stage_that_exhausts_its_budget_does_not_discard_a_completed_one(  # type: ignore[no-untyped-def]
    corpus, settings
) -> None:
    """Graph and HyDE time out; vector and keyword still return their evidence."""
    budgeted = _budgeted(settings, deep_stage_timeout_s=1.0, provider_call_timeout_s=0.5)
    retriever = Retriever(settings=budgeted, llm=SlowLLM())

    result = await retriever.retrieve("rice straw availability", profile="deep")

    statuses = {trace.stage: trace.status for trace in result.traces}
    assert statuses["graph"] == "timeout"
    assert statuses["hyde"] == "timeout"
    assert statuses["vector"] == "success"
    assert result.items, "a completed stage's evidence has to survive a timed-out sibling"


async def test_a_provider_backed_stage_may_outlast_the_database_budget(  # type: ignore[no-untyped-def]
    corpus, settings
) -> None:
    """The two budgets add, so a slow provider is not charged to the SQL layer.

    The live measurement behind this: a 32,945 ms query embedding against a
    30-second database budget. Here the same shape is scaled down, with a
    provider slower than the database budget alone would allow.
    """
    from sci_rag.retrieve.retriever import stage_budget_s

    budgeted = Settings(_env_file=None, deep_stage_timeout_s=30.0, provider_call_timeout_s=60.0)
    assert stage_budget_s("vector", budgeted.deep_stage_timeout_s, budgeted) == 90.0
    assert stage_budget_s("keyword", budgeted.deep_stage_timeout_s, budgeted) == 30.0
