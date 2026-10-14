"""Layer 1: dense vector similarity.

Cosine distance over chunk embeddings, served by the HNSW index. This is
the workhorse layer and carries the highest fusion weight.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document
from sci_rag.retrieve.types import Key, RetrievalScope, scope_conditions


async def vector_stage(
    session_factory: async_sessionmaker[AsyncSession],
    query_vector: list[float],
    scope: RetrievalScope,
    limit: int,
) -> list[Key]:
    async with session_factory() as session:
        statement = (
            select(Chunk.id)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.embedding.is_not(None), *scope_conditions(scope))
            .order_by(Chunk.embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        rows = (await session.execute(statement)).scalars().all()
    return [("chunk", chunk_id) for chunk_id in rows]
