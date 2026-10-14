"""The re-embed planner: act on embedding version stamps.

Every chunk (and community summary) records which embedder produced its
vector. This module is what makes that stamp actionable: ``plan_reindex``
reports exactly which rows a model upgrade left behind, ``apply_reindex``
re-embeds them in batches with a commit per batch, so an interrupted run
loses at most one batch of work and is safe to just run again.

Two hard rules:

* Only stale rows are touched. Rows already stamped with the current
  embedder version are never re-embedded, which is what makes reindex
  runs cumulative and cheap.
* A dimension change is REFUSED (:class:`ReindexRefused`). The vector
  columns are created with a fixed dimension; changing it is a schema
  migration plus a full rebuild, and pretending otherwise here would
  fail halfway through with opaque database errors.

The refusal reads the width off the live columns rather than off
``db.models.EMBEDDING_DIM``. Both the embedder and that constant come from
``SCI_RAG_EMBEDDING_DIM``, so comparing them moved both sides of the safety
check at once: changing the setting on a populated database left the guard
seeing no difference at all, which is what F-023 reproduced. The persisted
schema is the only side of this comparison the caller cannot move.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import EMBEDDING_DIM, Chunk, KgCommunity
from sci_rag.embed.provider import EmbeddingProvider

DEFAULT_BATCH_SIZE = 32

# Every vector column a reindex writes to. Both are created by the same
# migration, so in practice they agree, and checking both means a partially
# migrated database is refused rather than half rewritten.
_VECTOR_COLUMNS = (
    (Chunk.__tablename__, "embedding"),
    (KgCommunity.__tablename__, "summary_embedding"),
)

_VECTOR_TYPE = re.compile(r"^vector\((\d+)\)$")

# to_regclass returns NULL for a table that does not exist, so an unmigrated
# database falls out of the join rather than raising.
_COLUMN_TYPE_SQL = text(
    "SELECT format_type(a.atttypid, a.atttypmod) "
    "FROM pg_attribute a "
    "WHERE a.attrelid = to_regclass(:table) AND a.attname = :column AND a.attnum > 0"
)


class ReindexRefused(RuntimeError):
    """The requested reindex is not safe to run."""


@dataclass
class ReindexPlan:
    embedder_version: str
    total_chunks: int
    stale_chunks: int
    stale_communities: int
    # Stale chunk counts by their current (old) version stamp; None keys
    # render as "unstamped".
    chunk_versions: dict[str | None, int] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return self.stale_chunks == 0 and self.stale_communities == 0


@dataclass
class ReindexOutcome:
    chunks_reembedded: int = 0
    communities_reembedded: int = 0
    batches: int = 0


async def live_vector_dimension(session: AsyncSession, table: str, column: str) -> int | None:
    """The width of a persisted pgvector column, or None if it is not there yet.

    Reading the width from the database is the whole point. The alternative,
    ``db.models.EMBEDDING_DIM``, is initialized from the same setting the
    embedder is built from, so it cannot disagree with the embedder no matter
    what the database actually holds.
    """
    rendered = await session.scalar(_COLUMN_TYPE_SQL, {"table": table, "column": column})
    if rendered is None:
        return None
    match = _VECTOR_TYPE.match(rendered)
    return int(match.group(1)) if match else None


def _refusal(embedder: EmbeddingProvider, persisted: int, *, where: str) -> ReindexRefused:
    return ReindexRefused(
        f"embedder {embedder.version} produces {embedder.dim}-dimension vectors but {where} "
        f"is vector({persisted}). A dimension change is a schema migration plus a full "
        "re-ingest, not a reindex. Set SCI_RAG_EMBEDDING_DIM back to "
        f"{persisted}, or migrate the schema first."
    )


async def _check_dimension(session: AsyncSession, embedder: EmbeddingProvider) -> None:
    """Refuse before any embedding call or write when the widths disagree."""
    checked_any = False
    for table, column in _VECTOR_COLUMNS:
        persisted = await live_vector_dimension(session, table, column)
        if persisted is None:
            continue
        checked_any = True
        if embedder.dim != persisted:
            raise _refusal(embedder, persisted, where=f"the live {table}.{column} column")

    if checked_any:
        return
    # Nothing is persisted yet, so there is no live schema to disagree with.
    # The configured width is still worth checking: it catches an embedder
    # constructed by hand with the wrong one.
    if embedder.dim != EMBEDDING_DIM:
        raise _refusal(embedder, EMBEDDING_DIM, where="the configured schema width")


def _stale_chunks_condition(version: str):  # type: ignore[no-untyped-def]
    return (Chunk.embedding_version.is_distinct_from(version)) & (Chunk.content.is_not(None))


def _stale_communities_condition(version: str):  # type: ignore[no-untyped-def]
    return (KgCommunity.summary_embedding_version.is_distinct_from(version)) & (
        KgCommunity.summary.is_not(None)
    )


async def plan_reindex(
    session_factory: async_sessionmaker[AsyncSession], embedder: EmbeddingProvider
) -> ReindexPlan:
    version = embedder.version
    async with session_factory() as session:
        await _check_dimension(session, embedder)
        total_chunks = (await session.scalar(select(func.count(Chunk.id)))) or 0
        rows = await session.execute(
            select(Chunk.embedding_version, func.count(Chunk.id))
            .where(_stale_chunks_condition(version))
            .group_by(Chunk.embedding_version)
        )
        chunk_versions: dict[str | None, int] = {row[0]: row[1] for row in rows}
        stale_communities = (
            await session.scalar(
                select(func.count(KgCommunity.id)).where(_stale_communities_condition(version))
            )
        ) or 0
    return ReindexPlan(
        embedder_version=version,
        total_chunks=total_chunks,
        stale_chunks=sum(chunk_versions.values()),
        stale_communities=stale_communities,
        chunk_versions=chunk_versions,
    )


async def apply_reindex(
    session_factory: async_sessionmaker[AsyncSession],
    embedder: EmbeddingProvider,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: Callable[[str], None] | None = None,
) -> ReindexOutcome:
    """Re-embed stale rows in batches, committing after each batch."""
    async with session_factory() as session:
        # Read only, and before anything else: a refusal must cost nothing.
        await _check_dimension(session, embedder)
    version = embedder.version
    outcome = ReindexOutcome()

    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    while True:
        async with session_factory() as session:
            chunks = (
                (
                    await session.execute(
                        select(Chunk)
                        .where(_stale_chunks_condition(version))
                        .order_by(Chunk.id)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )
            if not chunks:
                break
            vectors = await embedder.embed([c.content for c in chunks], task="document")
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = embedder.assert_dimension(vector)
                chunk.embedding_version = version
            await session.commit()
        outcome.chunks_reembedded += len(chunks)
        outcome.batches += 1
        report(f"chunks: {outcome.chunks_reembedded} re-embedded")

    while True:
        async with session_factory() as session:
            communities = (
                (
                    await session.execute(
                        select(KgCommunity)
                        .where(_stale_communities_condition(version))
                        .order_by(KgCommunity.id)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )
            if not communities:
                break
            summaries = [c.summary or "" for c in communities]
            vectors = await embedder.embed(summaries, task="document")
            for community, vector in zip(communities, vectors, strict=True):
                community.summary_embedding = embedder.assert_dimension(vector)
                community.summary_embedding_version = version
            await session.commit()
        outcome.communities_reembedded += len(communities)
        outcome.batches += 1
        report(f"community summaries: {outcome.communities_reembedded} re-embedded")

    return outcome
