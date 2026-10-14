"""Adaptive routing: cheap, explainable query classification.

The router maps a query to a retrieval plan (profile + layer set) using
transparent heuristics, with an optional LLM fallback only when the
heuristics are genuinely ambiguous AND a client was provided. Every
decision carries human-readable reasons; nothing here is a black box.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.domain import load_domain
from sci_rag.evals.retrieval_eval import DEFAULT_ABLATIONS
from sci_rag.llm import MockLLM
from sci_rag.retrieve.router import RoutingDecision, route

DOMAIN_DIR = Path(__file__).parents[2] / "domain"


@pytest.fixture(scope="module")
def domain():  # type: ignore[no-untyped-def]
    return load_domain(DOMAIN_DIR)


class TestHeuristics:
    @pytest.mark.asyncio
    async def test_multi_hop_comparative_routes_deep_with_graph(self, domain) -> None:  # type: ignore[no-untyped-def]
        decision = await route(
            "compare rice straw and almond prunings for anaerobic digestion", domain
        )
        assert decision.profile == "deep"
        assert decision.include_graph is True
        assert any("multi-hop" in r or "comparative" in r for r in decision.reasons)

    @pytest.mark.asyncio
    async def test_causal_chain_routes_deep(self, domain) -> None:  # type: ignore[no-untyped-def]
        decision = await route(
            "how does moisture content affect gasification tar formation", domain
        )
        assert decision.profile == "deep"
        assert decision.include_graph is True

    @pytest.mark.asyncio
    async def test_short_factual_lookup_routes_interactive(self, domain) -> None:  # type: ignore[no-untyped-def]
        decision = await route("what is the ash content of rice straw", domain)
        assert decision.profile == "interactive"
        assert decision.include_graph is False
        assert decision.include_community is False

    @pytest.mark.asyncio
    async def test_overview_question_enables_communities(self, domain) -> None:  # type: ignore[no-untyped-def]
        decision = await route("give me an overview of the main themes in the corpus", domain)
        assert decision.include_community is True
        assert decision.profile == "deep"

    @pytest.mark.asyncio
    async def test_matched_query_class_recorded(self, domain) -> None:  # type: ignore[no-untyped-def]
        decision = await route("what is the ash content of rice straw", domain)
        assert decision.matched_class == "properties"

    @pytest.mark.asyncio
    async def test_deterministic_without_llm(self, domain) -> None:  # type: ignore[no-untyped-def]
        query = "residue supply overview across the region"
        first = await route(query, domain)
        second = await route(query, domain)
        assert first == second

    @pytest.mark.asyncio
    async def test_every_decision_has_reasons(self, domain) -> None:  # type: ignore[no-untyped-def]
        for query in (
            "compare X and Y",
            "what is Z",
            "overview of everything",
            "cellulose",
        ):
            decision = await route(query, domain)
            assert decision.reasons, f"no reasons for {query!r}"


class TestAmbiguousFallback:
    @pytest.mark.asyncio
    async def test_ambiguous_without_llm_defaults_deep(self, domain) -> None:  # type: ignore[no-untyped-def]
        decision = await route("cellulose valorization pathways contextualization", domain)
        assert decision.profile == "deep"
        assert decision.ambiguous is True

    @pytest.mark.asyncio
    async def test_ambiguous_with_llm_uses_its_answer(self, domain) -> None:  # type: ignore[no-untyped-def]
        llm = MockLLM(responses=[json.dumps({"profile": "interactive"})])
        decision = await route("cellulose valorization pathways contextualization", domain, llm=llm)
        assert decision.profile == "interactive"
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_unambiguous_query_never_calls_llm(self, domain) -> None:  # type: ignore[no-untyped-def]
        llm = MockLLM()
        await route("what is the ash content of rice straw", domain, llm=llm)
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_deep(self, domain) -> None:  # type: ignore[no-untyped-def]
        llm = MockLLM(responses=["not json"])
        decision = await route("cellulose valorization pathways contextualization", domain, llm=llm)
        assert decision.profile == "deep"


class TestPlumbing:
    def test_auto_routed_ablation_exists(self) -> None:
        config = next(c for c in DEFAULT_ABLATIONS if c.name == "auto_routed")
        assert config.kwargs.get("profile") == "auto"

    def test_query_request_accepts_auto(self) -> None:
        from sci_rag.server.schemas import QueryRequest

        request = QueryRequest(query="anything", profile="auto")
        assert request.profile == "auto"

    def test_decision_layer_flags_complete(self) -> None:
        for field in ("profile", "include_graph", "include_community", "include_hyde", "reasons"):
            assert field in RoutingDecision.__dataclass_fields__
