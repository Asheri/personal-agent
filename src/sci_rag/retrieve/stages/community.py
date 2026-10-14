"""Layer 4: community summaries.

Vector search over the LLM-written summaries of knowledge-graph clusters.
This is the layer that answers "big picture" questions no single chunk
covers ("what does this corpus say about rice straw overall?").

One deliberate restriction: a stored summary aggregates evidence from many
documents before any caller's scope is known, so this layer disables
itself whenever license, source, or exclusion filters are active. A
scoped caller must never receive a summary partially built from documents
outside their scope.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import KgCommunity
from sci_rag.retrieve.types import Key, RetrievalScope


async def community_stage(
    session_factory: async_sessionmaker[AsyncSession],
    query_vector: list[float],
    scope: RetrievalScope,
    limit: int,
) -> list[Key]:
    if not scope.is_unrestricted():
        # The orchestrator records this stage as "skipped".
        return []
    async with session_factory() as session:
        statement = (
            select(KgCommunity.id)
            .where(
                KgCommunity.summary_embedding.is_not(None),
                KgCommunity.summary.is_not(None),
            )
            .order_by(KgCommunity.summary_embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        rows = (await session.execute(statement)).scalars().all()
    return [("community", community_id) for community_id in rows]
