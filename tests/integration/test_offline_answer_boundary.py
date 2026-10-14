"""The offline route, end to end, on both sides of the generation boundary.

The unit tests pin the predicate and the wording. This one proves the thing a
reader actually experiences: retrieval works, the layers that need a model say
so instead of failing, and the answer command refuses with advice that names
generation. It runs against the real retriever and a real database, because
the trace statuses are produced by the orchestrator rather than scripted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_rag.answer import AnswerEngine
from sci_rag.config import Settings
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.retrieve import Retriever

pytestmark = pytest.mark.integration


def _offline_settings(settings) -> Settings:  # type: ignore[no-untyped-def]
    """The shipped offline configuration, with this run's database and dimension."""
    return Settings(
        _env_file=None,
        embedding_provider="local-hash",
        embedding_dim=settings.embedding_dim,
        database_url=settings.database_url,
        domain_dir=settings.domain_dir,
    )


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


async def test_offline_deep_retrieval_disables_the_model_only_layers(corpus) -> None:  # type: ignore[no-untyped-def]
    """Graph and HyDE cannot run here, so they say so rather than erroring.

    Both call a model for every query. Running them into the credential
    failure spent the deep stage budget twice and reported `error`, which
    reads as a broken deployment rather than the mode the reader chose.
    """
    offline = _offline_settings(Settings())
    result = await Retriever(settings=offline).retrieve("rice straw availability", profile="deep")

    statuses = {trace.stage: trace.status for trace in result.traces}
    assert statuses["graph"] == "disabled"
    assert statuses["hyde"] == "disabled"
    assert statuses["vector"] == "success"
    assert result.items, "offline retrieval still has to return evidence"


async def test_an_offline_answer_refuses_with_generation_specific_advice(corpus) -> None:  # type: ignore[no-untyped-def]
    """Retrieval succeeds, then the boundary is named for what it is."""
    engine = AnswerEngine(settings=_offline_settings(Settings()))

    events = [
        event async for event in engine.answer_stream("rice straw availability", profile="deep")
    ]

    retrieval = next(event for event in events if event.type == "retrieval_done")
    assert retrieval.data["item_count"] > 0, "the refusal must not be a no-evidence refusal"

    error = next(event for event in events if event.type == "error")
    assert error.data["code"] == "llm_unavailable"
    message = error.data["message"]
    assert "generate" in message
    assert "SCI_RAG_EMBEDDING_PROVIDER=local-hash" not in message
    assert not [event for event in events if event.type == "delta"]
