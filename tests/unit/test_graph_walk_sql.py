"""Confidence-aware graph traversal stays opt-in and parameterized."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sci_rag.domain import GraphTuning, load_domain
from sci_rag.embed import LocalHashEmbedder
from sci_rag.evals.retrieval_eval import DEFAULT_ABLATIONS
from sci_rag.llm import MockLLM
from sci_rag.retrieve import Retriever
from sci_rag.retrieve.stages.graph import _WALK_SQL


def test_graph_tuning_is_off_by_default() -> None:
    tuning = load_domain(Path(__file__).parents[2] / "domain").config.retrieval.graph

    assert tuning.min_confidence == 0.0
    assert tuning.confidence_weighted is False
    assert tuning.include_citations is False


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_graph_confidence_threshold_is_a_probability(value: float) -> None:
    with pytest.raises(ValidationError):
        GraphTuning(min_confidence=value)


def test_walk_sql_binds_threshold_and_tracks_minimum_path_confidence() -> None:
    sql = str(_WALK_SQL)

    assert "r.confidence >= :min_confidence" in sql
    assert "LEAST(w.path_confidence, r.confidence)" in sql
    assert ":confidence_weighted" in sql


def test_confidence_weighted_ablation_is_an_explicit_opt_in() -> None:
    config = next(config for config in DEFAULT_ABLATIONS if config.name == "confidence_weighted")

    assert config.kwargs == {"profile": "deep", "graph_confidence_weighted": True}


def test_citation_ablation_is_an_explicit_opt_in() -> None:
    config = next(config for config in DEFAULT_ABLATIONS if config.name == "with_citations")

    assert config.kwargs == {"profile": "deep", "graph_include_citations": True}
    assert "document_citations" in str(_WALK_SQL)
    assert ":include_citations" in str(_WALK_SQL)


@pytest.mark.asyncio
async def test_retriever_passes_domain_threshold_and_ablation_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    domain = load_domain(Path(__file__).parents[2] / "domain")
    domain.config.retrieval.graph.min_confidence = 0.6
    seen: list[tuple[float, bool, bool]] = []

    async def fake_graph_stage(  # type: ignore[no-untyped-def]
        *args,
        min_confidence: float,
        confidence_weighted: bool,
        include_citations: bool,
    ):
        seen.append((min_confidence, confidence_weighted, include_citations))
        return []

    async def fake_resolve(*args):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr("sci_rag.retrieve.retriever.graph_stage", fake_graph_stage)
    retriever = Retriever(
        domain=domain,
        embedder=LocalHashEmbedder(64),
        llm=MockLLM(),
        session_factory=object(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(retriever, "_resolve", fake_resolve)

    shared = {
        "include_vector": False,
        "include_keyword": False,
        "include_graph": True,
        "include_community": False,
        "include_hyde": False,
        "include_rerank": False,
    }
    await retriever.retrieve("query", **shared)  # type: ignore[arg-type]
    await retriever.retrieve(
        "query",
        graph_confidence_weighted=True,
        **shared,  # type: ignore[arg-type]
    )

    assert seen == [(0.6, False, False), (0.6, True, False)]
