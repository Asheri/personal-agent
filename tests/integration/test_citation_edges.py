"""Corpus-local citation construction, inspection, and scoped traversal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select

from sci_rag.citations import build_citation_edges
from sci_rag.db import Chunk, Document, DocumentCitation, KgEntity, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.llm import LLMClient
from sci_rag.retrieve.stages.graph import graph_stage
from sci_rag.retrieve.types import RetrievalScope
from sci_rag.server import RagService

pytestmark = pytest.mark.integration
DOMAIN_DIR = Path(__file__).parents[2] / "domain"


class CitationQueryLLM(LLMClient):
    async def generate(  # type: ignore[no-untyped-def]
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):
        return '{"entities": ["Seed concept"]}'

    async def _stream_impl(self) -> AsyncIterator[str]:
        yield ""

    def stream(  # type: ignore[no-untyped-def]
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048
    ):
        return self._stream_impl()


def _document(
    document_id: str,
    title: str,
    doi: str,
    *,
    license_class: str = "public",
    references: list[str] | None = None,
) -> Document:
    extra = {}
    if references is not None:
        extra["crossref"] = {"reference_dois": references}
    return Document(
        id=document_id,
        title=title,
        source="test",
        content_hash=document_id * 2,
        doi=doi,
        license_class=license_class,
        extra=extra,
    )


async def test_builder_retains_unmatched_references_and_resolves_them_later(
    clean_tables,
) -> None:  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    citing_id = "a" * 32
    cited_id = "b" * 32
    later_id = "c" * 32
    async with factory() as session:
        session.add_all(
            [
                _document(
                    citing_id,
                    "Citing work",
                    "10.1000/citing",
                    references=[
                        "10.1000/cited",
                        "https://doi.org/10.1000/CITED",
                        "10.1000/later",
                        "10.1000/citing",
                    ],
                ),
                _document(cited_id, "Cited work", "10.1000/cited"),
            ]
        )
        await session.commit()

    preview = await build_citation_edges(factory)
    assert (preview.matched, preview.unmatched, preview.self_citations_skipped) == (1, 1, 1)
    assert preview.rows_written == 2 and preview.dry_run is True

    applied = await build_citation_edges(factory, dry_run=False)
    assert applied.rows_written == 2
    async with factory() as session:
        rows = list(
            (await session.execute(select(DocumentCitation).order_by(DocumentCitation.cited_doi)))
            .scalars()
            .all()
        )
    assert [(row.cited_doi, row.cited_document_id) for row in rows] == [
        ("10.1000/cited", cited_id),
        ("10.1000/later", None),
    ]
    assert (await build_citation_edges(factory, dry_run=False)).rows_written == 0

    async with factory() as session:
        session.add(_document(later_id, "Later ingest", "10.1000/later"))
        await session.commit()
    resolved = await build_citation_edges(factory, dry_run=False)
    assert resolved.rows_written == 1 and resolved.unmatched == 0

    service = RagService()
    service.session_factory = factory
    outgoing = await service.get_citations(citing_id)
    incoming = await service.get_citations(cited_id)
    assert [(row["title"], row["resolved"]) for row in outgoing["references"]] == [
        ("Cited work", True),
        ("Later ingest", True),
    ]
    assert [row["title"] for row in incoming["cited_by"]] == ["Citing work"]


async def test_citation_expansion_is_opt_in_and_scoped_before_ranking(
    clean_tables,
) -> None:  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    seed_doc = "1" * 32
    public_doc = "2" * 32
    restricted_doc = "3" * 32
    seed_chunk = "4" * 32
    public_chunk = "5" * 32
    restricted_chunk = "6" * 32
    async with factory() as session:
        session.add_all(
            [
                _document(seed_doc, "Seed", "10.1000/seed"),
                _document(public_doc, "Public citation", "10.1000/public"),
                _document(
                    restricted_doc,
                    "Restricted citation",
                    "10.1000/restricted",
                    license_class="restricted",
                ),
                Chunk(
                    id=seed_chunk,
                    document_id=seed_doc,
                    chunk_index=0,
                    content="Seed concept evidence",
                    token_count=3,
                ),
                Chunk(
                    id=public_chunk,
                    document_id=public_doc,
                    chunk_index=0,
                    content="Public cited evidence",
                    token_count=3,
                ),
                Chunk(
                    id=restricted_chunk,
                    document_id=restricted_doc,
                    chunk_index=0,
                    content="Restricted cited evidence",
                    token_count=3,
                ),
                DocumentCitation(
                    citing_document_id=seed_doc,
                    cited_document_id=public_doc,
                    cited_doi="10.1000/public",
                ),
                DocumentCitation(
                    citing_document_id=seed_doc,
                    cited_document_id=restricted_doc,
                    cited_doi="10.1000/restricted",
                ),
                KgEntity(
                    name="Seed concept",
                    entity_type="Feedstock",
                    document_ids=[seed_doc],
                    chunk_ids=[seed_chunk],
                ),
            ]
        )
        await session.commit()

    common = (factory, CitationQueryLLM(), load_domain(DOMAIN_DIR), "query")
    off = await graph_stage(*common, RetrievalScope(), 20)
    scoped = await graph_stage(
        *common,
        RetrievalScope(license_classes=("public",)),
        20,
        include_citations=True,
    )
    unrestricted = await graph_stage(*common, RetrievalScope(), 20, include_citations=True)

    assert off == [("chunk", seed_chunk)]
    assert set(scoped) == {("chunk", seed_chunk), ("chunk", public_chunk)}
    assert set(unrestricted) == {
        ("chunk", seed_chunk),
        ("chunk", public_chunk),
        ("chunk", restricted_chunk),
    }
