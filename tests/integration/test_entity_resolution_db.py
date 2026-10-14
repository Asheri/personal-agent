from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from sci_rag.db import (
    Chunk,
    Document,
    EntityResolutionAudit,
    KgCommunity,
    KgEntity,
    KgRelationship,
    get_session_factory,
)
from sci_rag.domain import load_domain
from sci_rag.graph.extractor import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionStats,
    _insert_relationships,
    _upsert_entities,
)
from sci_rag.graph.resolve import resolve_entities
from sci_rag.retrieve.stages.graph import graph_stage
from sci_rag.retrieve.types import RetrievalScope

pytestmark = pytest.mark.integration


async def seed_duplicates() -> dict[str, str]:
    async with get_session_factory()() as session:
        document = Document(
            id="d" * 32,
            title="Rice evidence",
            content_hash="f" * 64,
            license_class="public",
        )
        chunk = Chunk(
            id="c" * 32,
            document_id=document.id,
            chunk_index=0,
            content="Paddy straw can be converted.",
            token_count=6,
        )
        winner = KgEntity(
            id="a" * 32,
            name="rice straw",
            entity_type="Feedstock",
            aliases=["paddy straw"],
            document_ids=[document.id],
            chunk_ids=[],
        )
        loser = KgEntity(
            id="b" * 32,
            name="Paddy Straw",
            entity_type="Feedstock",
            aliases=[],
            document_ids=[],
            chunk_ids=[chunk.id],
        )
        neighbor = KgEntity(
            id="e" * 32,
            name="anaerobic digestion",
            entity_type="ConversionProcess",
            aliases=[],
            document_ids=[document.id],
            chunk_ids=[chunk.id],
        )
        relationship = KgRelationship(
            id="r" * 32,
            source_entity_id=loser.id,
            target_entity_id=neighbor.id,
            relation_type="CONVERTED_BY",
            confidence=0.8,
            chunk_id=chunk.id,
            document_id=document.id,
        )
        session.add_all([document, chunk, winner, loser, neighbor, relationship])
        await session.commit()
    return {"winner": winner.id, "loser": loser.id, "chunk": chunk.id, "rel": relationship.id}


async def test_extraction_does_not_reuse_alias_from_different_entity_type(clean_tables) -> None:  # type: ignore[no-untyped-def]
    document_id = "1" * 32
    chunk_id = "2" * 32
    product_id = "3" * 32
    async with get_session_factory()() as session:
        session.add_all(
            [
                Document(
                    id=document_id,
                    title="Char evidence",
                    content_hash="4" * 64,
                    license_class="public",
                ),
                Chunk(
                    id=chunk_id,
                    document_id=document_id,
                    chunk_index=0,
                    content="Char is used as a feedstock.",
                    token_count=6,
                ),
                KgEntity(
                    id=product_id,
                    name="biochar",
                    entity_type="Product",
                    aliases=["char"],
                    document_ids=[],
                    chunk_ids=[],
                ),
            ]
        )
        await session.flush()

        ids = await _upsert_entities(
            session,
            [ExtractedEntity("char", "Feedstock", "incoming material", [1])],
            {1: chunk_id},
            {1: document_id},
            fallback_chunk_ids=[chunk_id],
            fallback_document_ids=[document_id],
            stats=ExtractionStats(),
        )
        await session.commit()

    async with get_session_factory()() as session:
        product = await session.get(KgEntity, product_id)
        feedstock = await session.scalar(select(KgEntity).where(KgEntity.name == "char"))
    assert product is not None and feedstock is not None
    assert product.document_ids == []
    assert feedstock.entity_type == "Feedstock"
    assert ids["char"] == feedstock.id


async def test_exact_name_type_conflict_is_rejected_without_relationship(clean_tables) -> None:  # type: ignore[no-untyped-def]
    document_id = "6" * 32
    chunk_id = "7" * 32
    conflicting_id = "8" * 32
    target_id = "9" * 32
    async with get_session_factory()() as session:
        session.add_all(
            [
                Document(
                    id=document_id,
                    title="Conflicting type evidence",
                    content_hash="a" * 64,
                    license_class="public",
                ),
                Chunk(
                    id=chunk_id,
                    document_id=document_id,
                    chunk_index=0,
                    content="Char produces fuel.",
                    token_count=3,
                ),
                KgEntity(
                    id=conflicting_id,
                    name="char",
                    entity_type="Product",
                    document_ids=[],
                    chunk_ids=[],
                ),
                KgEntity(id=target_id, name="fuel", entity_type="Product"),
            ]
        )
        await session.flush()
        ids = await _upsert_entities(
            session,
            [ExtractedEntity("char", "Feedstock", "incoming material", [1])],
            {1: chunk_id},
            {1: document_id},
            fallback_chunk_ids=[chunk_id],
            fallback_document_ids=[document_id],
            stats=ExtractionStats(),
        )
        await _insert_relationships(
            session,
            [ExtractedRelationship("char", "fuel", "PRODUCES", "produces fuel", 1)],
            {**ids, "fuel": target_id},
            {1: chunk_id},
            {1: document_id},
            ExtractionStats(),
        )
        await session.commit()

    async with get_session_factory()() as session:
        conflicting = await session.get(KgEntity, conflicting_id)
        relationship_count = await session.scalar(select(func.count(KgRelationship.id)))
    assert "char" not in ids
    assert conflicting is not None and conflicting.document_ids == []
    assert relationship_count == 0


async def test_relationship_extraction_preserves_distinct_evidence_surfaces(clean_tables) -> None:  # type: ignore[no-untyped-def]
    source_id = "a" * 32
    target_id = "b" * 32
    document_ids = ["c" * 32, "d" * 32]
    chunk_ids = ["e" * 32, "f" * 32]
    async with get_session_factory()() as session:
        session.add_all(
            [
                Document(
                    id=document_ids[index],
                    title=f"Evidence {index}",
                    content_hash=str(index + 7) * 64,
                    license_class="public" if index == 0 else "restricted",
                )
                for index in range(2)
            ]
            + [
                Chunk(
                    id=chunk_ids[index],
                    document_id=document_ids[index],
                    chunk_index=0,
                    content=f"Evidence {index}.",
                    token_count=2,
                )
                for index in range(2)
            ]
            + [
                KgEntity(id=source_id, name="source", entity_type="Feedstock"),
                KgEntity(id=target_id, name="target", entity_type="Product"),
            ]
        )
        await session.flush()
        relationship = ExtractedRelationship(
            "source", "target", "PRODUCES", "produces target", 1, 0.8
        )
        for document_id, chunk_id in zip(document_ids, chunk_ids, strict=True):
            await _insert_relationships(
                session,
                [relationship],
                {"source": source_id, "target": target_id},
                {1: chunk_id},
                {1: document_id},
                ExtractionStats(),
            )
            await session.flush()
        await session.commit()

    async with get_session_factory()() as session:
        relationships = (await session.execute(select(KgRelationship))).scalars().all()
    assert {relationship.document_id for relationship in relationships} == set(document_ids)


async def test_resolution_merges_evidence_repoints_edges_and_audits(clean_tables) -> None:  # type: ignore[no-untyped-def]
    ids = await seed_duplicates()

    report = await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)

    assert report.merged == 1
    async with get_session_factory()() as session:
        winner = await session.get(KgEntity, ids["winner"])
        loser = await session.get(KgEntity, ids["loser"])
        relationship = await session.get(KgRelationship, ids["rel"])
        audits = (await session.execute(select(EntityResolutionAudit))).scalars().all()
    assert winner is not None and loser is not None and relationship is not None
    assert winner.document_ids == ["d" * 32]
    assert winner.chunk_ids == [ids["chunk"]]
    assert "Paddy Straw" in winner.aliases
    assert loser.canonical_entity_id == winner.id
    assert relationship.source_entity_id == winner.id
    assert len(audits) == 1
    assert audits[0].merged_entity_name == "Paddy Straw"
    assert audits[0].surviving_entity_name == "rice straw"
    assert audits[0].method == "alias"


async def test_resolution_dry_run_makes_no_writes(clean_tables) -> None:  # type: ignore[no-untyped-def]
    await seed_duplicates()

    report = await resolve_entities(get_session_factory(), dry_run=True, no_llm=True)

    async with get_session_factory()() as session:
        canonical_count = await session.scalar(
            select(func.count(KgEntity.id)).where(KgEntity.canonical_entity_id.is_not(None))
        )
        audit_count = await session.scalar(select(func.count(EntityResolutionAudit.id)))
    assert report.planned_merges == 1
    assert report.merged == 0
    assert canonical_count == 0
    assert audit_count == 0


async def test_resolution_deduplicates_affected_edges_and_invalidates_communities(
    clean_tables,
) -> None:  # type: ignore[no-untyped-def]
    ids = await seed_duplicates()
    restricted_document_id = "4" * 32
    restricted_chunk_id = "5" * 32
    async with get_session_factory()() as session:
        session.add_all(
            [
                Document(
                    id=restricted_document_id,
                    title="Restricted conversion evidence",
                    content_hash="6" * 64,
                    license_class="restricted",
                ),
                Chunk(
                    id=restricted_chunk_id,
                    document_id=restricted_document_id,
                    chunk_index=0,
                    content="Restricted conversion claim.",
                    token_count=3,
                ),
                KgRelationship(
                    id="s" * 32,
                    source_entity_id=ids["winner"],
                    target_entity_id="e" * 32,
                    relation_type="CONVERTED_BY",
                    confidence=0.95,
                    document_id=restricted_document_id,
                    chunk_id=restricted_chunk_id,
                ),
                KgRelationship(
                    id="t" * 32,
                    source_entity_id=ids["loser"],
                    target_entity_id="e" * 32,
                    relation_type="CONVERTED_BY",
                    confidence=0.4,
                    document_id=restricted_document_id,
                    chunk_id=restricted_chunk_id,
                ),
                KgCommunity(
                    id="m" * 32,
                    title="Rice conversion",
                    level=0,
                    member_entity_ids=[ids["loser"], "e" * 32],
                    summary="Paddy straw and digestion.",
                ),
            ]
        )
        await session.commit()

    await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)

    async with get_session_factory()() as session:
        relationships = (
            (
                await session.execute(
                    select(KgRelationship).where(
                        KgRelationship.source_entity_id == ids["winner"],
                        KgRelationship.target_entity_id == "e" * 32,
                        KgRelationship.relation_type == "CONVERTED_BY",
                    )
                )
            )
            .scalars()
            .all()
        )
        community_count = await session.scalar(select(func.count(KgCommunity.id)))
    assert len(relationships) == 2
    by_document = {relationship.document_id: relationship for relationship in relationships}
    assert by_document["d" * 32].confidence == 0.8
    assert by_document[restricted_document_id].confidence == 0.95
    assert community_count == 0


class QueryLLM:
    async def generate_json(self, prompt: str, *, max_tokens: int = 512):  # type: ignore[no-untyped-def]
        return {"entities": ["Paddy Straw"]}


class ExactQueryLLM:
    async def generate_json(self, prompt: str, *, max_tokens: int = 512):  # type: ignore[no-untyped-def]
        return {"entities": ["seed process"]}


class NamedQueryLLM:
    def __init__(self, name: str) -> None:
        self.name = name

    async def generate_json(self, prompt: str, *, max_tokens: int = 512):  # type: ignore[no-untyped-def]
        return {"entities": [self.name]}


async def test_traversal_by_merged_name_reaches_survivor_evidence(clean_tables) -> None:  # type: ignore[no-untyped-def]
    ids = await seed_duplicates()
    await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)

    keys = await graph_stage(
        get_session_factory(),
        QueryLLM(),  # type: ignore[arg-type]
        load_domain(Path(__file__).parents[2] / "domain"),
        "What converts paddy straw?",
        RetrievalScope(),
        limit=5,
    )

    assert ("chunk", ids["chunk"]) in keys


async def test_scoped_traversal_does_not_expand_unproven_aliases(clean_tables) -> None:  # type: ignore[no-untyped-def]
    ids = await seed_duplicates()
    async with get_session_factory()() as session:
        winner = await session.get(KgEntity, ids["winner"])
        assert winner is not None
        winner.aliases = [*winner.aliases, "unproven alias"]
        await session.commit()
    await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)

    keys = await graph_stage(
        get_session_factory(),
        NamedQueryLLM("unproven alias"),  # type: ignore[arg-type]
        load_domain(Path(__file__).parents[2] / "domain"),
        "What is the unproven alias?",
        RetrievalScope(license_classes=("public",)),
        limit=5,
    )

    assert keys == []


async def test_scoped_name_provenance_requires_token_boundaries(clean_tables) -> None:  # type: ignore[no-untyped-def]
    document_id = "o" * 32
    chunk_id = "p" * 32
    async with get_session_factory()() as session:
        session.add_all(
            [
                Document(
                    id=document_id,
                    title="Soil evidence",
                    content_hash="4" * 64,
                    license_class="public",
                ),
                Chunk(
                    id=chunk_id,
                    document_id=document_id,
                    chunk_index=0,
                    content="Soil quality is measured here.",
                    token_count=5,
                ),
                KgEntity(
                    name="oil",
                    entity_type="Product",
                    document_ids=[document_id],
                    chunk_ids=[chunk_id],
                ),
            ]
        )
        await session.commit()

    keys = await graph_stage(
        get_session_factory(),
        NamedQueryLLM("oil"),  # type: ignore[arg-type]
        load_domain(Path(__file__).parents[2] / "domain"),
        "What is oil?",
        RetrievalScope(license_classes=("public",)),
        limit=5,
    )

    assert keys == []


async def test_scoped_traversal_requires_name_provenance_after_resolution(clean_tables) -> None:  # type: ignore[no-untyped-def]
    restricted_document_ids = ["g" * 32, "h" * 32]
    restricted_chunk_ids = ["i" * 32, "j" * 32]
    public_document_id = "k" * 32
    public_chunk_id = "l" * 32
    restricted_entity_id = "m" * 32
    public_entity_id = "n" * 32
    async with get_session_factory()() as session:
        session.add_all(
            [
                Document(
                    id=document_id,
                    title=f"Restricted name evidence {index}",
                    content_hash=str(index + 1) * 64,
                    license_class="restricted",
                )
                for index, document_id in enumerate(restricted_document_ids)
            ]
            + [
                Chunk(
                    id=restricted_chunk_ids[index],
                    document_id=document_id,
                    chunk_index=0,
                    content="Restricted term appears here.",
                    token_count=4,
                )
                for index, document_id in enumerate(restricted_document_ids)
            ]
            + [
                Document(
                    id=public_document_id,
                    title="Public name evidence",
                    content_hash="3" * 64,
                    license_class="public",
                ),
                Chunk(
                    id=public_chunk_id,
                    document_id=public_document_id,
                    chunk_index=0,
                    content="Public term appears here.",
                    token_count=4,
                ),
                KgEntity(
                    id=restricted_entity_id,
                    name="restricted term",
                    entity_type="Feedstock",
                    aliases=["public term"],
                    document_ids=restricted_document_ids,
                    chunk_ids=restricted_chunk_ids,
                ),
                KgEntity(
                    id=public_entity_id,
                    name="public term",
                    entity_type="Feedstock",
                    document_ids=[public_document_id],
                    chunk_ids=[public_chunk_id],
                ),
            ]
        )
        await session.commit()

    report = await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)
    assert report.merged == 1
    scope = RetrievalScope(license_classes=("public",))
    restricted_keys = await graph_stage(
        get_session_factory(),
        NamedQueryLLM("restricted term"),  # type: ignore[arg-type]
        load_domain(Path(__file__).parents[2] / "domain"),
        "What is the restricted term?",
        scope,
        limit=5,
    )
    public_keys = await graph_stage(
        get_session_factory(),
        NamedQueryLLM("public term"),  # type: ignore[arg-type]
        load_domain(Path(__file__).parents[2] / "domain"),
        "What is the public term?",
        scope,
        limit=5,
    )

    assert restricted_keys == []
    assert ("chunk", public_chunk_id) in public_keys


async def test_scoped_traversal_rejects_edges_evidenced_only_by_restricted_document(
    clean_tables,
) -> None:  # type: ignore[no-untyped-def]
    public_seed_doc = "1" * 32
    public_neighbor_doc = "2" * 32
    restricted_edge_doc = "3" * 32
    seed_chunk = "4" * 32
    neighbor_chunk = "5" * 32
    edge_chunk = "6" * 32
    seed_entity = "7" * 32
    neighbor_entity = "8" * 32
    async with get_session_factory()() as session:
        session.add_all(
            [
                Document(
                    id=public_seed_doc,
                    title="Public seed",
                    content_hash="1" * 64,
                    license_class="public",
                ),
                Document(
                    id=public_neighbor_doc,
                    title="Public neighbor",
                    content_hash="2" * 64,
                    license_class="public",
                ),
                Document(
                    id=restricted_edge_doc,
                    title="Restricted edge evidence",
                    content_hash="3" * 64,
                    license_class="restricted",
                ),
                Chunk(
                    id=seed_chunk,
                    document_id=public_seed_doc,
                    chunk_index=0,
                    content="Seed process evidence.",
                    token_count=3,
                ),
                Chunk(
                    id=neighbor_chunk,
                    document_id=public_neighbor_doc,
                    chunk_index=0,
                    content="Neighbor evidence.",
                    token_count=2,
                ),
                Chunk(
                    id=edge_chunk,
                    document_id=restricted_edge_doc,
                    chunk_index=0,
                    content="Restricted relationship evidence.",
                    token_count=3,
                ),
                KgEntity(
                    id=seed_entity,
                    name="seed process",
                    entity_type="ConversionProcess",
                    aliases=[],
                    document_ids=[public_seed_doc],
                    chunk_ids=[seed_chunk],
                ),
                KgEntity(
                    id=neighbor_entity,
                    name="neighbor product",
                    entity_type="Product",
                    aliases=[],
                    document_ids=[public_neighbor_doc],
                    chunk_ids=[neighbor_chunk],
                ),
                KgRelationship(
                    source_entity_id=seed_entity,
                    target_entity_id=neighbor_entity,
                    relation_type="PRODUCES",
                    document_id=restricted_edge_doc,
                    chunk_id=edge_chunk,
                ),
            ]
        )
        await session.commit()

    keys = await graph_stage(
        get_session_factory(),
        ExactQueryLLM(),  # type: ignore[arg-type]
        load_domain(Path(__file__).parents[2] / "domain"),
        "What does the seed process produce?",
        RetrievalScope(license_classes=("public",)),
        limit=5,
    )

    assert ("chunk", seed_chunk) in keys
    assert ("chunk", neighbor_chunk) not in keys


async def test_graph_gc_preserves_resolution_tombstones(clean_tables) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.corpus import graph_gc

    ids = await seed_duplicates()
    await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)

    outcome = await graph_gc(get_session_factory(), dry_run=False)

    async with get_session_factory()() as session:
        loser = await session.get(KgEntity, ids["loser"])
    assert loser is not None
    assert loser.canonical_entity_id == ids["winner"]
    assert outcome.entities_deleted == 0


async def test_graph_gc_preserves_empty_survivor_referenced_by_tombstone(clean_tables) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.corpus import graph_gc

    ids = await seed_duplicates()
    await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)
    async with get_session_factory()() as session:
        winner = await session.get(KgEntity, ids["winner"])
        assert winner is not None
        winner.document_ids = []
        winner.chunk_ids = []
        await session.commit()

    outcome = await graph_gc(get_session_factory(), dry_run=False)

    async with get_session_factory()() as session:
        winner = await session.get(KgEntity, ids["winner"])
        loser = await session.get(KgEntity, ids["loser"])
    assert outcome.entities_deleted == 0
    assert winner is not None and loser is not None
    assert loser.canonical_entity_id == winner.id


async def test_resolution_changes_what_a_survivor_query_retrieves(clean_tables) -> None:  # type: ignore[no-untyped-def]
    """One corpus, one query, run either side of the merge.

    Before resolution the survivor "rice straw" holds no chunk evidence and
    no edge: the duplicate "Paddy Straw" holds both. A reader who asks by the
    survivor's name therefore reaches nothing. After the merge the duplicate's
    evidence and its edge belong to the survivor, so the identical query
    reaches the chunk.

    Both halves are asserted because only the pair proves resolution changed
    the retrieval result. A single post-merge assertion cannot tell a working
    resolver apart from a corpus that would have answered anyway.
    """
    ids = await seed_duplicates()
    domain = load_domain(Path(__file__).parents[2] / "domain")

    async def ask_by_survivor_name() -> list:  # type: ignore[type-arg]
        return await graph_stage(
            get_session_factory(),
            NamedQueryLLM("rice straw"),  # type: ignore[arg-type]
            domain,
            "What converts rice straw?",
            RetrievalScope(),
            limit=5,
        )

    before = await ask_by_survivor_name()
    report = await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)
    after = await ask_by_survivor_name()

    assert report.planned_merges == 1
    assert ("chunk", ids["chunk"]) not in before
    assert ("chunk", ids["chunk"]) in after
    assert before != after
