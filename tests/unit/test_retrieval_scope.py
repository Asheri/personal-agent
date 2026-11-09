"""The scope contract, dimension by dimension.

Two properties are load-bearing and easy to break silently when a new
filter dimension is added:

1. Every populated field must emit a SQL condition, because the stages
   apply ``scope_conditions()`` and nothing else.
2. Every field must make ``is_unrestricted()`` False, because the
   community layer gates on it. A stored community summary aggregates
   evidence across documents before any scope is known, so a scoped
   caller must not receive one. A new dimension that forgets this gate
   would leave communities quietly serving out-of-scope content.

The parametrized cases below exist so that adding a field without
teaching ``is_unrestricted()`` about it fails here rather than in
production.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date

import pytest

from sci_rag.evals.retrieval_eval import DEFAULT_ABLATIONS, RESOLVED_ENTITIES_CONFIG
from sci_rag.retrieve.types import RetrievalScope, scope_conditions

# One kwargs dict per restriction dimension.
RESTRICTIONS: list[dict[str, object]] = [
    {"license_classes": ("public",)},
    {"sources": ("tests",)},
    {"exclude_document_ids": ("abc",)},
    {"year_min": 2020},
    {"year_max": 2024},
    {"authors": ("Bhattacharya",)},
    {"journals": ("Biomass and Bioenergy",)},
    {"exclude_dois": ("10.1234/x",)},
    {"exclude_retracted": True},
    {"date_min": date(2026, 1, 1)},
    {"date_max": date(2026, 12, 31)},
    {"projects": ("project-id",)},
    {"tags": ("manual",)},
    {"auto_tags": ("automatic",)},
    {"entity_names": ("Topic",)},
]


def test_default_scope_keeps_the_current_version_baseline() -> None:
    scope = RetrievalScope()
    assert scope.is_unrestricted()
    [condition] = scope_conditions(scope)
    assert "documents.is_current IS true" in str(condition)
    assert scope_conditions(RetrievalScope(include_superseded=True)) == []


@pytest.mark.parametrize("kwargs", RESTRICTIONS, ids=lambda k: next(iter(k)))
def test_every_dimension_restricts(kwargs: dict[str, object]) -> None:
    scope = RetrievalScope(**kwargs)  # type: ignore[arg-type]
    assert not scope.is_unrestricted(), (
        f"{next(iter(kwargs))} does not make the scope restricted; the community "
        "layer would keep serving cross-document summaries to a scoped caller"
    )
    assert len(scope_conditions(scope)) == 2
    assert len(scope_conditions(RetrievalScope(include_superseded=True, **kwargs))) == 1  # type: ignore[arg-type]


def test_year_range_emits_two_conditions() -> None:
    scope = RetrievalScope(year_min=2020, year_max=2024)
    assert len(scope_conditions(scope)) == 3


def test_denies_all_only_for_empty_license_tuple() -> None:
    assert RetrievalScope(license_classes=()).denies_all()
    assert not RetrievalScope(license_classes=("public",)).denies_all()
    # An empty tuple on a different dimension is "no restriction stated",
    # not "deny everything"; only the license allowlist fails closed.
    assert not RetrievalScope(authors=()).denies_all()
    assert not RetrievalScope(exclude_dois=()).denies_all()


def test_empty_non_license_tuples_do_not_restrict() -> None:
    """An empty author or journal tuple means nobody asked, not nobody passes."""
    assert RetrievalScope(authors=()).is_unrestricted()
    assert RetrievalScope(journals=()).is_unrestricted()
    assert RetrievalScope(exclude_dois=()).is_unrestricted()
    assert len(scope_conditions(RetrievalScope(authors=(), journals=(), exclude_dois=()))) == 1


def test_every_scope_field_is_covered_by_the_dimension_cases() -> None:
    assert {next(iter(case)) for case in RESTRICTIONS} == {
        field.name for field in fields(RetrievalScope)
    } - {"include_superseded"}


def test_scope_stays_hashable() -> None:
    """Frozen and hashable: scopes are cache keys in places."""
    scope = RetrievalScope(year_min=2020, authors=("A",), journals=("J",))
    assert hash(scope) == hash(RetrievalScope(year_min=2020, authors=("A",), journals=("J",)))


def test_no_retracted_ablation_carries_the_filter_scope() -> None:
    config = next(config for config in DEFAULT_ABLATIONS if config.name == "no_retracted")

    assert config.scope == RetrievalScope(exclude_retracted=True)


def test_entity_resolution_is_an_explicit_snapshot_condition() -> None:
    assert RESOLVED_ENTITIES_CONFIG.name == "resolved_entities"
    assert RESOLVED_ENTITIES_CONFIG not in DEFAULT_ABLATIONS
