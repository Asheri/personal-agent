"""The HTML eval view: one file, openable by someone with no terminal.

The audience for this renderer is a collaborator who will never run
`sci-rag`. That constrains it more than it first appears. A single file
they can be sent, with nothing fetched when they open it, because a
shared report that phones out is a report that renders differently for
the recipient than for the sender, and eventually renders as a blank
page behind a firewall.

The honest-reading guidance travels with the numbers for the same
reason: the markdown report warns about small samples and drafted ground
truth next to the metric, and a prettier view that drops the warning is
worse than no view.
"""

from __future__ import annotations

import json
from pathlib import Path

from sci_rag.evals.html import render_html

PROVENANCE = {
    "embedding": "gemini-embedding-001@1536",
    "models": {"answer": "google:gemini-2.5-flash", "judge": "google:gemini-2.5-flash"},
    "domain_digest": "11194722ed596f61cf2ebafb5e45a07e7048b1aaefc50d966c8d24734cd3cb6d",
    "decoding": {"temperature": 0.0, "json_mode": True},
}

CORPUS = {"documents": 5, "chunks": 34, "entities": 72, "relationships": 72, "communities": 7}


def _ci(mean: float, lo: float, hi: float, n: int = 9) -> dict[str, float]:
    return {"mean": mean, "lo": lo, "hi": hi, "n": float(n)}


def retrieval_report() -> dict:  # type: ignore[type-arg]
    return {
        "kind": "retrieval",
        "generated_at": "2026-08-31T04:30:50+00:00",
        "git_commit": "49130d1",
        "snapshot": "benchmark-20260831-041957",
        "provenance": PROVENANCE,
        "corpus": CORPUS,
        "ground_truth": {"drafted": 0, "reviewed": 10},
        "configs": [
            {
                "name": "full_deep",
                "description": "every layer on",
                "metrics": {"n": 9.0, "hit_at_5": 1.0, "mrr": 1.0, "ndcg_at_10": 0.95},
                "metrics_ci": {
                    "n": 9,
                    "hit_at_5": _ci(1.0, 1.0, 1.0),
                    "mrr": _ci(1.0, 1.0, 1.0),
                    "ndcg_at_10": _ci(0.95, 0.91, 0.98),
                },
                "records": [
                    {
                        "question_id": "rice-straw-generated",
                        "first_relevant_rank": 1,
                        "hit_at_5": True,
                        "hit_at_10": True,
                        "retrieved": 10,
                        "degraded_stages": [],
                        "relevant_ranks": [1, 2],
                    },
                    {
                        "question_id": "almond-logistics",
                        "first_relevant_rank": None,
                        "hit_at_5": False,
                        "hit_at_10": False,
                        "retrieved": 10,
                        "degraded_stages": ["community"],
                        "relevant_ranks": [],
                    },
                ],
            },
            {
                "name": "no_graph",
                "description": "graph traversal off",
                "metrics": {"n": 9.0, "hit_at_5": 0.94, "mrr": 0.9, "ndcg_at_10": 0.92},
                "metrics_ci": {
                    "n": 9,
                    # Overlaps the baseline interval: not distinguishable.
                    "hit_at_5": _ci(0.94, 0.83, 1.00),
                    # Sits entirely below the baseline interval: a real move.
                    "mrr": _ci(0.55, 0.40, 0.70),
                    "ndcg_at_10": _ci(0.92, 0.85, 0.98),
                },
                "records": [
                    {
                        "question_id": "rice-straw-generated",
                        "first_relevant_rank": 3,
                        "hit_at_5": True,
                        "hit_at_10": True,
                        "retrieved": 10,
                        "degraded_stages": [],
                        "relevant_ranks": [3],
                    }
                ],
            },
        ],
    }


def answers_report(drafted: int = 0) -> dict:  # type: ignore[type-arg]
    return {
        "kind": "answers",
        "generated_at": "2026-08-31T04:32:33+00:00",
        "git_commit": "49130d1",
        "snapshot": "benchmark-20260831-041957",
        "provenance": PROVENANCE,
        "models": {"answer": "gemini-2.5-flash"},
        "config": {"compression": False},
        "corpus": CORPUS,
        "ground_truth": {"drafted": drafted, "reviewed": 10 - drafted},
        "summary": {
            "n": 10.0,
            "graded": 10.0,
            "failed": 0.0,
            "groundedness_mean": 2.0,
            "correctness_mean": 1.7,
            "prompt_tokens_before_median": 1347.0,
            "prompt_tokens_after_median": 1347.0,
        },
        "summary_ci": {
            "groundedness": _ci(2.0, 2.0, 2.0, 10),
            "correctness": _ci(1.7, 1.4, 2.0, 10),
        },
        "records": [
            {
                "question_id": "rice-straw-generated",
                "tags": ["availability"],
                "answer_text": "302,000 dry tons were generated [1] & <b>not</b> bold.",
                "source_count": 8,
                "cited_count": 2,
                "prompt_tokens_before": 1312,
                "prompt_tokens_after": 1312,
                "compression_failure_count": 0,
                "compression_dropped_count": 0,
                "degraded_stages": [],
                "grounding": {
                    "groundedness": 2,
                    "citation_accuracy": 2,
                    "completeness": 2,
                    "rationale": "Every claim is supported.",
                },
                "correctness": {"correctness": 1, "rationale": "Omits harvested acres."},
                "error": None,
            }
        ],
    }


def calibration_payload() -> dict:  # type: ignore[type-arg]
    return {
        "matched_n": 10,
        "unmatched_label_ids": ["orphan-question"],
        "dimensions": {
            "groundedness": {
                "kappa": 1.0,
                "n": 10,
                "exact_agreement": 1.0,
                "band": "almost perfect",
                "matrix": [[0, 0, 0], [0, 0, 0], [0, 0, 10]],
            },
            "correctness": {
                "kappa": 0.0,
                "n": 10,
                "exact_agreement": 0.8,
                "band": "slight",
                "matrix": [[0, 0, 0], [0, 1, 1], [0, 0, 8]],
            },
        },
    }


def _external_references(page: str) -> list[str]:
    """Anything the browser would have to fetch to render this file."""
    offenders = []
    for marker in ('src="http', "src='http", 'href="http', "href='http", "@import", "<script"):
        if marker in page:
            offenders.append(marker)
    # A stylesheet link is the other way a page reaches out.
    if "<link" in page and "stylesheet" in page:
        offenders.append("<link rel=stylesheet>")
    return offenders


def test_a_retrieval_run_renders_to_one_self_contained_page() -> None:
    page = render_html(retrieval_report())

    assert page.startswith("<!DOCTYPE html>")
    assert "<style>" in page
    assert _external_references(page) == []
    assert "full_deep" in page
    assert "no_graph" in page


def test_an_answers_run_renders_to_one_self_contained_page() -> None:
    page = render_html(answers_report())

    assert page.startswith("<!DOCTYPE html>")
    assert _external_references(page) == []
    assert "rice-straw-generated" in page


def test_the_page_surfaces_the_provenance_receipt() -> None:
    """A number without its receipt is the thing this repo keeps refusing to publish.

    The payloads gained a `provenance` block so a report says which models
    produced it. A view for someone who cannot run the command is exactly
    where dropping that would do the most damage, because they have no way
    to go and look.
    """
    page = render_html(retrieval_report())

    assert "gemini-embedding-001@1536" in page
    assert "google:gemini-2.5-flash" in page
    assert "11194722ed59" in page
    assert "benchmark-20260831-041957" in page
    assert "49130d1" in page


def test_per_question_rows_are_marked_hit_or_miss() -> None:
    page = render_html(retrieval_report())

    # Matched as markup, not as a class name. Every class in this file also
    # appears in the inlined stylesheet, so a bare substring check would pass
    # on a page with no marked rows at all.
    assert "<tr class='row--hit'>" in page
    assert "<tr class='row--miss'>" in page


def test_a_cell_whose_interval_overlaps_the_baseline_is_marked_as_noise() -> None:
    """Overlapping intervals are the most common way these tables get misread.

    `no_graph` scores 0.94 against a baseline 1.00 on hit@5, and the
    intervals overlap, so the difference is not distinguishable at this
    sample size. Its mrr interval sits clear of the baseline's, so that one
    is a real move. The page has to tell those two apart or it invites the
    reader to rank configurations by decimal places.
    """
    page = render_html(retrieval_report())

    assert "<td class='num cell--overlaps'>0.94 [0.83, 1.00]</td>" in page
    assert "<td class='num cell--distinct'>0.55 [0.40, 0.70]</td>" in page

    # The baseline compares against nothing, so a report with only the
    # baseline carries no comparison marks at all.
    solo = retrieval_report()
    solo["configs"] = solo["configs"][:1]
    solo_page = render_html(solo)
    assert "cell--overlaps'" not in solo_page.split("</style>", 1)[1]
    assert "cell--distinct'" not in solo_page.split("</style>", 1)[1]


def test_a_small_sample_carries_its_warning() -> None:
    page = render_html(retrieval_report())

    assert "small sample" in page.lower()


def test_drafted_ground_truth_carries_its_warning_and_a_clean_run_does_not() -> None:
    drafted = render_html(answers_report(drafted=4))
    reviewed = render_html(answers_report(drafted=0))

    assert "model-drafted" in drafted
    assert "model-drafted" not in reviewed


def test_the_calibration_section_appears_only_when_calibration_exists() -> None:
    without = render_html(answers_report())
    with_calibration = render_html(answers_report(), calibration=calibration_payload())

    assert "Judge calibration" not in without
    assert "Judge calibration" in with_calibration
    assert "almost perfect" in with_calibration
    assert "orphan-question" in with_calibration


def test_model_text_is_escaped_rather_than_rendered() -> None:
    """Answer text and judge rationales are model output, so they are data.

    A model that emits `<b>` gets it shown, not applied. This is the one
    place in the renderer where untrusted text meets markup.
    """
    page = render_html(answers_report())

    assert "&lt;b&gt;not&lt;/b&gt;" in page
    assert "<b>not</b>" not in page
    assert "&amp;" in page


def test_the_cli_writes_the_page_next_to_the_report(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from sci_rag.cli.main import app

    run_dir = tmp_path / "20260831-043050-retrieval-ablation"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(json.dumps(retrieval_report()), encoding="utf-8")

    result = CliRunner().invoke(app, ["eval", "html", str(run_dir)])

    assert result.exit_code == 0, result.output
    written = run_dir / "report.html"
    assert written.exists()
    assert _external_references(written.read_text(encoding="utf-8")) == []


def test_the_cli_picks_up_calibration_sitting_beside_the_report(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from sci_rag.cli.main import app

    run_dir = tmp_path / "20260831-043233-answers"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(json.dumps(answers_report()), encoding="utf-8")
    (run_dir / "calibration.json").write_text(json.dumps(calibration_payload()), encoding="utf-8")

    result = CliRunner().invoke(
        app, ["eval", "html", str(run_dir), "--output", str(tmp_path / "o.html")]
    )

    assert result.exit_code == 0, result.output
    assert "Judge calibration" in (tmp_path / "o.html").read_text(encoding="utf-8")


def test_a_missing_report_fails_with_a_readable_message(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from sci_rag.cli.main import app

    result = CliRunner().invoke(app, ["eval", "html", str(tmp_path / "nope")])

    assert result.exit_code == 1
    assert "no report found" in result.output
