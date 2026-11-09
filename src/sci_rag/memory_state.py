"""Access and freshness metadata never physically remove documents or evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import any_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document, KgEntity
from sci_rag.versions import lock_document_writes


async def record_access(
    factory: async_sessionmaker[AsyncSession],
    document_ids: list[str],
    *,
    now: datetime | None = None,
) -> None:
    if not document_ids:
        return
    async with factory() as session:
        await session.execute(
            update(Document)
            .where(Document.id.in_(set(document_ids)), Document.is_current.is_(True))
            .values(
                access_count=Document.access_count + 1, last_accessed_at=now or datetime.now(UTC)
            )
        )
        await session.commit()


async def maintain_lifecycle(
    factory: async_sessionmaker[AsyncSession], *, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    async with factory() as session:
        await lock_document_writes(session)
        documents = list((await session.scalars(select(Document))).all())
        topics: dict[str, set[str]] = defaultdict(set)
        rows = await session.execute(
            select(Chunk.document_id, KgEntity.name)
            .join(KgEntity, Chunk.id == any_(KgEntity.chunk_ids))
            .where(
                KgEntity.entity_type == "Topic",
                func.strpos(func.lower(Chunk.content), func.lower(KgEntity.name)) > 0,
            )
        )
        for document_id, name in rows:
            topics[document_id].add(name)
        successors = {row.version_of: row for row in documents if row.version_of}
        topic_latest: dict[str, datetime] = {}
        for row in documents:
            if row.is_current:
                for topic in topics[row.id]:
                    topic_latest[topic] = max(
                        topic_latest.get(topic, row.ingested_at), row.ingested_at
                    )
        stale = 0
        for row in documents:
            last = row.last_accessed_at or row.ingested_at
            inactive = last is not None and last < now - timedelta(days=365)
            newer = inactive and any(
                topic_latest.get(topic, row.ingested_at) > row.ingested_at
                for topic in topics[row.id]
            )
            reason = (
                "superseded"
                if not row.is_current
                else "inactive_with_new_topic_material"
                if newer
                else None
            )
            successor = successors.get(row.id)
            state = dict(
                stale=reason is not None,
                reason=reason,
                tier="cold" if reason else "warm",
                valid_from=row.ingested_at.isoformat(),
                valid_to=successor.ingested_at.isoformat() if successor else None,
            )
            row.extra = {**row.extra, "memory_lifecycle": state}
            stale += int(reason is not None)
        await session.commit()
        hot = sorted(
            [row for row in documents if row.is_current and row.access_count > 0],
            key=lambda row: (row.access_count, row.last_accessed_at or row.ingested_at, row.id),
            reverse=True,
        )[:10]
    return dict(documents=len(documents), stale=stale, hot_document_ids=[row.id for row in hot])


def freshness(document: Document) -> dict[str, Any]:
    state = document.extra.get("memory_lifecycle", {})
    expired = not document.is_current or bool(state.get("stale"))
    return dict(
        state="superseded" if not document.is_current else "stale" if expired else "current",
        label="已过期, 可能仍反映历史工作" if expired else "current evidence",
        valid_from=state.get("valid_from")
        or (document.ingested_at.isoformat() if document.ingested_at else None),
        valid_to=state.get("valid_to"),
    )
