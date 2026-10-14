"""The auto profile end to end: router trace, resolved profile, overrides."""

from __future__ import annotations

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
    doc = tmp_path / "rice.md"
    doc.write_text("Rice straw ash content is near 18 percent with high silica.")
    return [CorpusEntry(path=doc, title="Rice Straw", license_class="public", source="tests")]


async def test_auto_profile_resolves_and_traces(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=MockLLM(),
        session_factory=get_session_factory(),
    )
    result = await retriever.retrieve("what is the ash content of rice straw", profile="auto")
    trace = result.trace_for("router")
    assert trace is not None and trace.status == "success"
    assert result.profile == "interactive"  # short factual lookup
    assert result.items, "retrieval must still return results under auto"


async def test_auto_respects_explicit_overrides(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    llm = MockLLM(default_response='{"entities": []}')
    retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=llm,
        session_factory=get_session_factory(),
    )
    # The router would turn graph OFF for this short lookup; the explicit
    # flag must win over the router's decision.
    result = await retriever.retrieve(
        "what is the ash content of rice straw", profile="auto", include_graph=True
    )
    graph_trace = result.trace_for("graph")
    assert graph_trace is not None and graph_trace.status != "disabled"


async def test_non_auto_profiles_have_no_router_trace(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=MockLLM(),
        session_factory=get_session_factory(),
    )
    result = await retriever.retrieve("anything at all", profile="deep")
    assert result.trace_for("router") is None
