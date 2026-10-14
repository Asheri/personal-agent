"""Rerank stage wired through the retriever: traces, ordering, degradation.

Offline like the rest of the integration suite: local-hash embeddings and
mock LLMs. These tests prove the orchestration contract (the rerank stage
runs post-fusion, traces honestly, and can never take a request down),
not reranking quality.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from sci_rag.db import get_session_factory
from sci_rag.domain import load_domain
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import MockLLM
from sci_rag.retrieve import Retriever

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"


@pytest.fixture()
def corpus_entries(tmp_path: Path) -> list[CorpusEntry]:
    rice = tmp_path / "rice.md"
    rice.write_text(
        "Rice straw availability in Colusa County is near 310,000 tons per year. "
        "Straw is baled after harvest and stored at field edge."
    )
    almond = tmp_path / "almond.txt"
    almond.write_text(
        "Almond orchard prunings are chipped in winter. "
        "Yields are close to 1.2 tons per acre in mature orchards."
    )
    return [
        CorpusEntry(path=rice, title="Rice Straw Report", license_class="public", source="tests"),
        CorpusEntry(path=almond, title="Almond Prunings", license_class="public", source="tests"),
    ]


def scores_response(pairs: list[tuple[int, float]]) -> str:
    return json.dumps({"scores": [{"index": i, "score": s} for i, s in pairs]})


def make_retriever(local_embedder, llm) -> Retriever:  # type: ignore[no-untyped-def]
    return Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=llm,
        session_factory=get_session_factory(),
    )


async def test_rerank_disabled_by_default_traces_disabled(
    clean_tables, corpus_entries, local_embedder
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    llm = MockLLM()
    retriever = make_retriever(local_embedder, llm)
    result = await retriever.retrieve("rice straw tons", profile="interactive")
    trace = result.trace_for("rerank")
    assert trace is not None and trace.status == "disabled"
    assert llm.calls == []


async def test_include_rerank_reorders_and_traces_success(
    clean_tables, corpus_entries, local_embedder
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    # Score every candidate; give the LAST fused candidate the top score so
    # a reorder is observable.
    reorder_llm = MockLLM(
        responses=[json.dumps({"scores": [{"index": i, "score": float(i)} for i in range(50)]})]
    )
    retriever = make_retriever(local_embedder, reorder_llm)
    baseline = await retriever.retrieve(
        "rice straw tons", profile="interactive", include_rerank=False
    )
    assert len(baseline.items) >= 2
    result = await retriever.retrieve("rice straw tons", profile="interactive", include_rerank=True)
    trace = result.trace_for("rerank")
    assert trace is not None and trace.status == "success"
    assert trace.candidate_count >= 2
    assert len(result.items) == len(baseline.items)
    # Highest index got the top score, so the fused order must be reversed.
    assert [i.id for i in result.items] == [i.id for i in reversed(baseline.items)]


async def test_rerank_failure_falls_back_to_fused_order(
    clean_tables, corpus_entries, local_embedder
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    bad_llm = MockLLM(default_response="not json at all")
    retriever = make_retriever(local_embedder, bad_llm)
    baseline = await retriever.retrieve(
        "rice straw tons", profile="interactive", include_rerank=False
    )
    result = await retriever.retrieve("rice straw tons", profile="interactive", include_rerank=True)
    trace = result.trace_for("rerank")
    assert trace is not None and trace.status == "error"
    assert [i.id for i in result.items] == [i.id for i in baseline.items]


async def test_rerank_timeout_falls_back_to_fused_order(
    clean_tables, corpus_entries, local_embedder, monkeypatch
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)

    class SlowLLM(MockLLM):
        async def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            await asyncio.sleep(5)
            return "{}"

    retriever = make_retriever(local_embedder, SlowLLM())
    retriever.domain.config.retrieval.reranker.timeout_s = 0.05
    baseline = await retriever.retrieve(
        "rice straw tons", profile="interactive", include_rerank=False
    )
    result = await retriever.retrieve("rice straw tons", profile="interactive", include_rerank=True)
    trace = result.trace_for("rerank")
    assert trace is not None and trace.status == "timeout"
    assert [i.id for i in result.items] == [i.id for i in baseline.items]
