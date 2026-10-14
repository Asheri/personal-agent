"""Diff two eval reports: what changed, per question, and is it real.

This closes the improvement loop the methodology promises: run an eval,
change one thing, run it again, and let `sci-rag eval diff` say which
questions moved and whether the metric deltas clear paired-bootstrap
significance, instead of eyeballing two markdown tables.

Works on the ``report.json`` payloads that every eval run writes.
Retrieval reports diff per-question ranks and all four metrics; answers
reports diff the judge's dimension means over the common questions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sci_rag.evals.retrieval_eval import ndcg_at_k
from sci_rag.evals.stats import paired_bootstrap_test


class DiffError(RuntimeError):
    """The two reports cannot be meaningfully compared."""


@dataclass
class QuestionDelta:
    question_id: str
    rank_a: int | None
    rank_b: int | None
    change: str  # improved | regressed | unchanged | appeared | disappeared | still_missing


@dataclass
class ConfigDiff:
    name: str
    common_n: int
    metric_deltas: dict[str, dict[str, float]]
    question_deltas: list[QuestionDelta] = field(default_factory=list)


@dataclass
class ReportDiff:
    kind: str
    label_a: str
    label_b: str
    configs: list[ConfigDiff] = field(default_factory=list)


def load_report(path: Path) -> dict[str, Any]:
    """Accept a report.json path or a run directory containing one."""
    if path.is_dir():
        path = path / "report.json"
    if not path.exists():
        raise DiffError(f"no report found at {path} (expected a report.json or a run directory)")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DiffError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "kind" not in payload:
        raise DiffError(f"{path} does not look like an eval report (missing 'kind')")
    return payload


def _label(payload: dict[str, Any]) -> str:
    commit = payload.get("git_commit") or "unknown-commit"
    stamp = str(payload.get("generated_at") or "")[:19]
    return f"{commit} ({stamp})" if stamp else str(commit)


def _classify(rank_a: int | None, rank_b: int | None) -> str:
    if rank_a is None and rank_b is None:
        return "still_missing"
    if rank_a is None:
        return "appeared"
    if rank_b is None:
        return "disappeared"
    if rank_b < rank_a:
        return "improved"
    if rank_b > rank_a:
        return "regressed"
    return "unchanged"


def _record_values(record: dict[str, Any]) -> dict[str, float]:
    rank = record.get("first_relevant_rank")
    relevant_ranks = record.get("relevant_ranks") or ([rank] if rank else [])
    return {
        "hit_at_5": 1.0 if rank is not None and rank <= 5 else 0.0,
        "hit_at_10": 1.0 if rank is not None and rank <= 10 else 0.0,
        "mrr": 1.0 / rank if rank else 0.0,
        "ndcg_at_10": ndcg_at_k(list(relevant_ranks), k=10),
    }


def _diff_config(name: str, records_a: list[dict], records_b: list[dict]) -> ConfigDiff:
    by_id_a = {r["question_id"]: r for r in records_a}
    by_id_b = {r["question_id"]: r for r in records_b}
    common = [qid for qid in by_id_a if qid in by_id_b]

    question_deltas = []
    for qid in sorted(set(by_id_a) | set(by_id_b)):
        in_a, in_b = qid in by_id_a, qid in by_id_b
        rank_a = by_id_a[qid].get("first_relevant_rank") if in_a else None
        rank_b = by_id_b[qid].get("first_relevant_rank") if in_b else None
        if in_a and in_b:
            change = _classify(rank_a, rank_b)
        else:
            change = "only_in_a" if in_a else "only_in_b"
        question_deltas.append(
            QuestionDelta(question_id=qid, rank_a=rank_a, rank_b=rank_b, change=change)
        )

    metric_deltas: dict[str, dict[str, float]] = {}
    if common:
        values_a = [_record_values(by_id_a[qid]) for qid in common]
        values_b = [_record_values(by_id_b[qid]) for qid in common]
        for metric in ("hit_at_5", "hit_at_10", "mrr", "ndcg_at_10"):
            comparison = paired_bootstrap_test(
                [v[metric] for v in values_a], [v[metric] for v in values_b]
            )
            metric_deltas[metric] = comparison.as_dict()

    return ConfigDiff(
        name=name,
        common_n=len(common),
        metric_deltas=metric_deltas,
        question_deltas=question_deltas,
    )


def _diff_answers(a: dict[str, Any], b: dict[str, Any]) -> ReportDiff:
    """Answers mode: paired deltas on judge dimensions over common questions."""

    def scores(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for record in payload.get("records", []):
            grades: dict[str, float] = {}
            grounding = record.get("grounding")
            if isinstance(grounding, dict):
                for dim in ("groundedness", "citation_accuracy", "completeness"):
                    if isinstance(grounding.get(dim), int | float):
                        grades[dim] = float(grounding[dim])
            correctness = record.get("correctness")
            if isinstance(correctness, dict) and isinstance(
                correctness.get("correctness"), int | float
            ):
                grades["correctness"] = float(correctness["correctness"])
            prompt_tokens = record.get("prompt_tokens_after")
            if isinstance(prompt_tokens, int | float) and prompt_tokens > 0:
                grades["prompt_tokens"] = float(prompt_tokens)
            if grades:
                out[record["question_id"]] = grades
        return out

    scores_a, scores_b = scores(a), scores(b)
    common = sorted(set(scores_a) & set(scores_b))
    metric_deltas: dict[str, dict[str, float]] = {}
    for dim in (
        "groundedness",
        "citation_accuracy",
        "completeness",
        "correctness",
        "prompt_tokens",
    ):
        pairs = [
            (scores_a[qid][dim], scores_b[qid][dim])
            for qid in common
            if dim in scores_a[qid] and dim in scores_b[qid]
        ]
        if pairs:
            comparison = paired_bootstrap_test([p[0] for p in pairs], [p[1] for p in pairs])
            metric_deltas[dim] = comparison.as_dict()
    config = ConfigDiff(name="answers", common_n=len(common), metric_deltas=metric_deltas)
    return ReportDiff(kind="answers", label_a=_label(a), label_b=_label(b), configs=[config])


def diff_reports(a: dict[str, Any], b: dict[str, Any], *, config: str | None = None) -> ReportDiff:
    kind_a, kind_b = a.get("kind"), b.get("kind")
    if kind_a != kind_b:
        raise DiffError(f"cannot diff a {kind_a!r} report against a {kind_b!r} report")
    if kind_a == "answers":
        return _diff_answers(a, b)

    configs_a = {c["name"]: c for c in a.get("configs", [])}
    configs_b = {c["name"]: c for c in b.get("configs", [])}
    names = [n for n in configs_a if n in configs_b]
    if config is not None:
        if config not in names:
            raise DiffError(
                f"config {config!r} is not present in both reports "
                f"(A has {sorted(configs_a)}, B has {sorted(configs_b)})"
            )
        names = [config]
    if not names:
        raise DiffError(
            f"no config appears in both reports "
            f"(A has {sorted(configs_a)}, B has {sorted(configs_b)})"
        )
    diffs = [
        _diff_config(name, configs_a[name]["records"], configs_b[name]["records"]) for name in names
    ]
    return ReportDiff(kind=str(kind_a), label_a=_label(a), label_b=_label(b), configs=diffs)


_ARROWS = {
    "improved": "better",
    "appeared": "better",
    "regressed": "worse",
    "disappeared": "worse",
}


def diff_markdown(diff: ReportDiff) -> str:
    lines = [
        "# Eval diff",
        "",
        f"A: {diff.label_a}",
        f"B: {diff.label_b}",
        "",
        "Deltas are B minus A over the questions common to both runs;",
        "p is a paired-bootstrap two-sided tail probability.",
    ]
    for config in diff.configs:
        lines += ["", f"## {config.name} (paired n={config.common_n})", ""]
        if config.metric_deltas:
            lines += [
                "| Metric | delta (B-A) | 95% CI | p |",
                "|--------|------------:|--------|--:|",
            ]
            for metric, d in config.metric_deltas.items():
                lines.append(
                    f"| {metric} | {d['delta']:+.3f} | [{d['lo']:+.3f}, {d['hi']:+.3f}] "
                    f"| {d['p_value']:.3f} |"
                )
        else:
            lines.append("No common questions; metric deltas unavailable.")
        moved = [q for q in config.question_deltas if q.change not in ("unchanged",)]
        if moved:
            lines += [
                "",
                "| Question | rank A | rank B | change |",
                "|----------|-------:|-------:|--------|",
            ]
            for q in moved:
                note = _ARROWS.get(q.change, "")
                change = f"{q.change} ({note})" if note else q.change
                lines.append(
                    f"| {q.question_id} | {q.rank_a if q.rank_a else '-'} "
                    f"| {q.rank_b if q.rank_b else '-'} | {change} |"
                )
    lines.append("")
    return "\n".join(lines)
