"""The domain tutorial's offline branch has to be reachable by succeeding.

`docs/bring-your-own-domain.md` advertises a route without credentials and
tells offline readers to use `--print-prompt` and `--from-file` throughout.
That covers the drafters. It does not cover graph extraction, community
construction, judged answer evaluation, or the cited-answer checkpoint, none
of which has an offline lane, so an offline reader following the page reached
four commands that exit 1 and no stated end state of their own.

A tutorial whose last checkpoint is an expected failure is not a tutorial with
an offline branch. These guards keep every model-only command behind an
explicit credentialed marker, and keep the offline reader's own end state on
the page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TUTORIAL = ROOT / "docs" / "bring-your-own-domain.md"

# The commands with no offline lane. The drafters are deliberately absent:
# every one of them takes `--print-prompt` and `--from-file`, which is the
# offline lane the page already documents.
MODEL_ONLY = (
    "sci-rag graph extract",
    "sci-rag graph communities",
    "sci-rag eval answers",
    "sci-rag answer",
)

# The marker a credentialed block carries. Prose, because the guard has to
# read what a reader reads, and a class nobody sees would drift from it.
CREDENTIALED_TITLE = '!!! note "Needs LLM provider credentials"'

# A single line inside a multi-command block may carry the same marker as a
# trailing comment instead, so a recipe card can list the credentialed step
# beside the offline ones without hiding it in a separate block.
INLINE_MARKER = "needs llm provider credentials"


def _page() -> str:
    return TUTORIAL.read_text(encoding="utf-8")


def _credentialed_regions(text: str) -> list[tuple[int, int]]:
    """Line spans covered by a credentialed admonition.

    An admonition owns every following line that is blank or indented, which
    is exactly MkDocs' own rule for where the block ends.
    """
    lines = text.splitlines()
    regions: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        if line.strip() != CREDENTIALED_TITLE:
            continue
        end = index + 1
        while end < len(lines) and (not lines[end].strip() or lines[end].startswith("    ")):
            end += 1
        regions.append((index, end))
    return regions


def _fenced_lines(text: str) -> list[tuple[int, str]]:
    """Lines inside a fenced block, which are the ones a reader copies.

    Prose that names a command is not the reader running it, and the page has
    to be able to say which commands need a credential in order to say it.
    """
    inside: list[tuple[int, str]] = []
    marker: str | None = None
    for number, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if marker is None and (stripped.startswith("```") or stripped.startswith("~~~")):
            marker = stripped[:3]
            continue
        if marker is not None and stripped.startswith(marker):
            marker = None
            continue
        if marker is not None:
            inside.append((number, line))
    return inside


@pytest.mark.parametrize("command", MODEL_ONLY)
def test_every_model_only_command_sits_inside_a_credentialed_block(command: str) -> None:
    text = _page()
    regions = _credentialed_regions(text)
    offenders = [
        number
        for number, line in _fenced_lines(text)
        if command in line
        and INLINE_MARKER not in line.casefold()
        and not any(start < number < end for start, end in regions)
    ]

    assert offenders == [], (
        f"{command!r} is offered as a command without a credentialed marker at lines {offenders}"
    )


def test_the_guard_can_see_an_ungated_command() -> None:
    """A guard that never fires would make the parametrization above vacuous."""
    ungated = "## Step\n\n```bash\nuv run sci-rag graph extract\n```\n"
    assert [number for number, _ in _fenced_lines(ungated)] == [3]
    assert _credentialed_regions(ungated) == []


def test_the_offline_reader_is_told_what_they_can_still_prove() -> None:
    """A skip without an outcome is an instruction to give up."""
    text = _page()
    normalized = re.sub(r"\s+", " ", text)

    assert "## Offline: what you can prove without a model" in text
    assert "eval retrieval" in normalized
    for reduced in ("ingest", "retrieve", "manifest lint"):
        assert reduced in normalized, reduced


def test_the_prerequisites_say_which_outcomes_need_a_credential() -> None:
    """The banner promised a path without credentials and named no limit."""
    text = _page()
    prerequisites = text.partition("## Before you start")[2].partition("## Step 0")[0]
    normalized = re.sub(r"\s+", " ", prerequisites)

    assert "graph" in normalized
    assert "cited answer" in normalized
    assert "judged" in normalized


def test_the_credentialed_end_state_is_labelled_as_credentialed() -> None:
    """The full end state is still the one to aim at, and it costs a credential."""
    text = _page()
    assert text.count(CREDENTIALED_TITLE) >= 3, "each model-only stage needs its own marker"
