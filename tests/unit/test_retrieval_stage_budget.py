"""How long each retrieval stage is allowed, and why the two budgets differ.

The per-stage timeout was written for database work, and it is the right
shape for that: a slow SQL layer should not hold a request open. Four of the
five stages call a provider before they reach SQL, though. Vector and
community await the shared query embedding, graph extracts query entities
with a model, HyDE generates a passage and then embeds it. Only keyword is
purely local.

Charging a remote call to a database budget is what made a supported live
Vertex project return nothing: a 32,945 ms query embedding cannot fit in 30
seconds, and every stage waiting on it failed together. So a stage that has
to call a provider gets the provider budget as well as the database budget,
and a local stage keeps the database budget alone.
"""

from __future__ import annotations

from typing import Any

import pytest

from sci_rag.config import Settings
from sci_rag.retrieve.retriever import PROVIDER_BACKED_STAGES, stage_budget_s


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_only_the_keyword_stage_is_purely_local() -> None:
    """Everything else waits on an embedding or a generation call first."""
    assert set(PROVIDER_BACKED_STAGES) == {"vector", "community", "graph", "hyde"}


@pytest.mark.parametrize("stage", sorted(PROVIDER_BACKED_STAGES))
def test_a_provider_backed_stage_gets_both_budgets(stage: str) -> None:
    settings = _settings(deep_stage_timeout_s=30.0, provider_call_timeout_s=60.0)
    assert stage_budget_s(stage, 30.0, settings) == 90.0


def test_a_local_stage_keeps_the_database_budget_alone() -> None:
    settings = _settings(deep_stage_timeout_s=30.0, provider_call_timeout_s=60.0)
    assert stage_budget_s("keyword", 30.0, settings) == 30.0


def test_the_default_provider_budget_clears_the_measured_vertex_latency() -> None:
    """32,945 ms and 36,819 ms are the query embeddings the audit timed live.

    The default has to clear the slowest of them with room to spare, or the
    documented route needs a manual override again.
    """
    assert _settings().provider_call_timeout_s >= 45.0


def test_the_interactive_profile_is_fixed_by_the_same_rule() -> None:
    """`make demo` retrieves on the interactive profile, whose budget is 8s.

    A live query embedding cannot fit in 8 seconds either, so the quickstart's
    retrieval checkpoint was inside the same defect. One rule covers both
    profiles rather than a second special case for this one.
    """
    settings = _settings()
    interactive = settings.interactive_stage_timeout_s
    assert stage_budget_s("vector", interactive, settings) > 30.0
    assert stage_budget_s("keyword", interactive, settings) == interactive
