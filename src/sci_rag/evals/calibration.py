"""Judge calibration: how well does the LLM judge agree with a human?

A judged-answers table is only citable if the judge itself has been
checked against human judgment. This module implements that check as a
repeatable workflow, not a one-off study: collect human labels for a set
of judged answers (``labels.jsonl``), run ``sci-rag eval calibrate``, and
report Cohen's kappa per dimension next to the judge's numbers.

The labels file is one JSON object per line, hand-written by a human who
read the answers WITHOUT looking at the judge's scores first:

    {"question_id": "rice-straw-ash", "groundedness": 2, "citation_accuracy": 2,
     "completeness": 1, "correctness": 2}

Dimensions may be omitted per row; ``#`` comment lines and blank lines
are skipped. Scores use the same 0-2 rubric the judge uses (see
``domain/prompts/judge_grounding.md``).

Kappa is reported as measured, with the standard Landis-Koch adjective
purely as a reading aid. No target value is asserted anywhere: a low
kappa is a finding about the judge, not a failure of the workflow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DIMENSIONS = ("groundedness", "citation_accuracy", "completeness", "correctness")
_SCORES = (0, 1, 2)


class CalibrationError(RuntimeError):
    """The labels or report cannot be used for a calibration."""


def cohens_kappa(pairs: list[tuple[int, int]]) -> float:
    """Unweighted Cohen's kappa for two raters on categorical scores.

    When expected chance agreement is total (both raters constant), the
    formula degenerates; by convention that returns 1.0 under full
    observed agreement and 0.0 otherwise.
    """
    if not pairs:
        raise ValueError("cohens_kappa needs at least one pair")
    n = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / n
    categories = sorted({v for pair in pairs for v in pair})
    expected = 0.0
    for category in categories:
        p_a = sum(1 for a, _ in pairs if a == category) / n
        p_b = sum(1 for _, b in pairs if b == category) / n
        expected += p_a * p_b
    if 1.0 - expected < 1e-12:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def landis_koch(kappa: float) -> str:
    """The standard qualitative band, as a reading aid only."""
    if kappa < 0:
        return "poor"
    if kappa < 0.2:
        return "slight"
    if kappa < 0.4:
        return "fair"
    if kappa < 0.6:
        return "moderate"
    if kappa < 0.8:
        return "substantial"
    return "almost perfect"


def parse_labels(path: Path) -> dict[str, dict[str, int]]:
    """Parse labels.jsonl with line-numbered errors for hand-edited files."""
    if not path.exists():
        raise CalibrationError(f"labels file not found: {path}")
    labels: dict[str, dict[str, int]] = {}
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CalibrationError(f"{path} line {line_no}: not valid JSON ({exc})") from exc
        if not isinstance(row, dict) or not isinstance(row.get("question_id"), str):
            raise CalibrationError(f"{path} line {line_no}: each row needs a 'question_id' string")
        qid = row["question_id"]
        if qid in labels:
            raise CalibrationError(f"{path} line {line_no}: duplicate question_id {qid!r}")
        scores: dict[str, int] = {}
        for dim in DIMENSIONS:
            if dim not in row:
                continue
            value = row[dim]
            if not isinstance(value, int) or value not in _SCORES:
                raise CalibrationError(
                    f"{path} line {line_no}: {dim} must be an integer 0, 1, or 2 (got {value!r})"
                )
            scores[dim] = value
        if not scores:
            raise CalibrationError(
                f"{path} line {line_no}: no dimension scores "
                f"(expected any of {', '.join(DIMENSIONS)})"
            )
        labels[qid] = scores
    if not labels:
        raise CalibrationError(f"{path} contains no labels")
    return labels


def judge_scores_from_report(payload: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Pull the judge's per-question dimension scores out of an answers report."""
    if payload.get("kind") not in (None, "answers"):
        raise CalibrationError(f"expected an answers report, got kind={payload.get('kind')!r}")
    scores: dict[str, dict[str, int]] = {}
    for record in payload.get("records", []):
        qid = record.get("question_id")
        if not isinstance(qid, str):
            continue
        row: dict[str, int] = {}
        grounding = record.get("grounding")
        if isinstance(grounding, dict):
            for dim in ("groundedness", "citation_accuracy", "completeness"):
                if isinstance(grounding.get(dim), int):
                    row[dim] = grounding[dim]
        correctness = record.get("correctness")
        if isinstance(correctness, dict) and isinstance(correctness.get("correctness"), int):
            row["correctness"] = correctness["correctness"]
        if row:
            scores[qid] = row
    return scores


@dataclass
class DimensionCalibration:
    kappa: float
    n: int
    exact_agreement: float
    # matrix[human_score][judge_score] = count
    matrix: list[list[int]]

    @property
    def band(self) -> str:
        return landis_koch(self.kappa)


@dataclass
class CalibrationResult:
    dimensions: dict[str, DimensionCalibration]
    matched_n: int
    unmatched_label_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "matched_n": self.matched_n,
            "unmatched_label_ids": self.unmatched_label_ids,
            "dimensions": {
                name: {
                    "kappa": d.kappa,
                    "n": d.n,
                    "exact_agreement": d.exact_agreement,
                    "band": d.band,
                    "matrix": d.matrix,
                }
                for name, d in self.dimensions.items()
            },
        }


def calibrate(
    human: dict[str, dict[str, int]], judge: dict[str, dict[str, int]]
) -> CalibrationResult:
    matched = sorted(set(human) & set(judge))
    unmatched = sorted(set(human) - set(judge))
    if not matched:
        raise CalibrationError(
            "no labeled question_id matches the report "
            f"(labels: {sorted(human)[:5]}..., report: {sorted(judge)[:5]}...)"
        )
    dimensions: dict[str, DimensionCalibration] = {}
    for dim in DIMENSIONS:
        pairs = [
            (human[qid][dim], judge[qid][dim])
            for qid in matched
            if dim in human[qid] and dim in judge[qid]
        ]
        if not pairs:
            continue
        matrix = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        for h, j in pairs:
            matrix[h][j] += 1
        dimensions[dim] = DimensionCalibration(
            kappa=cohens_kappa(pairs),
            n=len(pairs),
            exact_agreement=sum(1 for h, j in pairs if h == j) / len(pairs),
            matrix=matrix,
        )
    if not dimensions:
        raise CalibrationError("matched questions share no dimension scores with the report")
    return CalibrationResult(
        dimensions=dimensions, matched_n=len(matched), unmatched_label_ids=unmatched
    )


def calibration_markdown(result: CalibrationResult) -> str:
    lines = [
        "## Judge calibration (human labels vs judge)",
        "",
        f"Matched questions: {result.matched_n}."
        + (
            f" Unmatched label ids ignored: {', '.join(result.unmatched_label_ids)}."
            if result.unmatched_label_ids
            else ""
        ),
        "",
        "| Dimension | Cohen's kappa | exact agreement | n | reading |",
        "|-----------|--------------:|----------------:|--:|---------|",
    ]
    for name, d in result.dimensions.items():
        lines.append(f"| {name} | {d.kappa:.2f} | {d.exact_agreement:.2f} | {d.n} | {d.band} |")
    lines += [
        "",
        "Kappa is chance-corrected agreement; the reading column is the",
        "Landis-Koch adjective, a convention rather than a target. Agreement",
        "matrices (rows: human score 0-2, columns: judge score 0-2):",
        "",
    ]
    for name, d in result.dimensions.items():
        lines.append(f"### {name} (n={d.n})")
        lines.append("")
        lines.append("| human \\ judge | 0 | 1 | 2 |")
        lines.append("|---------------|--:|--:|--:|")
        for score in _SCORES:
            row = d.matrix[score]
            lines.append(f"| {score} | {row[0]} | {row[1]} | {row[2]} |")
        lines.append("")
    return "\n".join(lines)
