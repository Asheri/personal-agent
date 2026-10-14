"""Corpus lifecycle: delete documents, garbage-collect the graph.

A knowledge base that can only grow rots: retracted papers, superseded
reports, and mistaken ingests all need a clean exit. Deletion here is
transactional and reaches every layer:

* the document row goes, and its chunks cascade with it (FK);
* every graph entity scrubs the deleted document and chunk ids from its
  evidence arrays (an entity with remaining evidence survives with a
  smaller footprint; one with none becomes GC-eligible);
* relationships whose evidence lived in the deleted documents go;
* communities whose member entities carried evidence from the deleted
  documents go too, because their stored summaries were written FROM
  that evidence. Community coverage returns on the next
  ``sci-rag graph communities`` run.

``graph_gc`` is the complementary sweep: entities left with no evidence,
relationships with dangling evidence pointers, and communities whose
member lists no longer resolve. It exists so the graph never quietly
serves ghosts, whatever order deletions happened in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import (
    Chunk,
    Document,
    DocumentCitation,
    KgCommunity,
    KgEntity,
    KgRelationship,
)

log = structlog.get_logger(__name__)


@dataclass
class DeleteOutcome:
    documents_deleted: int = 0
    chunks_deleted: int = 0
    citations_deleted: int = 0
    entities_scrubbed: int = 0
    relationships_deleted: int = 0
    communities_deleted: int = 0


@dataclass
class GcOutcome:
    entities_deleted: int = 0
    relationships_deleted: int = 0
    communities_deleted: int = 0
    communities_pruned: int = 0
    citations_deleted: int = 0

    @property
    def clean(self) -> bool:
        return not (
            self.entities_deleted
            or self.relationships_deleted
            or self.communities_deleted
            or self.communities_pruned
            or self.citations_deleted
        )


async def delete_documents(
    session_factory: async_sessionmaker[AsyncSession], document_ids: list[str]
) -> DeleteOutcome:
    """Delete documents and every graph trace of their evidence, atomically."""
    outcome = DeleteOutcome()
    targets = [d for d in dict.fromkeys(document_ids) if d]
    if not targets:
        return outcome
    async with session_factory() as session:
        found = set(
            (await session.execute(select(Document.id).where(Document.id.in_(targets))))
            .scalars()
            .all()
        )
        if not found:
            return outcome
        doomed_chunks = set(
            (await session.execute(select(Chunk.id).where(Chunk.document_id.in_(found))))
            .scalars()
            .all()
        )
        outcome.citations_deleted = int(
            await session.scalar(
                select(func.count(DocumentCitation.id)).where(
                    (DocumentCitation.citing_document_id.in_(found))
                    | (DocumentCitation.cited_document_id.in_(found))
                )
            )
            or 0
        )

        # Relationships evidenced by the doomed documents or chunks.
        relationship_result = cast(
            "CursorResult[Any]",
            await session.execute(
                delete(KgRelationship).where(
                    (KgRelationship.document_id.in_(found))
                    | (KgRelationship.chunk_id.in_(doomed_chunks) if doomed_chunks else False)
                )
            ),
        )
        outcome.relationships_deleted = relationship_result.rowcount or 0

        # Scrub evidence arrays; remember which entities were touched.
        affected_entity_ids: list[str] = []
        entities = (
            (
                await session.execute(
                    select(KgEntity).where(KgEntity.document_ids.overlap(list(found)))
                )
            )
            .scalars()
            .all()
        )
        for entity in entities:
            entity.document_ids = [d for d in entity.document_ids if d not in found]
            entity.chunk_ids = [c for c in entity.chunk_ids if c not in doomed_chunks]
            affected_entity_ids.append(entity.id)
        outcome.entities_scrubbed = len(entities)

        # Communities that aggregated evidence from those entities: their
        # summaries were written from content that is being deleted.
        if affected_entity_ids:
            community_result = cast(
                "CursorResult[Any]",
                await session.execute(
                    delete(KgCommunity).where(
                        KgCommunity.member_entity_ids.overlap(affected_entity_ids)
                    )
                ),
            )
            outcome.communities_deleted = community_result.rowcount or 0

        document_result = cast(
            "CursorResult[Any]",
            await session.execute(delete(Document).where(Document.id.in_(found))),
        )
        outcome.documents_deleted = document_result.rowcount or 0
        outcome.chunks_deleted = len(doomed_chunks)
        await session.commit()
    log.info(
        "corpus_delete",
        documents=outcome.documents_deleted,
        chunks=outcome.chunks_deleted,
        citations=outcome.citations_deleted,
        entities_scrubbed=outcome.entities_scrubbed,
        relationships=outcome.relationships_deleted,
        communities=outcome.communities_deleted,
    )
    return outcome


async def graph_gc(
    session_factory: async_sessionmaker[AsyncSession], *, dry_run: bool = True
) -> GcOutcome:
    """Sweep the graph for ghosts. Dry run reports; apply deletes.

    Order matters: evidence-less entities first (their relationships
    cascade), then relationships with dangling evidence pointers, then
    communities whose member lists reference vanished entities.
    """
    outcome = GcOutcome()
    async with session_factory() as session:
        lineage_survivors = select(KgEntity.canonical_entity_id).where(
            KgEntity.canonical_entity_id.is_not(None)
        )
        evidence_less = (
            (
                await session.execute(
                    select(KgEntity.id).where(
                        (KgEntity.chunk_ids == [])
                        & (KgEntity.document_ids == [])
                        & KgEntity.canonical_entity_id.is_(None)
                        & KgEntity.id.not_in(lineage_survivors)
                    )
                )
            )
            .scalars()
            .all()
        )
        outcome.entities_deleted = len(evidence_less)

        live_chunk_ids = select(Chunk.id)
        live_document_ids = select(Document.id)
        dangling_relationships = (
            (
                await session.execute(
                    select(KgRelationship.id).where(
                        (
                            KgRelationship.chunk_id.is_not(None)
                            & KgRelationship.chunk_id.not_in(live_chunk_ids)
                        )
                        | (
                            KgRelationship.document_id.is_not(None)
                            & KgRelationship.document_id.not_in(live_document_ids)
                        )
                        | KgRelationship.source_entity_id.in_(evidence_less)
                        | KgRelationship.target_entity_id.in_(evidence_less)
                    )
                )
            )
            .scalars()
            .all()
        )
        outcome.relationships_deleted = len(dangling_relationships)

        dangling_citations = (
            (
                await session.execute(
                    select(DocumentCitation.id).where(
                        DocumentCitation.citing_document_id.not_in(live_document_ids)
                        | (
                            DocumentCitation.cited_document_id.is_not(None)
                            & DocumentCitation.cited_document_id.not_in(live_document_ids)
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        outcome.citations_deleted = len(dangling_citations)

        # Communities referencing entities that no longer exist (including
        # the ones this sweep is about to delete).
        surviving = {
            eid
            for eid in (await session.execute(select(KgEntity.id))).scalars()
            if eid not in set(evidence_less)
        }
        communities = (await session.execute(select(KgCommunity))).scalars().all()
        doomed_communities: list[str] = []
        prunable: list[KgCommunity] = []
        for community in communities:
            members = [m for m in community.member_entity_ids if m in surviving]
            if not members:
                doomed_communities.append(community.id)
            elif len(members) != len(community.member_entity_ids):
                prunable.append(community)
        outcome.communities_deleted = len(doomed_communities)
        outcome.communities_pruned = len(prunable)

        if dry_run:
            return outcome

        if dangling_relationships:
            await session.execute(
                delete(KgRelationship).where(KgRelationship.id.in_(dangling_relationships))
            )
        if dangling_citations:
            await session.execute(
                delete(DocumentCitation).where(DocumentCitation.id.in_(dangling_citations))
            )
        if evidence_less:
            await session.execute(delete(KgEntity).where(KgEntity.id.in_(evidence_less)))
        for community in prunable:
            community.member_entity_ids = [m for m in community.member_entity_ids if m in surviving]
        if doomed_communities:
            await session.execute(delete(KgCommunity).where(KgCommunity.id.in_(doomed_communities)))
        await session.commit()
    log.info(
        "graph_gc",
        dry_run=dry_run,
        entities=outcome.entities_deleted,
        relationships=outcome.relationships_deleted,
        citations=outcome.citations_deleted,
        communities_deleted=outcome.communities_deleted,
        communities_pruned=outcome.communities_pruned,
    )
    return outcome
