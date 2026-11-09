"""Scoped browsing and facets share the retrieval predicate and stable sorting."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from sqlalchemy import any_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document, KgCommunity, KgEntity, Project
from sci_rag.retrieve.types import RetrievalScope, entity_scope_condition, scope_conditions


@dataclass(frozen=True)
class FacetDimension:
    name: str
    attribute: str
    array: bool = False


DIMENSIONS = (
    FacetDimension("project", "project_id"),
    FacetDimension("time", "doc_date"),
    FacetDimension("tags", "tags", True),
    FacetDimension("auto_tags", "auto_tags", True),
    FacetDimension("parser", "parser"),
    FacetDimension("topic", "named_topic", True),
)


def document_summary(document: Document) -> dict[str, Any]:
    from sci_rag.memory_state import freshness

    return dict(
        id=document.id,
        title=document.title,
        source=document.source,
        license_class=document.license_class,
        project_id=document.project_id,
        project_source=document.project_source,
        doc_date=document.doc_date.isoformat() if document.doc_date else None,
        doc_date_source=document.doc_date_source,
        tags=document.tags or [],
        auto_tags=document.auto_tags or [],
        parser=document.extra.get("parser"),
        version_seq=document.version_seq,
        ingested_at=document.ingested_at.isoformat(),
        relations=["similar", "citations", "versions", "projects"],
        freshness=freshness(document),
    )


async def browse_documents(
    factory: async_sessionmaker[AsyncSession],
    scope: RetrievalScope | None = None,
    *,
    page: int = 1,
    page_size: int = 20,
    dimension: str | None = None,
    by: str | None = None,
) -> dict[str, Any]:
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError("invalid_pagination")
    scope = scope or RetrievalScope()
    conditions = scope_conditions(scope)
    if by is not None:
        if dimension == "project":
            conditions.append(Document.project_id == by)
        elif dimension in {"tags", "auto_tags"}:
            conditions.append(getattr(Document, dimension).overlap([by]))
        elif dimension == "topic":
            conditions.append(
                select(Chunk.id)
                .join(KgEntity, Chunk.id == any_(KgEntity.chunk_ids))
                .where(
                    Chunk.document_id == Document.id,
                    KgEntity.entity_type == "Topic",
                    KgEntity.name == by,
                )
                .correlate(Document)
                .exists()
            )
        elif dimension == "time":
            start = date.fromisoformat(by + "-01")
            end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
            conditions.append(
                or_(Document.doc_date.is_(None), Document.doc_date.between(start, end))
            )
        else:
            raise ValueError("invalid_dimension_value")
    async with factory() as session:
        if dimension == "project" and by is not None:
            visible = await session.scalar(
                select(Project.id)
                .join(Document, Document.project_id == Project.id)
                .where(Project.id == by, *scope_conditions(replace(scope, projects=())))
                .limit(1)
            )
            if visible is None:
                raise LookupError("project_not_found")
        total = await session.scalar(select(func.count(Document.id)).where(*conditions))
        rows = list(
            (
                await session.scalars(
                    select(Document)
                    .where(*conditions)
                    .order_by(
                        Document.doc_date.desc().nulls_last(),
                        Document.ingested_at.desc(),
                        Document.id,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
    return dict(
        documents=[document_summary(row) for row in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def facet_counts(
    factory: async_sessionmaker[AsyncSession], scope: RetrievalScope | None = None
) -> dict[str, Any]:
    scope = scope or RetrievalScope()
    result: dict[str, list[dict[str, Any]]] = {}
    async with factory() as session:
        total = int(
            await session.scalar(select(func.count(Document.id)).where(*scope_conditions(scope)))
            or 0
        )
        for dimension in DIMENSIONS:
            rows: list[Any]
            if dimension.name == "topic":
                pairs = (
                    select(KgEntity.name.label("value"), Document.id.label("document_id"))
                    .select_from(Document)
                    .join(Chunk, Chunk.document_id == Document.id)
                    .join(KgEntity, Chunk.id == any_(KgEntity.chunk_ids))
                    .where(
                        *scope_conditions(scope),
                        KgEntity.entity_type == "Topic",
                        func.strpos(func.lower(Chunk.content), func.lower(KgEntity.name)) > 0,
                    )
                    .distinct()
                    .subquery()
                )
                query = select(pairs.c.value, func.count()).group_by(pairs.c.value)
                rows = list((await session.execute(query)).all())
                missing = await session.scalar(
                    select(func.count(Document.id)).where(
                        *scope_conditions(scope), Document.id.not_in(select(pairs.c.document_id))
                    )
                )
                if missing:
                    rows.append((None, missing))
            else:
                if dimension.name == "time":
                    value = func.to_char(Document.doc_date, "YYYY-MM")
                elif dimension.name == "parser":
                    value = Document.extra["parser"].astext
                else:
                    value = getattr(Document, dimension.attribute)
                if dimension.array:
                    expanded = (
                        select(Document.id, func.unnest(value).label("value"))
                        .where(*scope_conditions(scope))
                        .subquery()
                    )
                    rows = list(
                        (
                            await session.execute(
                                select(
                                    expanded.c.value, func.count(func.distinct(expanded.c.id))
                                ).group_by(expanded.c.value)
                            )
                        ).all()
                    )
                    missing = await session.scalar(
                        select(func.count(Document.id)).where(
                            *scope_conditions(scope), func.coalesce(func.cardinality(value), 0) == 0
                        )
                    )
                    if missing:
                        rows.append((None, missing))
                else:
                    rows = list(
                        (
                            await session.execute(
                                select(value, func.count(Document.id))
                                .where(*scope_conditions(scope))
                                .group_by(value)
                            )
                        ).all()
                    )
            result[dimension.name] = [
                dict(value=value, count=int(count))
                for value, count in sorted(rows, key=lambda row: (row[0] is None, str(row[0])))
            ]
    return dict(total=total, dimensions=result)


async def list_projects(
    factory: async_sessionmaker[AsyncSession], scope: RetrievalScope | None = None
) -> dict[str, Any]:
    scope = scope or RetrievalScope()
    async with factory() as session:
        rows = (
            await session.execute(
                select(Project.id, Project.name, Project.slug, func.count(Document.id))
                .join(Document, Document.project_id == Project.id)
                .where(*scope_conditions(scope))
                .group_by(Project.id, Project.name, Project.slug)
                .order_by(Project.name, Project.id)
            )
        ).all()
    return {
        "projects": [
            dict(id=key, name=name, slug=slug, documents=int(count))
            for key, name, slug, count in rows
        ]
    }


async def topic_overview(
    factory: async_sessionmaker[AsyncSession], scope: RetrievalScope | None = None
) -> dict[str, Any]:
    scope = scope or RetrievalScope()
    async with factory() as session:
        named = list(
            (
                await session.scalars(
                    select(KgEntity)
                    .where(KgEntity.entity_type == "Topic", entity_scope_condition(scope))
                    .order_by(KgEntity.name, KgEntity.id)
                )
            ).all()
        )
        # Community text aggregates documents. Suppress it for every restriction.
        clusters = (
            list((await session.scalars(select(KgCommunity).order_by(KgCommunity.id))).all())
            if scope.is_unrestricted()
            else []
        )
    return dict(
        named_topics=[dict(id=row.id, name=row.name) for row in named],
        topic_clusters=[dict(id=row.id, summary=row.summary) for row in clusters],
        clusters_status="available" if scope.is_unrestricted() else "disabled_scoped_aggregate",
    )
