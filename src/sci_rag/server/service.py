"""One service facade behind both front doors.

The REST routers and the MCP tools call the same :class:`RagService`
instance, so the two surfaces can never drift apart: same retrieval, same
scoping, same citations, same stats.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import aliased

import sci_rag
from sci_rag.answer import AnswerEngine, AnswerEvent
from sci_rag.config import Settings, get_settings
from sci_rag.db.engine import get_session_factory
from sci_rag.db.models import (
    Chunk,
    Document,
    DocumentCitation,
    KgCommunity,
    KgEntity,
    KgRelationship,
)
from sci_rag.licensing import EXTERNAL_SAFE_CLASSES
from sci_rag.retrieve import RetrievalResult, RetrievalScope, Retriever
from sci_rag.retrieve.types import (
    entity_scope_condition,
    relationship_scope_condition,
    scope_conditions,
)
from sci_rag.server.errors import ApiError


class RagService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        retriever: Retriever | None = None,
        answer_engine: AnswerEngine | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = retriever or Retriever(settings=self.settings)
        self.engine = answer_engine or AnswerEngine(
            settings=self.settings, retriever=self.retriever
        )
        self.session_factory = self.retriever.session_factory or get_session_factory()
        self.domain = self.retriever.domain

    @staticmethod
    def scope_from(
        license_classes: list[str] | None = None,
        sources: list[str] | None = None,
        *,
        year_min: int | None = None,
        year_max: int | None = None,
        authors: list[str] | None = None,
        journals: list[str] | None = None,
        exclude_dois: list[str] | None = None,
        exclude_retracted: bool = False,
        date_min: date | None = None,
        date_max: date | None = None,
        projects: list[str] | None = None,
        tags: list[str] | None = None,
        auto_tags: list[str] | None = None,
        entity_names: list[str] | None = None,
    ) -> RetrievalScope | None:
        """Build a scope, or None when the caller restricted nothing.

        Returning None rather than an empty scope keeps the community
        layer eligible for unfiltered requests: the retriever treats an
        unrestricted scope and no scope identically, but a caller reading
        traces should not see a scope object appear out of nowhere.
        """
        if not any(
            (
                license_classes is not None,
                sources is not None,
                year_min is not None,
                year_max is not None,
                authors,
                journals,
                exclude_dois,
                exclude_retracted,
                date_min is not None,
                date_max is not None,
                projects,
                tags,
                auto_tags,
                entity_names,
            )
        ):
            return None
        return RetrievalScope(
            license_classes=tuple(license_classes) if license_classes is not None else None,
            sources=tuple(sources) if sources is not None else None,
            year_min=year_min,
            year_max=year_max,
            authors=tuple(authors or ()),
            journals=tuple(journals or ()),
            exclude_dois=tuple(exclude_dois or ()),
            exclude_retracted=exclude_retracted,
            date_min=date_min,
            date_max=date_max,
            projects=tuple(projects or ()),
            tags=tuple(tags or ()),
            auto_tags=tuple(auto_tags or ()),
            entity_names=tuple(entity_names or ()),
        )

    async def retrieve(
        self,
        query: str,
        *,
        profile: str = "interactive",
        top_k: int = 8,
        license_classes: list[str] | None = None,
        sources: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        authors: list[str] | None = None,
        journals: list[str] | None = None,
        exclude_dois: list[str] | None = None,
        include_graph: bool | None = None,
        include_community: bool | None = None,
        include_hyde: bool | None = None,
        include_rerank: bool | None = None,
        date_min: date | None = None,
        date_max: date | None = None,
        projects: list[str] | None = None,
        tags: list[str] | None = None,
        auto_tags: list[str] | None = None,
        entity_names: list[str] | None = None,
    ) -> RetrievalResult:
        return await self.retriever.retrieve(
            query,
            profile=profile,
            limit=top_k,
            scope=self.scope_from(
                license_classes,
                sources,
                year_min=year_min,
                year_max=year_max,
                authors=authors,
                journals=journals,
                exclude_dois=exclude_dois,
                date_min=date_min,
                date_max=date_max,
                projects=projects,
                tags=tags,
                auto_tags=auto_tags,
                entity_names=entity_names,
            ),
            include_graph=include_graph,
            include_community=include_community,
            include_hyde=include_hyde,
            include_rerank=include_rerank,
        )

    def answer_stream(
        self,
        query: str,
        *,
        profile: str = "deep",
        top_k: int = 8,
        max_tokens: int = 2048,
        license_classes: list[str] | None = None,
        sources: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        authors: list[str] | None = None,
        journals: list[str] | None = None,
        exclude_dois: list[str] | None = None,
        api_key_override: str | None = None,
        include_compression: bool | None = None,
        date_min: date | None = None,
        date_max: date | None = None,
        projects: list[str] | None = None,
        tags: list[str] | None = None,
        auto_tags: list[str] | None = None,
        entity_names: list[str] | None = None,
    ) -> AsyncIterator[AnswerEvent]:
        return self.engine.answer_stream(
            query,
            profile=profile,
            limit=top_k,
            max_tokens=max_tokens,
            scope=self.scope_from(
                license_classes,
                sources,
                year_min=year_min,
                year_max=year_max,
                authors=authors,
                journals=journals,
                exclude_dois=exclude_dois,
                exclude_retracted=True,
                date_min=date_min,
                date_max=date_max,
                projects=projects,
                tags=tags,
                auto_tags=auto_tags,
                entity_names=entity_names,
            ),
            api_key_override=api_key_override,
            include_compression=include_compression,
        )

    @staticmethod
    def validated_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
        from pydantic import ValidationError

        from sci_rag.server.schemas import BrowseFilters

        try:
            return BrowseFilters.model_validate(filters or {}).model_dump(
                exclude_none=True, exclude_unset=True
            )
        except (ValidationError, TypeError, ValueError):
            raise ApiError(422, "invalid_browse_filter", "Invalid corpus filters") from None

    async def browse_corpus(
        self,
        *,
        dimension: str = "documents",
        by: str | None = None,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        from pydantic import ValidationError

        from sci_rag.browse import DIMENSIONS, browse_documents, facet_counts

        try:
            values = self.validated_filters(filters)
            scope = self.scope_from(**values)
            if dimension == "facets" or (dimension in {d.name for d in DIMENSIONS} and by is None):
                result = await facet_counts(self.session_factory, scope)
                return (
                    result
                    if dimension == "facets"
                    else dict(
                        dimension=dimension,
                        total=result["total"],
                        buckets=result["dimensions"][dimension],
                    )
                )
            if dimension != "documents" and dimension not in {d.name for d in DIMENSIONS}:
                raise ValueError("invalid_dimension")
            return await browse_documents(
                self.session_factory,
                scope,
                page=page,
                page_size=page_size,
                dimension=dimension,
                by=by,
            )
        except LookupError:
            raise ApiError(404, "project_not_found", "No visible project with that id") from None
        except (ValidationError, ValueError, TypeError):
            raise ApiError(
                422, "invalid_browse_filter", "Invalid browse filter or pagination"
            ) from None

    async def list_projects(self, *, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        from sci_rag.browse import list_projects

        scope = self.scope_from(**self.validated_filters(filters))
        return await list_projects(self.session_factory, scope)

    async def topic_overview(self, *, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        from sci_rag.browse import topic_overview

        return await topic_overview(
            self.session_factory, self.scope_from(**self.validated_filters(filters))
        )

    async def list_documents(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        source: str | None = None,
        license_class: str | None = None,
    ) -> tuple[list[Document], int]:
        conditions: list[ColumnElement[bool]] = scope_conditions(RetrievalScope())
        if search:
            conditions.append(Document.title.ilike(f"%{search}%"))
        if source:
            conditions.append(Document.source == source)
        if license_class:
            conditions.append(Document.license_class == license_class)
        async with self.session_factory() as session:
            total = await session.scalar(select(func.count(Document.id)).where(*conditions))
            rows = (
                (
                    await session.execute(
                        select(Document)
                        .where(*conditions)
                        .order_by(Document.ingested_at.desc(), Document.id)
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows), int(total or 0)

    async def get_document(
        self,
        document_id: str,
        *,
        preview_chunks: int = 8,
        preview_chars: int = 240,
        include_superseded: bool = False,
        scope: RetrievalScope | None = None,
    ) -> tuple[Document, list[Chunk]]:
        async with self.session_factory() as session:
            from dataclasses import replace

            visible = replace(scope or RetrievalScope(), include_superseded=include_superseded)
            document = await session.scalar(
                select(Document).where(Document.id == document_id, *scope_conditions(visible))
            )
            if document is None or (document.is_current is False and not include_superseded):
                raise ApiError(404, "document_not_found", "No such document", document_id)
            chunks = (
                (
                    await session.execute(
                        select(Chunk)
                        .where(Chunk.document_id == document_id)
                        .order_by(Chunk.chunk_index)
                        .limit(preview_chunks)
                    )
                )
                .scalars()
                .all()
            )
        return document, list(chunks)

    async def get_related_documents(
        self,
        document_id: str,
        *,
        relation: str = "all",
        scope: RetrievalScope | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        from sci_rag.relate.read import related_documents

        try:
            return await related_documents(
                self.session_factory, document_id, relation=relation, scope=scope, limit=limit
            )
        except LookupError:
            raise ApiError(404, "document_not_found", "No such document") from None
        except ValueError:
            raise ApiError(422, "invalid_relation", "Invalid relation or limit") from None

    async def get_document_versions(
        self, document_id: str, *, scope: RetrievalScope | None = None
    ) -> dict[str, Any]:
        from sci_rag.relate.read import document_versions

        try:
            return await document_versions(self.session_factory, document_id, scope=scope)
        except LookupError:
            raise ApiError(404, "document_not_found", "No such document") from None

    async def get_citations(
        self, document_id: str, *, scope: RetrievalScope | None = None
    ) -> dict[str, Any]:
        """Return resolved and unresolved references in both directions."""
        from sci_rag.relate.read import citation_evidence_condition

        scope = scope or RetrievalScope()
        eligible = select(Document.id).where(*scope_conditions(scope))
        cited = aliased(Document)
        citing = aliased(Document)
        async with self.session_factory() as session:
            document = await session.scalar(
                select(Document).where(Document.id == document_id, *scope_conditions(scope))
            )
            if document is None:
                raise ApiError(404, "document_not_found", "No such document", document_id)
            references = (
                await session.execute(
                    select(DocumentCitation, cited)
                    .outerjoin(
                        cited,
                        (cited.id == DocumentCitation.cited_document_id)
                        & cited.is_current.is_(True),
                    )
                    .where(
                        DocumentCitation.citing_document_id == document_id,
                        or_(
                            DocumentCitation.cited_document_id.is_(None),
                            DocumentCitation.cited_document_id.in_(eligible),
                        ),
                        citation_evidence_condition(),
                    )
                    .order_by(DocumentCitation.cited_doi, DocumentCitation.id)
                )
            ).all()
            cited_by = (
                await session.execute(
                    select(DocumentCitation, citing)
                    .join(citing, citing.id == DocumentCitation.citing_document_id)
                    .where(
                        DocumentCitation.cited_document_id == document_id,
                        citing.is_current.is_(True),
                        citing.id.in_(eligible),
                        citation_evidence_condition(),
                    )
                    .order_by(citing.title, citing.id)
                )
            ).all()
        return {
            "document_id": document.id,
            "title": document.title,
            "doi": document.doi,
            "references": [
                {
                    "document_id": target.id if target else None,
                    "title": target.title if target else None,
                    "doi": row.cited_doi,
                    "source": row.source,
                    "resolved": target is not None,
                }
                for row, target in references
            ],
            "cited_by": [
                {
                    "document_id": source.id,
                    "title": source.title,
                    "doi": source.doi,
                    "source": row.source,
                }
                for row, source in cited_by
            ],
        }

    async def stats(self, *, scope: RetrievalScope | None = None) -> dict[str, Any]:
        scope = scope or RetrievalScope()
        async with self.session_factory() as session:
            counts: dict[str, Any] = {}
            for label, model in (
                ("documents", Document),
                ("chunks", Chunk),
                ("citations", DocumentCitation),
                ("entities", KgEntity),
                ("relationships", KgRelationship),
                ("communities", KgCommunity),
            ):
                if model is KgCommunity and not scope.is_unrestricted():
                    counts[label] = 0
                    continue
                query = select(func.count(model.id))
                if model is Document:
                    query = query.where(*scope_conditions(scope))
                elif model is Chunk:
                    query = query.join(Document).where(*scope_conditions(scope))
                elif model is KgEntity:
                    query = query.where(entity_scope_condition(scope))
                elif model is KgRelationship:
                    query = query.where(relationship_scope_condition(scope))
                elif model is DocumentCitation:
                    query = query.join(
                        Document, Document.id == DocumentCitation.citing_document_id
                    ).where(*scope_conditions(scope))
                counts[label] = int(await session.scalar(query) or 0)
            counts["license_classes"] = {
                license_class: count
                for license_class, count in await session.execute(
                    select(Document.license_class, func.count(Document.id))
                    .where(*scope_conditions(scope))
                    .group_by(Document.license_class)
                )
            }
            counts["sources"] = {
                source: count
                for source, count in await session.execute(
                    select(Document.source, func.count(Document.id))
                    .where(*scope_conditions(scope))
                    .group_by(Document.source)
                )
            }
            counts["embedding_versions"] = {
                version or "none": count
                for version, count in (
                    await session.execute(
                        select(Chunk.embedding_version, func.count(Chunk.id))
                        .join(Document)
                        .where(*scope_conditions(scope))
                        .group_by(Chunk.embedding_version)
                    )
                ).all()
            }
        return counts

    async def corpus_manifest(self, *, base_url: str = "") -> dict[str, Any]:
        stats = await self.stats(scope=RetrievalScope(license_classes=EXTERNAL_SAFE_CLASSES))
        tuning = self.domain.config.retrieval
        return {
            "name": self.domain.name,
            "description": self.domain.config.description,
            "domain": self.domain.name,
            "kit": "sci-rag-kit",
            "kit_version": sci_rag.__version__,
            "stats": {
                "documents": stats["documents"],
                "chunks": stats["chunks"],
                "entities": stats["entities"],
                "communities": stats["communities"],
            },
            "embedding": {
                "model": self.settings.embedding_model,
                "provider": self.settings.embedding_provider,
                "dimension": self.settings.embedding_dim,
            },
            "retrieval": {
                "layers": ["vector", "keyword", "graph", "community", "hyde"],
                "fusion": "weighted_rrf",
                "rrf_k": tuning.rrf_k,
                "weights": tuning.weights,
            },
            "endpoints": {
                "rest": f"{base_url}/v1",
                "mcp": f"{base_url}/mcp",
                "openapi": f"{base_url}/openapi.json",
            },
            "features": {
                "byo_llm_key": True,
                "streaming": True,
                "license_scoping": True,
            },
        }

    async def database_healthy(self) -> bool:
        try:
            async with self.session_factory() as session:
                await session.execute(select(1))
            return True
        except Exception:
            return False
