"""The partner-model examples the docs name, and how they stay true.

F-030 read a model card and a release-notes entry and concluded the guide's
example was retired. A live call to the documented endpoint says otherwise:
both `grok-4.1-fast` ids answered on 2026-08-30, ten days after the shutdown
date the finding cites, while the newer ids it suggested return `NotFound`
here. Documentation about a lifecycle and a 200 from the endpoint are
different kinds of evidence, and the endpoint is the one a reader hits.

What the finding is right about is that nothing kept the guide honest. A model
id in prose has no date on it and nothing re-checks it, so the next time one
really does go away the guide will say so for as long as nobody notices. The
registry below is the list a live check walks, and these guards keep it and
the prose from drifting apart.
"""

from __future__ import annotations

import re
from pathlib import Path
from runpy import run_path

ROOT = Path(__file__).resolve().parents[2]

_MODULE: dict | None = None  # type: ignore[type-arg]


def _checker() -> dict:  # type: ignore[type-arg]
    global _MODULE
    if _MODULE is None:
        _MODULE = run_path("scripts/check_partner_models.py")
    return _MODULE


#: Where a reader meets a concrete partner-model id.
READER_SURFACES = ("docs/extend.md", ".env.example")

#: A model id written as an example of a misconfiguration rather than as
#: something to run. `docs/troubleshooting.md` names one to show what happens
#: when you reach for a model with no credential behind it, and putting that in
#: the registry would mean probing a model nobody is being told to use.
NOT_A_RECOMMENDATION = "anthropic:claude-opus-5"

_MODEL_ID = re.compile(r"(?:anthropic:|openai-compatible:)?xai/[a-z0-9.-]+|anthropic:[a-z0-9.-]+")


def _named_in_docs() -> set[str]:
    found: set[str] = set()
    for surface in READER_SURFACES:
        for match in _MODEL_ID.finditer((ROOT / surface).read_text(encoding="utf-8")):
            found.add(match.group(0))
    return {name for name in found if name != NOT_A_RECOMMENDATION}


def _registry_ids() -> set[str]:
    return {entry.model for entry in _checker()["PARTNER_MODELS"]}


def test_every_partner_model_a_reader_can_copy_is_in_the_registry() -> None:
    """An id nobody checks is an id that outlives its model."""
    missing = sorted(
        name
        for name in _named_in_docs()
        if not any(name in registered for registered in _registry_ids())
    )

    assert missing == [], f"named in the docs but never checked: {missing}"


def test_the_registry_names_nothing_the_docs_do_not() -> None:
    """Drift the other way: checking a model no reader is told about."""
    named = _named_in_docs()
    stale = sorted(
        entry.model
        for entry in _checker()["PARTNER_MODELS"]
        if not any(name in entry.model for name in named)
    )

    assert stale == [], f"checked but named nowhere a reader looks: {stale}"


def test_every_entry_records_where_it_is_served_and_when_it_last_answered() -> None:
    for entry in _checker()["PARTNER_MODELS"]:
        assert entry.location, entry.model
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry.verified), entry.model


def test_the_guide_publishes_the_verification_date_and_the_lifecycle_source() -> None:
    """A dated example is a claim a reader can judge; an undated one is not."""
    page = (ROOT / "docs" / "extend.md").read_text(encoding="utf-8")
    newest = max(entry.verified for entry in _checker()["PARTNER_MODELS"])

    assert newest in page, "the guide has to say when these ids last answered"
    assert "make providers-check" in page, "and how to ask again"
    assert "partner-models" in page, "and where the provider states the lifecycle"


def test_the_check_reports_a_model_that_no_longer_answers() -> None:
    """The failure mode this exists for, without contacting a provider."""
    summarize = _checker()["summarize"]
    entry = _checker()["PARTNER_MODELS"][0]

    ok, lines = summarize([(entry, True, "answered in 885 ms")])
    assert ok
    assert "answered" in "\n".join(lines)

    ok, lines = summarize([(entry, False, "The model was not found in global.")])
    assert not ok
    assert entry.model in "\n".join(lines)
