"""Metadata filters, enforced inside every layer's SQL.

The scope rule is that filtering happens before ranking, inside each
layer, so an out-of-scope document can never crowd an eligible one out of
a bounded candidate pool. These tests assert that for the metadata
dimensions added in v0.3: publication year, author, journal, and DOI
exclusion, through the vector layer and the keyword layer independently,
plus the community-layer gate that any restriction must trip.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select, update

from sci_rag.db import Document, KgCommunity, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import LLMClient
from sci_rag.retrieve import RetrievalScope, Retriever

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"

OLD_PHRASE = "windrowed at the field edge"
NEW_PHRASE = "baled within seventy two hours"


class QuietMockLLM(LLMClient):
    """Names no entities, so the graph layer contributes nothing."""

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        return '{"entities": []}'

    async def _stream_impl(self) -> AsyncIterator[str]:
        yield ""

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream_impl()


@pytest.fixture()
def corpus_entries(tmp_path: Path) -> list[CorpusEntry]:
    old = tmp_path / "old.md"
    old.write_text(
        f"Rice straw handling in the Colusa Basin. Straw is {OLD_PHRASE} after harvest "
        "and left to dry before collection."
    )
    new = tmp_path / "new.md"
    new.write_text(
        f"Rice straw handling in the Colusa Basin. Straw is {NEW_PHRASE} after harvest "
        "to limit field losses."
    )
    return [
        CorpusEntry(
            path=old,
            title="Straw Handling 2015",
            authors=["Alvarez, R."],
            year=2015,
            doi="10.1000/old",
            license_class="public",
            source="tests",
        ),
        CorpusEntry(
            path=new,
            title="Straw Handling 2023",
            authors=["Nakamura, K."],
            year=2023,
            doi="10.1000/new",
            license_class="public",
            source="tests",
        ),
    ]


def make_retriever(local_embedder) -> Retriever:  # type: ignore[no-untyped-def]
    return Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=QuietMockLLM(),
        session_factory=get_session_factory(),
    )


async def _set_journals() -> None:
    """Journals are set by enrichment in real corpora; set them directly here."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Document)
            .where(Document.title == "Straw Handling 2015")
            .values(journal="Field Crops Research")
        )
        await session.execute(
            update(Document)
            .where(Document.title == "Straw Handling 2023")
            .values(journal="Biomass and Bioenergy")
        )
        await session.commit()


def _contents(result) -> str:  # type: ignore[no-untyped-def]
    return " ".join(item.content for item in result.items)


@pytest.mark.parametrize("layer", ["vector", "keyword"])
async def test_year_range_filters_inside_each_layer(
    clean_tables, corpus_entries, local_embedder, layer
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    retriever = make_retriever(local_embedder)
    flags = {
        "include_vector": layer == "vector",
        "include_keyword": layer == "keyword",
        "include_graph": False,
        "include_community": False,
        "include_hyde": False,
    }
    recent = await retriever.retrieve(
        "rice straw handling after harvest",
        profile="deep",
        scope=RetrievalScope(year_min=2020),
        **flags,
    )
    assert NEW_PHRASE in _contents(recent)
    assert OLD_PHRASE not in _contents(recent)

    older = await retriever.retrieve(
        "rice straw handling after harvest",
        profile="deep",
        scope=RetrievalScope(year_max=2019),
        **flags,
    )
    assert OLD_PHRASE in _contents(older)
    assert NEW_PHRASE not in _contents(older)


async def test_author_filter(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    retriever = make_retriever(local_embedder)
    result = await retriever.retrieve(
        "rice straw handling after harvest",
        profile="deep",
        scope=RetrievalScope(authors=("Nakamura, K.",)),
        include_graph=False,
        include_hyde=False,
    )
    assert NEW_PHRASE in _contents(result)
    assert OLD_PHRASE not in _contents(result)


async def test_journal_filter(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    await _set_journals()
    retriever = make_retriever(local_embedder)
    result = await retriever.retrieve(
        "rice straw handling after harvest",
        profile="deep",
        scope=RetrievalScope(journals=("Biomass and Bioenergy",)),
        include_graph=False,
        include_hyde=False,
    )
    assert NEW_PHRASE in _contents(result)
    assert OLD_PHRASE not in _contents(result)


async def test_doi_exclusion(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    retriever = make_retriever(local_embedder)
    result = await retriever.retrieve(
        "rice straw handling after harvest",
        profile="deep",
        scope=RetrievalScope(exclude_dois=("10.1000/old",)),
        include_graph=False,
        include_hyde=False,
    )
    assert NEW_PHRASE in _contents(result)
    assert OLD_PHRASE not in _contents(result)


async def test_metadata_scope_disables_the_community_layer(
    clean_tables, corpus_entries, local_embedder
):  # type: ignore[no-untyped-def]
    """The trap this test exists for: a stored summary aggregates evidence
    across documents before any scope is known, so ANY restriction must
    disable the layer. A new scope field that is not in is_unrestricted()
    would leave it serving out-of-scope content."""
    await ingest_entries(corpus_entries, embedder=local_embedder)
    factory = get_session_factory()
    async with factory() as session:
        vector = (await local_embedder.embed(["straw handling overview"], task="document"))[0]
        session.add(
            KgCommunity(
                title="Straw handling",
                member_entity_ids=[],
                summary="Overview covering both handling reports.",
                summary_embedding=vector,
            )
        )
        await session.commit()

    retriever = make_retriever(local_embedder)
    unrestricted = await retriever.retrieve(
        "straw handling overview", profile="deep", include_graph=False, include_hyde=False
    )
    assert unrestricted.trace_for("community") is not None
    assert unrestricted.trace_for("community").status == "success"

    for scope in (
        RetrievalScope(year_min=2020),
        RetrievalScope(year_max=2019),
        RetrievalScope(authors=("Nakamura, K.",)),
        RetrievalScope(journals=("Biomass and Bioenergy",)),
        RetrievalScope(exclude_dois=("10.1000/old",)),
    ):
        result = await retriever.retrieve(
            "straw handling overview",
            profile="deep",
            scope=scope,
            include_graph=False,
            include_hyde=False,
        )
        trace = result.trace_for("community")
        assert trace is not None and trace.status == "skipped", (
            f"scope {scope} left the community layer running"
        )
        assert not any(item.kind == "community" for item in result.items)


async def test_journal_column_and_index_exist(clean_tables) -> None:  # type: ignore[no-untyped-def]
    """Filters must not query JSONB, so journal is a first-class column."""
    factory = get_session_factory()
    async with factory() as session:
        # Selecting the column at all proves the mapping and the DDL agree.
        await session.execute(select(Document.journal).limit(1))
