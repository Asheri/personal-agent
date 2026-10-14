"""The report diff engine: what changed between two eval runs, and is it real.

Fixtures are synthetic payload dicts in the exact shape retrieval_payload
and answers_payload write, so these tests also pin the on-disk report
contract that `sci-rag eval diff` consumes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sci_rag.cli.main import app
from sci_rag.evals.diff import DiffError, diff_markdown, diff_reports


def retrieval_payload_fixture(name: str, ranks: dict[str, int | None]) -> dict:
    records = [
        {
            "question_id": qid,
            "first_relevant_rank": rank,
            "hit_at_5": rank is not None and rank <= 5,
            "hit_at_10": rank is not None and rank <= 10,
            "retrieved": 10,
            "degraded_stages": [],
            "relevant_ranks": [rank] if rank is not None else [],
        }
        for qid, rank in ranks.items()
    ]
    return {
        "kind": "retrieval",
        "generated_at": "2026-08-27T00:00:00+00:00",
        "git_commit": name,
        "corpus": {"documents": 5, "chunks": 34},
        "configs": [
            {
                "name": "full_deep",
                "description": "All five layers",
                "metrics": {},
                "records": records,
            }
        ],
    }


def answers_payload_fixture(name: str, scores: list[int], tokens: list[int]) -> dict:
    return {
        "kind": "answers",
        "generated_at": "2026-08-27T00:00:00+00:00",
        "git_commit": name,
        "records": [
            {
                "question_id": f"q{index}",
                "grounding": {
                    "groundedness": score,
                    "citation_accuracy": score,
                    "completeness": score,
                },
                "correctness": {"correctness": score},
                "prompt_tokens_after": token_count,
            }
            for index, (score, token_count) in enumerate(zip(scores, tokens, strict=True))
        ],
    }


class TestDiffRetrieval:
    def test_per_question_changes_classified(self) -> None:
        a = retrieval_payload_fixture("aaa", {"q1": 3, "q2": 1, "q3": None, "q4": 2, "q5": None})
        b = retrieval_payload_fixture("bbb", {"q1": 1, "q2": 2, "q3": 4, "q4": None, "q5": None})
        diff = diff_reports(a, b)
        config = diff.configs[0]
        changes = {d.question_id: d.change for d in config.question_deltas}
        assert changes == {
            "q1": "improved",
            "q2": "regressed",
            "q3": "appeared",
            "q4": "disappeared",
            "q5": "still_missing",
        }

    def test_metric_deltas_have_paired_significance(self) -> None:
        a = retrieval_payload_fixture("aaa", {f"q{i}": None for i in range(12)})
        b = retrieval_payload_fixture("bbb", {f"q{i}": 1 for i in range(12)})
        diff = diff_reports(a, b)
        hit5 = diff.configs[0].metric_deltas["hit_at_5"]
        assert hit5["delta"] == pytest.approx(1.0)
        assert hit5["p_value"] < 0.05

    def test_identical_reports_show_zero_delta(self) -> None:
        a = retrieval_payload_fixture("aaa", {"q1": 1, "q2": 2})
        diff = diff_reports(a, json.loads(json.dumps(a)))
        hit5 = diff.configs[0].metric_deltas["hit_at_5"]
        assert hit5["delta"] == pytest.approx(0.0)

    def test_question_sets_intersect_for_metrics(self) -> None:
        a = retrieval_payload_fixture("aaa", {"q1": 1, "q2": 2, "only_a": 1})
        b = retrieval_payload_fixture("bbb", {"q1": 1, "q2": 1, "only_b": 1})
        diff = diff_reports(a, b)
        config = diff.configs[0]
        assert config.common_n == 2
        ids = {d.question_id for d in config.question_deltas}
        assert {"only_a", "only_b"} <= ids

    def test_kind_mismatch_rejected(self) -> None:
        a = retrieval_payload_fixture("aaa", {"q1": 1})
        b = dict(retrieval_payload_fixture("bbb", {"q1": 1}), kind="answers")
        with pytest.raises(DiffError):
            diff_reports(a, b)

    def test_no_common_config_rejected(self) -> None:
        a = retrieval_payload_fixture("aaa", {"q1": 1})
        b = retrieval_payload_fixture("bbb", {"q1": 1})
        b["configs"][0]["name"] = "other_config"
        with pytest.raises(DiffError):
            diff_reports(a, b)

    def test_markdown_renders_tables(self) -> None:
        a = retrieval_payload_fixture("aaa", {"q1": 3, "q2": None})
        b = retrieval_payload_fixture("bbb", {"q1": 1, "q2": 2})
        diff = diff_reports(a, b)
        md = diff_markdown(diff)
        assert "full_deep" in md
        assert "improved" in md and "appeared" in md
        assert "hit_at_5" in md
        assert "aaa" in md and "bbb" in md


def test_answers_diff_pairs_judge_dimensions_and_prompt_tokens() -> None:
    baseline = answers_payload_fixture("aaa", [2, 2, 1], [1000, 800, 900])
    compressed = answers_payload_fixture("bbb", [2, 2, 1], [400, 300, 350])

    diff = diff_reports(baseline, compressed)

    metrics = diff.configs[0].metric_deltas
    assert metrics["groundedness"]["delta"] == 0.0
    assert metrics["correctness"]["delta"] == 0.0
    assert metrics["prompt_tokens"]["delta"] == pytest.approx(-550.0)
    assert "prompt_tokens" in diff_markdown(diff)


class TestDiffCli:
    def test_cli_diffs_two_report_files(self, tmp_path: Path) -> None:
        a_path = tmp_path / "a" / "report.json"
        b_path = tmp_path / "b" / "report.json"
        a_path.parent.mkdir()
        b_path.parent.mkdir()
        a_path.write_text(json.dumps(retrieval_payload_fixture("aaa", {"q1": 3, "q2": None})))
        b_path.write_text(json.dumps(retrieval_payload_fixture("bbb", {"q1": 1, "q2": 2})))
        runner = CliRunner()
        result = runner.invoke(app, ["eval", "diff", str(a_path), str(b_path)])
        assert result.exit_code == 0, result.output
        assert "improved" in result.output

    def test_cli_accepts_run_directories(self, tmp_path: Path) -> None:
        a_dir = tmp_path / "run-a"
        b_dir = tmp_path / "run-b"
        a_dir.mkdir()
        b_dir.mkdir()
        (a_dir / "report.json").write_text(json.dumps(retrieval_payload_fixture("aaa", {"q1": 2})))
        (b_dir / "report.json").write_text(json.dumps(retrieval_payload_fixture("bbb", {"q1": 1})))
        runner = CliRunner()
        result = runner.invoke(app, ["eval", "diff", str(a_dir), str(b_dir)])
        assert result.exit_code == 0, result.output

    def test_cli_missing_file_friendly_error(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app, ["eval", "diff", str(tmp_path / "nope.json"), str(tmp_path / "nope2.json")]
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "no report" in result.output.lower()

    def test_cli_writes_output_file(self, tmp_path: Path) -> None:
        a_path = tmp_path / "a.json"
        b_path = tmp_path / "b.json"
        a_path.write_text(json.dumps(retrieval_payload_fixture("aaa", {"q1": 2})))
        b_path.write_text(json.dumps(retrieval_payload_fixture("bbb", {"q1": 1})))
        out = tmp_path / "diff.md"
        runner = CliRunner()
        result = runner.invoke(
            app, ["eval", "diff", str(a_path), str(b_path), "--output", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert out.exists() and "hit_at_5" in out.read_text()
