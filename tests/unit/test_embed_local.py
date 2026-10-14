import math

import pytest

from sci_rag.embed import LocalHashEmbedder, QueryEmbeddingCache


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_dimension_and_unit_norm() -> None:
    embedder = LocalHashEmbedder(64)
    [vec] = await embedder.embed(["rice straw availability in Colusa County"], task="document")
    assert len(vec) == 64
    assert math.isclose(sum(v * v for v in vec), 1.0, rel_tol=1e-9)


async def test_deterministic() -> None:
    embedder = LocalHashEmbedder(64)
    a = await embedder.embed(["identical text"], task="document")
    b = await embedder.embed(["identical text"], task="query")
    assert a == b


async def test_lexical_similarity_orders_sensibly() -> None:
    embedder = LocalHashEmbedder(256)
    [query] = await embedder.embed(["almond orchard residue yields"], task="query")
    [near] = await embedder.embed(
        ["Almond orchard residues have yields near 1.2 tons per acre."], task="document"
    )
    [far] = await embedder.embed(
        ["Distillation column reflux ratios depend on relative volatility."], task="document"
    )
    assert _cosine(query, near) > _cosine(query, far)


async def test_empty_text_returns_stable_unit_vector() -> None:
    embedder = LocalHashEmbedder(16)
    [vec] = await embedder.embed([""], task="document")
    assert math.isclose(sum(v * v for v in vec), 1.0, rel_tol=1e-9)


async def test_query_cache_hits_and_respects_bypass() -> None:
    class Counting(LocalHashEmbedder):
        calls = 0

        async def embed(self, texts, *, task):  # type: ignore[no-untyped-def]
            Counting.calls += 1
            return await super().embed(texts, task=task)

    cache = QueryEmbeddingCache(Counting(32))
    await cache.embed_query("same question")
    await cache.embed_query("same question")
    assert Counting.calls == 1
    await cache.embed_query("same question", use_cache=False)
    assert Counting.calls == 2


async def test_dimension_assertion_fires() -> None:
    from sci_rag.embed import EmbeddingDimensionError

    embedder = LocalHashEmbedder(32)
    with pytest.raises(EmbeddingDimensionError):
        embedder.assert_dimension([0.0] * 16)
