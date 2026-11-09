"""One scoped read path for CLI, REST, and Agent tools."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document, DocumentCitation, DocumentEmbedding, Project
from sci_rag.relate.vectors import centered_cosine, mean_vector
from sci_rag.retrieve import RetrievalScope
from sci_rag.retrieve.types import scope_conditions


def _document(row: Document) -> dict[str, Any]:
    from sci_rag.memory_state import freshness

    return {
        "document_id": row.id,
        "title": row.title,
        "source": row.source,
        "license_class": row.license_class,
        "is_current": row.is_current,
        "freshness": freshness(row),
    }


def citation_evidence_condition():  # type: ignore[no-untyped-def]
    literal = (
        select(Chunk.id)
        .where(
            Chunk.id == DocumentCitation.evidence_chunk_id,
            Chunk.document_id == DocumentCitation.citing_document_id,
            func.strpos(func.lower(Chunk.content), func.lower(DocumentCitation.cited_key)) > 0,
        )
        .exists()
    )
    return or_(DocumentCitation.source != "mention", literal)


async def _visible(session: AsyncSession, scope: RetrievalScope) -> dict[str, Document]:
    return {
        d.id: d
        for d in (await session.scalars(select(Document).where(*scope_conditions(scope)))).all()
    }


async def related_documents(
    factory: async_sessionmaker[AsyncSession],
    document_id: str,
    *,
    relation: str = "all",
    scope: RetrievalScope | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    if relation not in {"all", "similar", "citations", "projects"} or not 1 <= limit <= 100:
        raise ValueError("invalid_relation_or_limit")
    scope = scope or RetrievalScope()
    async with factory() as session:
        visible = await _visible(session, scope)
        if document_id not in visible:
            raise LookupError("document_not_found")
        seed = visible[document_id]
        result: dict[str, Any] = {"document": _document(seed)}
        if relation in {"all", "similar"}:
            vectors = list(
                (
                    await session.scalars(
                        select(DocumentEmbedding).where(DocumentEmbedding.document_id.in_(visible))
                    )
                ).all()
            )
            target = next((v for v in vectors if v.document_id == document_id), None)
            if target is None:
                result["similar"], result["similarity_status"] = [], "missing_document_vector"
            else:
                same_version = [
                    v for v in vectors if v.embedding_version == target.embedding_version
                ]
                center = mean_vector([v.embedding for v in same_version])
                ranked = []
                for row in same_version:
                    if row.document_id == document_id:
                        continue
                    score = centered_cosine(target.embedding, row.embedding, center)
                    if score is not None:
                        ranked.append(
                            {
                                **_document(visible[row.document_id]),
                                "score": score,
                                "method": "centered_document_mean_cosine",
                                "embedding_version": target.embedding_version,
                            }
                        )
                ranked.sort(key=lambda row: (-row["score"], row["document_id"]))
                result["similar"], result["similarity_status"] = ranked[:limit], "ready"
        if relation in {"all", "projects"}:
            project = await session.get(Project, seed.project_id) if seed.project_id else None
            result["project"] = (
                {"id": project.id, "name": project.name, "source": seed.project_source}
                if project
                else None
            )
            peers = sorted(
                [
                    d
                    for d in visible.values()
                    if seed.project_id and d.project_id == seed.project_id and d.id != document_id
                ],
                key=lambda d: d.id,
            )
            result["projects"] = [
                {**_document(d), "method": "shared_project", "project_source": d.project_source}
                for d in peers[:limit]
            ]
        if relation in {"all", "citations"}:
            rows = list(
                (
                    await session.scalars(
                        select(DocumentCitation)
                        .where(
                            (DocumentCitation.citing_document_id == document_id)
                            | (DocumentCitation.cited_document_id == document_id),
                            DocumentCitation.citing_document_id.in_(visible),
                            or_(
                                DocumentCitation.cited_document_id.is_(None),
                                DocumentCitation.cited_document_id.in_(visible),
                            ),
                            citation_evidence_condition(),
                        )
                        .order_by(DocumentCitation.id)
                    )
                ).all()
            )
            chunks = {
                c.id: c
                for c in (
                    await session.scalars(select(Chunk).where(Chunk.document_id.in_(visible)))
                ).all()
            }
            outgoing: list[dict[str, Any]] = []
            incoming: list[dict[str, Any]] = []
            for edge in rows:
                if edge.citing_document_id not in visible or (
                    edge.cited_document_id and edge.cited_document_id not in visible
                ):
                    continue
                evidence = chunks.get(edge.evidence_chunk_id or "")
                if edge.source == "mention" and (
                    evidence is None
                    or evidence.document_id != edge.citing_document_id
                    or not edge.cited_key
                    or edge.cited_key.casefold() not in evidence.content.casefold()
                ):
                    continue
                cited_target = visible.get(edge.cited_document_id or "")
                item = {
                    "citing_document_id": edge.citing_document_id,
                    "cited_document_id": edge.cited_document_id,
                    "title": (cited_target.title if cited_target else None)
                    if edge.citing_document_id == document_id
                    else visible[edge.citing_document_id].title,
                    "citing_title": visible[edge.citing_document_id].title,
                    "cited_title": cited_target.title if cited_target else None,
                    "doi": edge.cited_doi,
                    "source": edge.source,
                    "resolved": cited_target is not None,
                    "key": edge.cited_key,
                    "evidence_chunk_id": edge.evidence_chunk_id,
                    "evidence": edge.cited_key if evidence else None,
                    "confidence": edge.confidence,
                }
                (outgoing if edge.citing_document_id == document_id else incoming).append(item)
            result["citations"] = {"references": outgoing[:limit], "cited_by": incoming[:limit]}
        return result


async def document_versions(
    factory: async_sessionmaker[AsyncSession],
    document_id: str,
    *,
    scope: RetrievalScope | None = None,
) -> dict[str, Any]:
    # Calling this history-specific operation explicitly requests retained revisions.
    scope = replace(scope or RetrievalScope(), include_superseded=True)
    async with factory() as session:
        visible = await _visible(session, scope)
        if document_id not in visible:
            raise LookupError("document_not_found")
        seed = visible[document_id]
        versions = sorted(
            [d for d in visible.values() if d.identity_key == seed.identity_key],
            key=lambda d: d.version_seq,
        )
        ids = {d.id for d in versions}
        return {
            "document_id": document_id,
            "versions": [
                {
                    **_document(d),
                    "version_seq": d.version_seq,
                    "predecessor_id": d.version_of if d.version_of in ids else None,
                    "method": "retained_source_revision",
                }
                for d in versions
            ],
        }
