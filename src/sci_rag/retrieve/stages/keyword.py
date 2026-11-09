"""Layer 2: keyword full-text search.

Postgres full-text search over the generated ``search_tsv`` column (GIN
indexed). ``websearch_to_tsquery`` accepts raw user input safely, including
quoted phrases and stray punctuation. This layer catches the exact terms,
model numbers, and chemical names that embeddings sometimes blur.
"""

from __future__ import annotations

import re

from sqlalchemy import ColumnElement, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document
from sci_rag.keyword_tokens import chinese_search_tokens, contains_han
from sci_rag.retrieve.types import Key, RetrievalScope, scope_conditions


async def keyword_stage(
    session_factory: async_sessionmaker[AsyncSession],
    query: str,
    scope: RetrievalScope,
    limit: int,
) -> list[Key]:
    if limit <= 0 or not query.strip():
        return []
    if contains_han(query):
        tokens = chinese_search_tokens(query)
        if not tokens:
            return []
        # OR preserves recall for natural questions containing absent filler words.
        # Tokens contain only word characters and all query values stay bound.
        tsquery = func.websearch_to_tsquery("simple", " OR ".join(tokens))
        vector = Chunk.search_zh_tsv
    else:
        tsquery = func.websearch_to_tsquery("english", query)
        vector = Chunk.search_tsv
    condition: ColumnElement[bool] = vector.op("@@")(tsquery)
    rank = func.ts_rank(vector, tsquery)
    if not contains_han(query):
        # Preserve English stemming/phrase syntax while matching identifiers
        # segmented from adjacent Chinese punctuation in the simple index.
        fallback = func.websearch_to_tsquery("simple", query)
        condition = or_(condition, Chunk.search_zh_tsv.op("@@")(fallback))
        rank = func.greatest(rank, func.ts_rank(Chunk.search_zh_tsv, fallback))
    ordering = [rank.desc(), Chunk.id]
    identifiers = re.findall(r"[A-Za-z][A-Za-z0-9_-]*[0-9][A-Za-z0-9_-]*", query)
    if contains_han(query) and identifiers:
        exact = func.websearch_to_tsquery("simple", " OR ".join(identifiers))
        # An explicit identifier outranks common question words such as the
        # Chinese word for "number", before the bounded candidate limit.
        ordering.insert(0, case((Chunk.search_zh_tsv.op("@@")(exact), 1), else_=0).desc())
    async with session_factory() as session:
        statement = (
            select(Chunk.id)
            .join(Document, Chunk.document_id == Document.id)
            .where(condition, *scope_conditions(scope))
            .order_by(*ordering)
            .limit(limit)
        )
        rows = (await session.execute(statement)).scalars().all()
    return [("chunk", chunk_id) for chunk_id in rows]
