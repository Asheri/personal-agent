"""Reranker unit tests: scoring, fallback, config, and the nDCG metric.

The reranker is off by default and must never be able to take a request
down: every failure mode (malformed JSON, timeout, missing scores) falls
back to the fused order and says so in the trace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.domain import load_domain
from sci_rag.evals.retrieval_eval import DEFAULT_ABLATIONS, ndcg_at_k
from sci_rag.llm import MockLLM
from sci_rag.retrieve.rerank import LLMReranker, RerankError
from sci_rag.retrieve.types import RetrievedItem

DOMAIN_DIR = Path(__file__).parents[2] / "domain"


def make_items(n: int) -> list[RetrievedItem]:
    return [
        RetrievedItem(
            kind="chunk",
            id=f"c{i}",
            score=1.0 / (i + 1),
            layers=["vector"],
            title=f"Doc {i}",
            content=f"content number {i}",
        )
        for i in range(n)
    ]


@pytest.fixture(scope="module")
def domain():  # type: ignore[no-untyped-def]
    return load_domain(DOMAIN_DIR)


class TestLLMReranker:
    @pytest.mark.asyncio
    async def test_reorders_by_llm_scores(self, domain) -> None:  # type: ignore[no-untyped-def]
        items = make_items(3)
        llm = MockLLM(
            responses=[
                json.dumps(
                    {
                        "scores": [
                            {"index": 0, "score": 1},
                            {"index": 1, "score": 9},
                            {"index": 2, "score": 5},
                        ]
                    }
                )
            ]
        )
        reranker = LLMReranker(llm, domain)
        ranked = await reranker.rerank("test query", items, top_k=3)
        assert [item.id for item in ranked] == ["c1", "c2", "c0"]

    @pytest.mark.asyncio
    async def test_unscored_items_keep_fused_order_after_scored(self, domain) -> None:  # type: ignore[no-untyped-def]
        items = make_items(4)
        llm = MockLLM(
            responses=[json.dumps({"scores": [{"index": 3, "score": 9}, {"index": 1, "score": 5}]})]
        )
        reranker = LLMReranker(llm, domain)
        ranked = await reranker.rerank("q", items, top_k=4)
        # Scored first (by score desc), then unscored in fused order.
        assert [item.id for item in ranked] == ["c3", "c1", "c0", "c2"]

    @pytest.mark.asyncio
    async def test_top_k_truncates(self, domain) -> None:  # type: ignore[no-untyped-def]
        items = make_items(5)
        llm = MockLLM(
            responses=[json.dumps({"scores": [{"index": i, "score": 10 - i} for i in range(5)]})]
        )
        ranked = await LLMReranker(llm, domain).rerank("q", items, top_k=2)
        assert len(ranked) == 2

    @pytest.mark.asyncio
    async def test_malformed_json_raises_rerank_error(self, domain) -> None:  # type: ignore[no-untyped-def]
        items = make_items(2)
        llm = MockLLM(responses=["this is not json"])
        with pytest.raises(RerankError):
            await LLMReranker(llm, domain).rerank("q", items, top_k=2)

    @pytest.mark.asyncio
    async def test_missing_scores_key_raises(self, domain) -> None:  # type: ignore[no-untyped-def]
        items = make_items(2)
        llm = MockLLM(responses=[json.dumps({"rankings": []})])
        with pytest.raises(RerankError):
            await LLMReranker(llm, domain).rerank("q", items, top_k=2)

    @pytest.mark.asyncio
    async def test_out_of_range_indices_ignored(self, domain) -> None:  # type: ignore[no-untyped-def]
        items = make_items(2)
        llm = MockLLM(
            responses=[
                json.dumps({"scores": [{"index": 99, "score": 9}, {"index": 1, "score": 5}]})
            ]
        )
        ranked = await LLMReranker(llm, domain).rerank("q", items, top_k=2)
        assert [item.id for item in ranked] == ["c1", "c0"]

    @pytest.mark.asyncio
    async def test_empty_pool_short_circuits_without_llm_call(self, domain) -> None:  # type: ignore[no-untyped-def]
        llm = MockLLM()
        ranked = await LLMReranker(llm, domain).rerank("q", [], top_k=5)
        assert ranked == []
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_prompt_contains_query_and_candidates(self, domain) -> None:  # type: ignore[no-untyped-def]
        items = make_items(2)
        llm = MockLLM(responses=[json.dumps({"scores": [{"index": 0, "score": 5}]})])
        await LLMReranker(llm, domain).rerank("rice straw yield", items, top_k=2)
        prompt = llm.calls[0]["prompt"]
        assert "rice straw yield" in prompt
        assert "content number 0" in prompt
        assert llm.calls[0]["json_mode"] is True


class TestRerankerConfig:
    def test_domain_reranker_defaults(self, domain) -> None:  # type: ignore[no-untyped-def]
        cfg = domain.config.retrieval.reranker
        assert cfg.enabled is False
        assert cfg.adapter == "llm"
        assert cfg.pool == 20
        assert cfg.timeout_s > 0

    def test_ablation_configs_include_rerank_pair(self) -> None:
        names = {c.name for c in DEFAULT_ABLATIONS}
        assert "with_rerank" in names
        assert "no_rerank" in names
        with_rerank = next(c for c in DEFAULT_ABLATIONS if c.name == "with_rerank")
        assert with_rerank.kwargs.get("include_rerank") is True


class TestNdcg:
    def test_perfect_ranking_is_one(self) -> None:
        # Two relevant items at ranks 1 and 2 of 5 retrieved.
        assert ndcg_at_k([1, 2], k=5) == pytest.approx(1.0)

    def test_no_relevant_is_zero(self) -> None:
        assert ndcg_at_k([], k=5) == 0.0

    def test_late_ranking_below_early(self) -> None:
        early = ndcg_at_k([1], k=10)
        late = ndcg_at_k([10], k=10)
        assert early == pytest.approx(1.0)
        assert 0 < late < early

    def test_hand_computed_value(self) -> None:
        # One relevant item at rank 3: DCG = 1/log2(4); IDCG = 1/log2(2) = 1.
        import math

        expected = (1.0 / math.log2(4)) / 1.0
        assert ndcg_at_k([3], k=5) == pytest.approx(expected)

    def test_ranks_beyond_k_do_not_count(self) -> None:
        assert ndcg_at_k([7], k=5) == 0.0
