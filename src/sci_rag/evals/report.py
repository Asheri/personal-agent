"""Evaluation artifacts: numbers you can trust later.

Every run writes a JSON payload (for machines and regression diffs) and a
Markdown report (for humans) into ``eval_results/``, stamped with a corpus
fingerprint (document/chunk/graph counts, embedding versions, latest
ingestion time) and the git commit when available. An eval number without
its corpus fingerprint is just a rumor.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document, KgCommunity, KgEntity, KgRelationship
from sci_rag.evals.answer_eval import AnswerEvalRecord, summarize_answer_records
from sci_rag.evals.retrieval_eval import RetrievalEvalResult
from sci_rag.evals.seeds import DRAFTED_TAG, SeedQuestion
from sci_rag.evals.stats import SMALL_N, bootstrap_ci, format_ci


def small_n_warning(n: int) -> list[str]:
    if 0 < n < SMALL_N:
        return [
            "",
            f"Warning: n={n} questions is a small sample. The 95% intervals are",
            "wide, and metric differences inside overlapping intervals are noise,",
            "not findings.",
        ]
    return []


def drafted_questions_warning(drafted: int, total: int) -> list[str]:
    """Say out loud when the ground truth under a report is model-drafted.

    A metric is only as trustworthy as the questions it was scored against.
    `sci-rag draft questions` tags every row it writes `drafted`, and the tag
    survives until a domain expert reads the question and deletes it. While
    any tag remains, the report has to carry the caveat next to the number,
    because a table pasted into a slide deck travels without its provenance.
    """
    if drafted <= 0:
        return []
    return [
        "",
        f"Warning: {drafted} of {total} seed questions are model-drafted and have not",
        "been reviewed by a domain expert, so every metric here is provisional. Check",
        "each one against the document it cites, then remove its `drafted` tag.",
    ]


def ground_truth_counts(tag_lists: Iterable[Sequence[str]]) -> dict[str, int]:
    """The same receipt the markdown warning shows, for the JSON payload."""
    counts = {"drafted": 0, "reviewed": 0}
    for tags in tag_lists:
        counts["drafted" if DRAFTED_TAG in tags else "reviewed"] += 1
    return counts


async def corpus_fingerprint(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    async with session_factory() as session:
        counts = {}
        for label, model in (
            ("documents", Document),
            ("chunks", Chunk),
            ("entities", KgEntity),
            ("relationships", KgRelationship),
            ("communities", KgCommunity),
        ):
            counts[label] = await session.scalar(select(func.count(model.id)))
        latest = await session.scalar(select(func.max(Document.ingested_at)))
        versions = sorted(
            v
            for v in (await session.execute(select(Chunk.embedding_version).distinct())).scalars()
            if v
        )
    return {
        **counts,
        "latest_ingested_at": latest.isoformat() if latest else None,
        "embedding_versions": versions,
    }


#: The receipt a published number carries. Corpus counts are outcomes; these
#: are the inputs that produce them, and without them a reader cannot tell
#: expected model variance from a changed prompt, model, or ontology.
PROVENANCE_FIELDS = ("embedding", "models", "domain_digest", "decoding")

#: The decoding settings the evaluation paths actually send. They are constants
#: rather than settings today, and recording them says so: a later change to
#: any of them explains a metric move that would otherwise look like variance.
_DECODING = {"temperature": 0.0, "judge_temperature": 0.0, "json_mode": True}


def domain_digest(domain_dir: Path) -> str:
    """A digest over the ontology and every prompt, in a stable order.

    Editing a prompt changes every entity the extractor emits, and no count in
    the corpus fingerprint records that it happened. This does.
    """
    hasher = hashlib.sha256()
    paths = [domain_dir / "domain.yaml", *sorted((domain_dir / "prompts").glob("*.md"))]
    for path in paths:
        try:
            body = path.read_bytes()
        except OSError:
            continue
        hasher.update(path.name.encode("utf-8"))
        hasher.update(body)
    return hasher.hexdigest()


def provenance_block(settings: Any, *, domain_dir: Path | None = None) -> dict[str, Any]:
    """Everything a reader needs to explain a number that moved."""
    return {
        "embedding": f"{settings.embedding_model}@{settings.embedding_dim}",
        "models": {
            role: str(settings.model_spec_for(role)) for role in ("answer", "extraction", "judge")
        },
        "domain_digest": domain_digest(domain_dir or settings.domain_dir),
        "decoding": dict(_DECODING),
    }


def git_commit() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            or None
        )
    except Exception:
        return None


def _run_dir(base: Path, kind: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    directory = base / f"{stamp}-{kind}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_report(
    *,
    kind: str,
    payload: dict[str, Any],
    markdown: str,
    base_dir: Path = Path("eval_results"),
) -> tuple[Path, Path]:
    directory = _run_dir(base_dir, kind)
    json_path = directory / "report.json"
    md_path = directory / "report.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path


def retrieval_payload(
    results: list[RetrievalEvalResult],
    fingerprint: dict[str, Any],
    *,
    snapshot: str | None = None,
    questions: list[SeedQuestion] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The machine-readable report.

    ``questions`` is the seed set the run scored. It is optional only so an
    older caller keeps working; the CLI always passes it, and without it the
    payload cannot honestly claim anything about its ground truth, so the
    ``ground_truth`` block is omitted rather than guessed at.
    """
    payload: dict[str, Any] = {
        "kind": "retrieval",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "snapshot": snapshot,
        "provenance": provenance or {},
        "corpus": fingerprint,
    }
    if questions is not None:
        payload["ground_truth"] = ground_truth_counts([q.tags for q in questions])
    payload["configs"] = [
        {
            "name": r.config.name,
            "description": r.config.description,
            "metrics": r.metrics,
            "metrics_ci": r.metrics_with_ci,
            "records": [asdict(record) for record in r.records],
        }
        for r in results
    ]
    return payload


def retrieval_markdown(
    results: list[RetrievalEvalResult],
    fingerprint: dict[str, Any],
    *,
    questions: list[SeedQuestion] | None = None,
) -> str:
    lines = [
        "# Retrieval evaluation",
        "",
        f"Corpus: {fingerprint.get('documents')} documents, {fingerprint.get('chunks')} chunks, "
        f"{fingerprint.get('entities')} entities, {fingerprint.get('communities')} communities.",
        f"Embedding versions: {', '.join(fingerprint.get('embedding_versions', [])) or 'none'}.",
        "",
        "| Config | hit@5 | hit@10 | MRR | nDCG@10 | questions |",
        "|--------|------:|-------:|----:|--------:|----------:|",
    ]
    max_n = 0
    for result in results:
        ci = result.metrics_with_ci
        n = int(ci.get("n", 0))
        max_n = max(max_n, n)
        if n == 0:
            lines.append(f"| {result.config.name} | - | - | - | - | 0 |")
            continue
        lines.append(
            f"| {result.config.name} | {format_ci(ci['hit_at_5'])} "
            f"| {format_ci(ci['hit_at_10'])} | {format_ci(ci['mrr'])} "
            f"| {format_ci(ci['ndcg_at_10'])} | {n} |"
        )
    lines += small_n_warning(max_n)
    if questions is not None:
        counts = ground_truth_counts([q.tags for q in questions])
        lines += drafted_questions_warning(
            counts["drafted"], counts["drafted"] + counts["reviewed"]
        )
    lines += [
        "",
        "Cells are mean [95% bootstrap CI], resampled per question.",
    ]
    lines += [
        "",
        "Read this table by comparing rows against `full_deep`: a layer earns",
        "its place when removing it drops hit rate or MRR. Misses by question",
        "are in report.json.",
        "",
    ]
    misses = [
        (result.config.name, record.question_id)
        for result in results
        for record in result.records
        if record.first_relevant_rank is None
    ]
    if misses:
        lines.append("## Missed questions")
        lines.append("")
        lines += [f"- `{config}`: {qid}" for config, qid in misses]
        lines.append("")
    return "\n".join(lines)


def answer_dimension_values(records: list[AnswerEvalRecord]) -> dict[str, list[float]]:
    """Per-question judge scores by dimension, for bootstrap CIs."""
    graded = [r.grounding for r in records if r.grounding is not None]
    out = {
        "groundedness": [float(g.groundedness) for g in graded],
        "citation_accuracy": [float(g.citation_accuracy) for g in graded],
        "completeness": [float(g.completeness) for g in graded],
    }
    correct = [r.correctness for r in records if r.correctness is not None]
    if correct:
        out["correctness"] = [float(c.correctness) for c in correct]
    return out


def summarize_answers_ci(records: list[AnswerEvalRecord]) -> dict[str, Any]:
    return {
        name: bootstrap_ci(values).as_dict()
        for name, values in answer_dimension_values(records).items()
        if values
    }


def answers_payload(
    records: list[AnswerEvalRecord],
    fingerprint: dict[str, Any],
    *,
    snapshot: str | None = None,
    models: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "answers",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "snapshot": snapshot,
        "provenance": provenance or {},
        "models": models or {},
        "config": config or {},
        "corpus": fingerprint,
        "ground_truth": ground_truth_counts([record.tags for record in records]),
        "summary": summarize_answer_records(records),
        "summary_ci": summarize_answers_ci(records),
        "records": [asdict(record) for record in records],
    }


def answers_markdown(
    records: list[AnswerEvalRecord],
    fingerprint: dict[str, Any],
    *,
    models: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    summary = summarize_answer_records(records)
    lines = [
        "# Answer evaluation (blind judge)",
        "",
        f"Corpus: {fingerprint.get('documents')} documents, {fingerprint.get('chunks')} chunks.",
        "",
    ]
    if models:
        lines += [
            "Answered by `{}`; graded by `{}`.".format(
                models.get("answer", "unknown"), models.get("judge", "unknown")
            ),
            "",
        ]
    if config and "compression" in config:
        lines += [
            f"Contextual compression: `{'enabled' if config['compression'] else 'disabled'}`.",
            "",
        ]
    lines += [
        "Scores are 0 to 2 per dimension. The grounding judge never sees the",
        "reference answer; correctness is graded in a separate reference-only pass.",
        "",
        "| Metric | Mean [95% CI] |",
        "|--------|--------------:|",
    ]
    ci_summary = summarize_answers_ci(records)
    for key in (
        "groundedness",
        "citation_accuracy",
        "completeness",
        "correctness",
    ):
        if key in ci_summary:
            lines.append(f"| {key} | {format_ci(ci_summary[key])} |")
    lines += [
        f"| graded / total | {int(summary['graded'])} / {int(summary['n'])} |",
    ]
    if "prompt_tokens_before_median" in summary and "prompt_tokens_after_median" in summary:
        lines += [
            f"| median prompt tokens before | {summary['prompt_tokens_before_median']:.1f} |",
            f"| median prompt tokens after | {summary['prompt_tokens_after_median']:.1f} |",
        ]
    lines += small_n_warning(int(summary["graded"]))
    ground_truth = ground_truth_counts([record.tags for record in records])
    lines += drafted_questions_warning(
        ground_truth["drafted"], ground_truth["drafted"] + ground_truth["reviewed"]
    )
    lines += [
        "",
        "## Per question",
        "",
        "| Question | grounded | citations | complete | correct | note |",
        "|----------|---------:|----------:|---------:|--------:|------|",
    ]
    for record in records:
        g = record.grounding
        c = record.correctness
        note = record.error or ("honesty probe" if "unanswerable" in record.tags else "")
        lines.append(
            f"| {record.question_id} "
            f"| {g.groundedness if g else '-'} "
            f"| {g.citation_accuracy if g else '-'} "
            f"| {g.completeness if g else '-'} "
            f"| {c.correctness if c else '-'} "
            f"| {note} |"
        )
    lines.append("")
    return "\n".join(lines)
