"""Derived document means, with centering restricted to the visible corpus."""

from __future__ import annotations

import math
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document, DocumentEmbedding
from sci_rag.versions import lock_document_writes


def mean_vector(vectors: Sequence[Sequence[float]]) -> list[float]:
    if not vectors or len(vectors[0]) == 0:
        raise ValueError("no_vectors")
    width = len(vectors[0])
    if any(len(v) != width or any(not math.isfinite(float(x)) for x in v) for v in vectors):
        raise ValueError("invalid_vectors")
    return [math.fsum(float(v[i]) for v in vectors) / len(vectors) for i in range(width)]


def centered_cosine(
    a: Sequence[float], b: Sequence[float], center: Sequence[float]
) -> float | None:
    if len(a) != len(b) or len(a) != len(center):
        raise ValueError("dimension_mismatch")
    left, right = (
        [x - c for x, c in zip(a, center, strict=True)],
        [x - c for x, c in zip(b, center, strict=True)],
    )
    denominator = math.sqrt(math.fsum(x * x for x in left) * math.fsum(x * x for x in right))
    if denominator <= 1e-12:
        return None
    return max(
        -1.0, min(1.0, math.fsum(x * y for x, y in zip(left, right, strict=True)) / denominator)
    )


async def refresh_document_embedding(session: AsyncSession, document_id: str) -> bool:
    await session.flush()
    chunks = list(
        (await session.scalars(select(Chunk).where(Chunk.document_id == document_id))).all()
    )
    versions = {c.embedding_version for c in chunks}
    if (
        not chunks
        or any(c.embedding is None for c in chunks)
        or len(versions) != 1
        or None in versions
    ):
        await session.execute(
            delete(DocumentEmbedding).where(DocumentEmbedding.document_id == document_id)
        )
        return False
    vectors = [c.embedding for c in chunks if c.embedding is not None]
    vector = mean_vector(vectors)
    row = await session.get(DocumentEmbedding, document_id)
    version = next(iter(versions))
    assert version is not None
    if row is None:
        session.add(
            DocumentEmbedding(document_id=document_id, embedding=vector, embedding_version=version)
        )
    else:
        row.embedding, row.embedding_version = vector, version
    return True


async def rebuild_document_embeddings(
    factory: async_sessionmaker[AsyncSession], *, apply: bool = False
) -> dict[str, int | bool]:
    async with factory() as session:
        await lock_document_writes(session)
        ids = list(
            (await session.scalars(select(Document.id).where(Document.is_current.is_(True)))).all()
        )
        written = sum(
            [await refresh_document_embedding(session, document_id) for document_id in ids]
        )
        if apply:
            await session.commit()
        else:
            await session.rollback()
        return {"documents_scanned": len(ids), "vectors_ready": written, "applied": apply}
