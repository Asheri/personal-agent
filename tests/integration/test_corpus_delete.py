"""Delete a document, and prove its content unreachable through EVERY layer.

The regression contract of `sci-rag corpus delete` + `sci-rag graph gc`:
after deleting a document, no retrieval path (vector, keyword, graph
traversal, community summaries) can surface its content, the graph keeps
no dangling evidence pointers, and untouched documents remain fully
retrievable. The graph fixture is built directly (no LLM) so the test
stays offline and deterministic.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from sci_rag.corpus import delete_documents, graph_gc
from sci_rag.db import (
    Chunk,
    Document,
    DocumentCitation,
    KgCommunity,
    KgEntity,
    KgRelationship,
    get_session_factory,
)
from sci_rag.domain import load_domain
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import LLMClient
from sci_rag.retrieve import Retriever

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"

RICE_PHRASE = "310,000 tons of rice straw"
ALMOND_PHRASE = "almond prunings are chipped"


class EntityMockLLM(LLMClient):
    """Always claims the query mentions both fixture entities."""

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        return '{"entities": ["Rice Straw", "Almond Prunings"]}'

    async def _stream_impl(self) -> AsyncIterator[str]:
        yield ""

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream_impl()


@pytest.fixture()
def corpus_entries(tmp_path: Path) -> list[CorpusEntry]:
    rice = tmp_path / "rice.md"
    rice.write_text(
        f"The Colusa Basin generated {RICE_PHRASE} in 2023. "
        "Straw is baled after harvest and stored at field edge."
    )
    almond = tmp_path / "almond.md"
    almond.write_text(f"In winter, {ALMOND_PHRASE} at roadside. Yields near 1.2 tons per acre.")
    return [
        CorpusEntry(path=rice, title="Rice Straw Report", license_class="public", source="tests"),
        CorpusEntry(path=almond, title="Almond Prunings", license_class="public", source="tests"),
    ]


async def _build_graph_fixture() -> dict[str, str]:
    """Entities/relationships/communities wired to the ingested docs."""
    factory = get_session_factory()
    async with factory() as session:
        docs = {
            title: doc_id
            for doc_id, title in (await session.execute(select(Document.id, Document.title))).all()
        }
        chunks: dict[str, list[str]] = {}
        for doc_title, doc_id in docs.items():
            ids = (
                (await session.execute(select(Chunk.id).where(Chunk.document_id == doc_id)))
                .scalars()
                .all()
            )
            chunks[doc_title] = list(ids)

        rice_doc = docs["Rice Straw Report"]
        almond_doc = docs["Almond Prunings"]
        rice_only = KgEntity(
            name="Rice Straw",
            entity_type="Feedstock",
            description="Straw from rice harvest.",
            document_ids=[rice_doc],
            chunk_ids=chunks["Rice Straw Report"],
        )
        both_docs = KgEntity(
            name="Almond Prunings",
            entity_type="Feedstock",
            description="Prunings from almond orchards.",
            document_ids=[almond_doc, rice_doc],
            chunk_ids=chunks["Almond Prunings"] + chunks["Rice Straw Report"][:1],
        )
        session.add_all([rice_only, both_docs])
        await session.flush()
        relationship = KgRelationship(
            source_entity_id=rice_only.id,
            target_entity_id=both_docs.id,
            relation_type="COMPETES_WITH",
            evidence="Both residues compete for boiler capacity.",
            document_id=rice_doc,
            chunk_id=chunks["Rice Straw Report"][0],
        )
        session.add(relationship)
        community = KgCommunity(
            title="Residue supply",
            member_entity_ids=[rice_only.id, both_docs.id],
            summary=f"Covers {RICE_PHRASE} and almond pruning logistics.",
            summary_embedding=None,
        )
        session.add(community)
        citation = DocumentCitation(
            citing_document_id=almond_doc,
            cited_document_id=rice_doc,
            cited_doi="10.1000/rice-report",
        )
        session.add(citation)
        await session.commit()
        return {
            "rice_doc": rice_doc,
            "almond_doc": almond_doc,
            "rice_entity": rice_only.id,
            "both_entity": both_docs.id,
            "relationship": relationship.id,
            "community": community.id,
            "citation": citation.id,
        }


def make_retriever(local_embedder) -> Retriever:  # type: ignore[no-untyped-def]
    return Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=EntityMockLLM(),
        session_factory=get_session_factory(),
    )


async def test_delete_cascades_scrubs_and_unreaches_every_layer(
    clean_tables, corpus_entries, local_embedder
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    ids = await _build_graph_fixture()
    outcome = await delete_documents(get_session_factory(), [ids["rice_doc"]])
    assert outcome.documents_deleted == 1
    assert outcome.relationships_deleted == 1
    assert outcome.communities_deleted == 1
    assert outcome.citations_deleted == 1

    factory = get_session_factory()
    async with factory() as session:
        # Chunks cascaded with the document.
        rice_chunks = await session.scalar(
            select(func.count(Chunk.id)).where(Chunk.document_id == ids["rice_doc"])
        )
        assert rice_chunks == 0
        # Arrays scrubbed on the surviving multi-doc entity.
        both = await session.get(KgEntity, ids["both_entity"])
        assert both is not None
        assert ids["rice_doc"] not in both.document_ids
        # The rice-only entity is now evidence-less (arrays scrubbed empty).
        rice_entity = await session.get(KgEntity, ids["rice_entity"])
        assert rice_entity is not None
        assert rice_entity.document_ids == [] and rice_entity.chunk_ids == []
        # The community that aggregated the deleted evidence is gone.
        assert await session.get(KgCommunity, ids["community"]) is None
        assert await session.get(DocumentCitation, ids["citation"]) is None

    # GC removes the evidence-less entity.
    gc_outcome = await graph_gc(get_session_factory(), dry_run=False)
    assert gc_outcome.entities_deleted == 1
    async with factory() as session:
        assert await session.get(KgEntity, ids["rice_entity"]) is None
        assert await session.get(KgEntity, ids["both_entity"]) is not None

    # No layer can reach the deleted content anymore.
    retriever = make_retriever(local_embedder)
    result = await retriever.retrieve(
        "how many tons of rice straw",
        profile="deep",
        include_hyde=False,
        graph_include_citations=True,
    )
    all_content = " ".join(item.content for item in result.items)
    assert RICE_PHRASE not in all_content
    # The untouched document is still fully retrievable.
    almond = await retriever.retrieve("almond prunings chipped", profile="deep", include_hyde=False)
    assert any(ALMOND_PHRASE.lower() in item.content.lower() for item in almond.items)


async def test_gc_dry_run_mutates_nothing(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    ids = await _build_graph_fixture()
    await delete_documents(get_session_factory(), [ids["rice_doc"]])
    gc_outcome = await graph_gc(get_session_factory(), dry_run=True)
    assert gc_outcome.entities_deleted == 1  # reported, not executed
    factory = get_session_factory()
    async with factory() as session:
        assert await session.get(KgEntity, ids["rice_entity"]) is not None


async def test_delete_unknown_id_reports_zero(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    outcome = await delete_documents(get_session_factory(), ["doesnotexist"])
    assert outcome.documents_deleted == 0
    factory = get_session_factory()
    async with factory() as session:
        remaining = await session.scalar(select(func.count(Document.id)))
    assert remaining == 2


async def test_gc_prunes_dangling_relationship_refs(clean_tables, corpus_entries, local_embedder):  # type: ignore[no-untyped-def]
    """A relationship whose evidence chunk vanished outside the delete path
    (defense in depth) is removed by gc."""
    await ingest_entries(corpus_entries, embedder=local_embedder)
    ids = await _build_graph_fixture()
    factory = get_session_factory()
    async with factory() as session:
        relationship = await session.get(KgRelationship, ids["relationship"])
        assert relationship is not None
        relationship.chunk_id = "vanishedchunkid"
        relationship.document_id = None
        await session.commit()
    gc_outcome = await graph_gc(get_session_factory(), dry_run=False)
    assert gc_outcome.relationships_deleted >= 1
    async with factory() as session:
        assert await session.get(KgRelationship, ids["relationship"]) is None
