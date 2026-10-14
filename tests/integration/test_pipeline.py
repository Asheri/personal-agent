"""End-to-end pipeline tests: files -> chunks -> retrieval -> cited answer.

Everything here runs offline: the deterministic local-hash embedder stands
in for real embeddings and a routing mock stands in for the LLM. These
tests prove the plumbing (ingestion, dedup, scoping, fusion, citations),
not retrieval quality; quality is the evaluation harness's job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from sci_rag.db import Chunk, Document, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import LLMClient
from sci_rag.retrieve import RetrievalScope, Retriever

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"


class RoutingMockLLM(LLMClient):
    """Routes on prompt content so concurrent stages stay deterministic."""

    def __init__(self, *, entities: list[str] | None = None, answer: str = "") -> None:
        self.entities = entities or []
        self.answer = answer

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        if json_mode or '"entities"' in prompt:
            names = ", ".join(f'"{e}"' for e in self.entities)
            return f'{{"entities": [{names}]}}'
        return "Rice straw availability in the valley is measured in tons per year."

    async def _stream_impl(self, text: str) -> AsyncIterator[str]:
        for start in range(0, len(text), 16):
            yield text[start : start + 16]

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream_impl(self.answer)


@pytest.fixture()
def corpus_entries(tmp_path: Path) -> list[CorpusEntry]:
    rice = tmp_path / "rice.md"
    rice.write_text(
        "# Rice Straw Resources in Colusa County\n\n"
        "## Availability\n\n"
        "Colusa County produces large volumes of rice straw after harvest each fall. "
        "Regional estimates put rice straw availability near 310,000 tons per year.\n\n"
        "## Collection\n\n"
        "Rice straw is baled after harvest and stored at field edge before transport.\n"
    )
    almond = tmp_path / "almond.txt"
    almond.write_text(
        "Almond orchard prunings are chipped in the field during winter maintenance. "
        "Typical almond pruning yields are close to 1.2 tons per acre in mature orchards. "
        "Moisture content at collection ranges from 30 to 45 percent."
    )
    secret = tmp_path / "conversion.txt"
    secret.write_text(
        "Proprietary pyrolysis trials converted mixed orchard residues to biochar. "
        "The pyrolysis reactor operated at 500 degrees Celsius with nitrogen purge. "
        "Biochar yields reached 28 percent by mass in the proprietary trials."
    )
    return [
        CorpusEntry(
            path=rice,
            title="Rice Straw Resources in Colusa County",
            authors=["County Ag Dept"],
            year=2023,
            license_class="public",
            source="county_reports",
        ),
        CorpusEntry(
            path=almond,
            title="Almond Pruning Logistics",
            license_class="CC-BY",
            source="extension_notes",
        ),
        CorpusEntry(
            path=secret,
            title="Proprietary Pyrolysis Trials",
            license_class="restricted",
            source="partner_data",
        ),
    ]


@pytest.fixture()
def retriever(local_embedder) -> Retriever:  # type: ignore[no-untyped-def]
    return Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=RoutingMockLLM(),
        session_factory=get_session_factory(),
    )


async def _ingest(entries, local_embedder):  # type: ignore[no-untyped-def]
    return await ingest_entries(entries, embedder=local_embedder)


async def test_ingest_stores_documents_and_chunks(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    report = await _ingest(corpus_entries, local_embedder)
    assert report.ingested == 3 and report.failed == 0

    async with get_session_factory()() as session:
        doc_count = await session.scalar(select(func.count(Document.id)))
        chunk_count = await session.scalar(select(func.count(Chunk.id)))
        no_embedding = await session.scalar(
            select(func.count(Chunk.id)).where(Chunk.embedding.is_(None))
        )
        versions = set(
            (await session.execute(select(Chunk.embedding_version).distinct())).scalars()
        )
    assert doc_count == 3
    assert chunk_count is not None and chunk_count >= 3
    assert no_embedding == 0
    assert versions == {local_embedder.version}


async def test_reingest_is_a_noop(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    first = await _ingest(corpus_entries, local_embedder)
    assert first.ingested == 3
    second = await _ingest(corpus_entries, local_embedder)
    assert second.ingested == 0 and second.skipped == 3


async def test_interactive_retrieval_finds_the_right_document(
    clean_tables, corpus_entries, local_embedder, retriever
):  # type: ignore[no-untyped-def]
    await _ingest(corpus_entries, local_embedder)
    result = await retriever.retrieve(
        "rice straw availability in Colusa County", profile="interactive", limit=5
    )
    assert result.items, "expected at least one retrieved item"
    assert result.items[0].title == "Rice Straw Resources in Colusa County"
    statuses = {t.stage: t.status for t in result.traces}
    assert statuses["vector"] in ("success", "empty")
    assert statuses["keyword"] in ("success", "empty")
    assert statuses["graph"] == "disabled"
    assert statuses["hyde"] == "disabled"


async def test_license_scope_is_enforced_in_every_layer(
    clean_tables, corpus_entries, local_embedder, retriever
):  # type: ignore[no-untyped-def]
    await _ingest(corpus_entries, local_embedder)
    open_only = RetrievalScope(license_classes=("public", "open_commercial"))
    result = await retriever.retrieve(
        "proprietary pyrolysis biochar yields", profile="deep", limit=8, scope=open_only
    )
    assert all(item.license_class in ("public", "open_commercial") for item in result.items)
    assert all(item.title != "Proprietary Pyrolysis Trials" for item in result.items)
    # The community layer must refuse to serve a scoped request.
    community = result.trace_for("community")
    assert community is not None and community.status == "skipped"


async def test_empty_license_scope_denies_everything(
    clean_tables, corpus_entries, local_embedder, retriever
):  # type: ignore[no-untyped-def]
    await _ingest(corpus_entries, local_embedder)
    result = await retriever.retrieve(
        "rice straw", profile="interactive", scope=RetrievalScope(license_classes=())
    )
    assert result.items == []
    assert result.traces and result.traces[0].status == "denied"


async def test_excluded_documents_never_surface(
    clean_tables, corpus_entries, local_embedder, retriever
):  # type: ignore[no-untyped-def]
    await _ingest(corpus_entries, local_embedder)
    async with get_session_factory()() as session:
        rice_id = await session.scalar(
            select(Document.id).where(Document.title.like("Rice Straw%"))
        )
    assert rice_id is not None
    result = await retriever.retrieve(
        "rice straw availability in Colusa County",
        profile="deep",
        scope=RetrievalScope(exclude_document_ids=(rice_id,)),
    )
    assert all(item.document_id != rice_id for item in result.items)


async def test_deep_profile_runs_all_layers(
    clean_tables, corpus_entries, local_embedder, retriever
):  # type: ignore[no-untyped-def]
    await _ingest(corpus_entries, local_embedder)
    result = await retriever.retrieve("almond pruning moisture content", profile="deep")
    statuses = {t.stage: t.status for t in result.traces}
    # Graph has no entities yet (that is the graph build's job), so empty is
    # expected; what matters is that every layer ran and none errored.
    for stage in ("vector", "keyword", "graph", "community", "hyde"):
        assert statuses[stage] in ("success", "empty"), f"{stage}: {statuses[stage]}"


async def test_answer_carries_citations(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    from sci_rag.answer import AnswerEngine

    await _ingest(corpus_entries, local_embedder)
    mock = RoutingMockLLM(
        answer="Colusa County produces about 310,000 tons of rice straw per year [1]."
    )
    engine = AnswerEngine(
        retriever=Retriever(
            domain=load_domain(DOMAIN_DIR),
            embedder=local_embedder,
            llm=mock,
            session_factory=get_session_factory(),
        ),
        llm=mock,
    )
    result = await engine.answer("rice straw availability in Colusa County", profile="interactive")
    assert "310,000 tons" in result.text
    assert result.cited_sources and result.cited_sources[0].index == 1
    assert result.cited_sources[0].title == "Rice Straw Resources in Colusa County"


async def test_answer_refuses_when_nothing_is_in_scope(
    clean_tables, corpus_entries, local_embedder
):  # type: ignore[no-untyped-def]
    from sci_rag.answer import AnswerEngine

    await _ingest(corpus_entries, local_embedder)
    mock = RoutingMockLLM(answer="should never be used")
    engine = AnswerEngine(
        retriever=Retriever(
            domain=load_domain(DOMAIN_DIR),
            embedder=local_embedder,
            llm=mock,
            session_factory=get_session_factory(),
        ),
        llm=mock,
    )
    result = await engine.answer(
        "anything at all",
        profile="interactive",
        scope=RetrievalScope(license_classes=("public",), sources=("nonexistent_source",)),
    )
    assert "cannot give a grounded answer" in result.text
    assert result.sources == []
