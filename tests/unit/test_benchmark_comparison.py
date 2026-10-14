"""Drift in a published benchmark has to be shown, not absorbed.

`make benchmark` rendered straight over `docs/benchmarks.md`. A run whose
graph came out with 93 entities instead of 83 and whose mean correctness moved
from 1.3 to 1.9 left exactly the same trace as a run that reproduced: a
rewritten file. Whether those numbers are expected model variance or a changed
input is a scientific question, and it cannot be asked if nobody is shown the
move.

So the renderer compares before writing, states the tolerance it is judging
against, and `--check` exits nonzero when a published number has moved outside
it.
"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pytest

# The renderers are scripts rather than package modules, so they are loaded
# the way `test_doc_renderers.py` loads them.
_MODULE: dict | None = None


def _renderer() -> dict:  # type: ignore[type-arg]
    global _MODULE
    if _MODULE is None:
        _MODULE = run_path("scripts/render_benchmarks.py")
    return _MODULE


TOLERANCES = _renderer()["TOLERANCES"]
compare_pages = _renderer()["compare_pages"]


def _page(**numbers: object) -> str:
    return (
        "# Benchmarks\n\n"
        f"- Corpus: {numbers.get('documents', 5)} documents, {numbers.get('chunks', 34)} chunks, "
        f"{numbers.get('entities', 83)} entities, {numbers.get('relationships', 79)} "
        f"relationships, {numbers.get('communities', 7)} communities\n"
        "\n| Config | hit@5 |\n|---|---:|\n"
        f"| full_deep | {numbers.get('hit', '0.89')} |\n"
    )


def test_an_identical_render_reports_no_drift() -> None:
    assert compare_pages(_page(), _page()) == []


def test_a_metric_inside_the_tolerance_is_reported_but_not_a_failure() -> None:
    """Small movement on nine questions is noise, and saying so is the point."""
    moved = compare_pages(_page(), _page(hit="0.90"))

    assert moved, "a change always gets reported"
    assert all(not entry.material for entry in moved)


@pytest.mark.parametrize(
    ("field", "before", "after"),
    (("entities", 83, 84), ("relationships", 79, 80)),
)
def test_pinned_graph_counts_have_zero_tolerance(field: str, before: int, after: int) -> None:
    """One pinned graph row moving is implementation or provenance drift."""
    moved = compare_pages(_page(**{field: before}), _page(**{field: after}))

    assert len(moved) == 1
    assert moved[0].label == field
    assert moved[0].material


@pytest.mark.parametrize("field", ("documents", "chunks", "communities"))
def test_other_counts_keep_the_declared_relative_tolerance(field: str) -> None:
    """Only replay-pinned graph counts become exact comparisons."""
    moved = compare_pages(_page(**{field: 100}), _page(**{field: 105}))

    assert len(moved) == 1
    assert moved[0].label == field
    assert not moved[0].material


def test_the_tolerances_are_declared_rather_than_implied() -> None:
    """A tolerance nobody can read is not a scientific tolerance."""
    assert set(TOLERANCES) == {"metric", "count"}
    assert 0 < TOLERANCES["metric"] < 0.2
    assert 0 < TOLERANCES["count"] < 0.2


def test_check_mode_exits_nonzero_when_a_published_number_moved(tmp_path: Path) -> None:
    check_against_committed = _renderer()["check_against_committed"]

    committed = tmp_path / "benchmarks.md"
    committed.write_text(_page(), encoding="utf-8")

    with pytest.raises(SystemExit) as caught:
        check_against_committed(_page(entities=93), committed)

    assert caught.value.code != 0


def test_check_mode_passes_when_nothing_material_moved(tmp_path: Path) -> None:
    check_against_committed = _renderer()["check_against_committed"]

    committed = tmp_path / "benchmarks.md"
    committed.write_text(_page(), encoding="utf-8")

    check_against_committed(_page(hit="0.90"), committed)


def test_the_published_page_states_the_tolerance_the_renderer_judges_against() -> None:
    """The page is generated, but only a credentialed run regenerates it.

    `eval_results/` is ignored, so nothing in the repository can re-render this
    page offline. That makes the statement of the tolerance the one part a
    reader can check here, and holding it to the renderer's own constant is
    what stops the two from drifting between benchmark runs.
    """
    page = Path("docs/benchmarks.md").read_text(encoding="utf-8")

    assert f"{TOLERANCES['metric']} absolute on a metric" in page
    count_tolerance = f"{TOLERANCES['count']:.0%} on"
    assert any(
        phrase in page
        for phrase in (
            f"{count_tolerance} a count",
            f"{count_tolerance} other counts",
        )
    )
    assert "Publishing movement beyond the tolerance requires" in page
