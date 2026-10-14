"""Layer 2: keyword full-text search.

Postgres full-text search over the generated ``search_tsv`` column (GIN
indexed). ``websearch_to_tsquery`` accepts raw user input safely, including
quoted phrases and stray punctuation. This layer catches the exact terms,
model numbers, and chemical names that embeddings sometimes blur.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document
from sci_rag.retrieve.types import Key, RetrievalScope, scope_conditions


async def keyword_stage(
    session_factory: async_sessionmaker[AsyncSession],
    query: str,
    scope: RetrievalScope,
    limit: int,
) -> list[Key]:
    tsquery = func.websearch_to_tsquery("english", query)
    async with session_factory() as session:
        statement = (
            select(Chunk.id)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.search_tsv.op("@@")(tsquery), *scope_conditions(scope))
            .order_by(func.ts_rank(Chunk.search_tsv, tsquery).desc(), Chunk.id)
            .limit(limit)
        )
        rows = (await session.execute(statement)).scalars().all()
    return [("chunk", chunk_id) for chunk_id in rows]
