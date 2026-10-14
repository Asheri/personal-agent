"""Judge calibration: Cohen's kappa between human labels and judge scores.

Kappa fixtures are hand-computed. The parser tests pin the labels.jsonl
contract (question_id plus 0-2 integer dimension scores) with friendly,
line-numbered errors, because label files are hand-written by humans.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sci_rag.cli.main import app
from sci_rag.evals.calibration import (
    CalibrationError,
    calibrate,
    calibration_markdown,
    cohens_kappa,
    judge_scores_from_report,
    parse_labels,
)


class TestCohensKappa:
    def test_perfect_agreement_is_one(self) -> None:
        pairs = [(0, 0), (1, 1), (2, 2), (1, 1), (0, 0), (2, 2)]
        assert cohens_kappa(pairs) == pytest.approx(1.0)

    def test_hand_computed_value(self) -> None:
        # Raters agree on 8 of 10 (po = 0.8). Both marginals are 7x score-1
        # and 3x score-0, so pe = 0.7*0.7 + 0.3*0.3 = 0.58 and
        # kappa = (0.8 - 0.58) / 0.42 = 0.5238...
        pairs = [(1, 1)] * 6 + [(0, 0)] * 2 + [(0, 1)] * 1 + [(1, 0)] * 1
        assert cohens_kappa(pairs) == pytest.approx((0.8 - 0.58) / 0.42)

    def test_constant_raters_in_full_agreement(self) -> None:
        # Both raters always say 2: chance agreement is total; convention 1.0.
        assert cohens_kappa([(2, 2)] * 8) == pytest.approx(1.0)

    def test_no_agreement_beyond_chance_is_zero_or_less(self) -> None:
        pairs = [(0, 2), (2, 0), (0, 2), (2, 0)]
        assert cohens_kappa(pairs) <= 0.0

    def test_empty_pairs_rejected(self) -> None:
        with pytest.raises(ValueError):
            cohens_kappa([])


class TestParseLabels:
    def test_parses_valid_labels(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        path.write_text(
            json.dumps({"question_id": "q1", "groundedness": 2, "correctness": 1})
            + "\n"
            + json.dumps({"question_id": "q2", "groundedness": 0})
            + "\n"
        )
        labels = parse_labels(path)
        assert labels == {
            "q1": {"groundedness": 2, "correctness": 1},
            "q2": {"groundedness": 0},
        }

    def test_score_out_of_range_rejected_with_line_number(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        path.write_text(json.dumps({"question_id": "q1", "groundedness": 5}) + "\n")
        with pytest.raises(CalibrationError, match="line 1"):
            parse_labels(path)

    def test_missing_question_id_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        path.write_text(json.dumps({"groundedness": 1}) + "\n")
        with pytest.raises(CalibrationError, match="question_id"):
            parse_labels(path)

    def test_comment_and_blank_lines_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        path.write_text(
            "# non-expert seed labels\n\n"
            + json.dumps({"question_id": "q1", "completeness": 2})
            + "\n"
        )
        assert parse_labels(path) == {"q1": {"completeness": 2}}

    def test_duplicate_question_id_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        row = json.dumps({"question_id": "q1", "groundedness": 1})
        path.write_text(row + "\n" + row + "\n")
        with pytest.raises(CalibrationError, match="duplicate"):
            parse_labels(path)


def answers_report_fixture(scores: dict[str, dict[str, int]]) -> dict:
    records = []
    for qid, dims in scores.items():
        records.append(
            {
                "question_id": qid,
                "tags": [],
                "grounding": {
                    "groundedness": dims.get("groundedness", 2),
                    "citation_accuracy": dims.get("citation_accuracy", 2),
                    "completeness": dims.get("completeness", 2),
                    "rationale": "",
                },
                "correctness": (
                    {"correctness": dims["correctness"], "rationale": ""}
                    if "correctness" in dims
                    else None
                ),
                "error": None,
            }
        )
    return {"kind": "answers", "git_commit": "abc", "records": records}


class TestCalibrate:
    def test_kappa_per_dimension_and_agreement_matrix(self) -> None:
        report = answers_report_fixture(
            {f"q{i}": {"groundedness": 2, "correctness": 1} for i in range(6)}
        )
        judge = judge_scores_from_report(report)
        human = {f"q{i}": {"groundedness": 2, "correctness": 1} for i in range(6)}
        result = calibrate(human, judge)
        grounded = result.dimensions["groundedness"]
        assert grounded.kappa == pytest.approx(1.0)
        assert grounded.n == 6
        assert grounded.matrix[2][2] == 6
        assert result.dimensions["correctness"].kappa == pytest.approx(1.0)

    def test_disagreements_lower_kappa_and_fill_matrix(self) -> None:
        report = answers_report_fixture(
            {"q1": {"groundedness": 2}, "q2": {"groundedness": 2}, "q3": {"groundedness": 0}}
        )
        judge = judge_scores_from_report(report)
        human = {
            "q1": {"groundedness": 2},
            "q2": {"groundedness": 0},
            "q3": {"groundedness": 0},
        }
        result = calibrate(human, judge)
        grounded = result.dimensions["groundedness"]
        assert grounded.kappa < 1.0
        assert grounded.matrix[0][2] == 1  # human said 0, judge said 2
        assert grounded.exact_agreement == pytest.approx(2 / 3)

    def test_unmatched_question_ids_reported_not_fatal(self) -> None:
        report = answers_report_fixture({"q1": {"groundedness": 2}})
        judge = judge_scores_from_report(report)
        human = {"q1": {"groundedness": 2}, "zz": {"groundedness": 1}}
        result = calibrate(human, judge)
        assert result.unmatched_label_ids == ["zz"]
        assert result.dimensions["groundedness"].n == 1

    def test_no_overlap_rejected(self) -> None:
        report = answers_report_fixture({"q1": {"groundedness": 2}})
        judge = judge_scores_from_report(report)
        with pytest.raises(CalibrationError):
            calibrate({"zz": {"groundedness": 1}}, judge)

    def test_markdown_renders_kappa_table(self) -> None:
        report = answers_report_fixture({f"q{i}": {"groundedness": 2} for i in range(4)})
        judge = judge_scores_from_report(report)
        human = {f"q{i}": {"groundedness": 2} for i in range(4)}
        md = calibration_markdown(calibrate(human, judge))
        assert "kappa" in md.lower()
        assert "groundedness" in md
        assert "n=4" in md or "| 4 |" in md


class TestCalibrateCli:
    def test_cli_end_to_end(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        report_path.write_text(
            json.dumps(answers_report_fixture({f"q{i}": {"groundedness": 2} for i in range(5)}))
        )
        labels_path = tmp_path / "labels.jsonl"
        labels_path.write_text(
            "\n".join(json.dumps({"question_id": f"q{i}", "groundedness": 2}) for i in range(5))
        )
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["eval", "calibrate", "--labels", str(labels_path), "--report", str(report_path)],
        )
        assert result.exit_code == 0, result.output
        assert "groundedness" in result.output

    def test_cli_appends_to_report_markdown(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(answers_report_fixture({"q1": {"groundedness": 2}})))
        md_path = tmp_path / "report.md"
        md_path.write_text("# Answer evaluation (blind judge)\n")
        labels_path = tmp_path / "labels.jsonl"
        labels_path.write_text(json.dumps({"question_id": "q1", "groundedness": 2}))
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["eval", "calibrate", "--labels", str(labels_path), "--report", str(report_path)],
        )
        assert result.exit_code == 0, result.output
        assert "Judge calibration" in md_path.read_text()

    def test_cli_missing_labels_friendly(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["eval", "calibrate", "--labels", str(tmp_path / "nope.jsonl")])
        assert result.exit_code != 0
