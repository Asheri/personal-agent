#!/usr/bin/env python
"""Three-condition answer comparison on MultiHop-RAG.

The question this answers is the one a course report has to answer: does the
concept graph earn its place next to plain retrieval, and does either beat
answering with no retrieved evidence at all?

Conditions, all on the same questions and the same model:

``plain``  no retrieval. The answer prompt gets the question and an explicit
           "(no sources were retrieved)" block, so the instructions and the
           output contract match the other two conditions.
``rag``    vector and keyword layers only.
``kg``     every layer the domain config enables, graph and community included.

MultiHop-RAG ships two files (HuggingFace ``yixuantt/MultiHopRAG``):

``corpus.json``      `[{"title", "body", "source", "published_at"}]`
``MultiHopRAG.json`` `[{"query", "answer", "question_type", "evidence_list":
                     [{"fact", "source", "url", "published_at"}]}]`

Each article becomes one Markdown file plus a manifest row, so the ordinary
ingest path does the work and nothing here knows how to chunk a document.

Examples::

    # Validate the dataset and write the corpus, no models, no database
    uv run python scripts/run_benchmark_eval.py --dataset ~/data/MultiHopRAG \\
        --corpus-dir "$PCMEM_DATA_DIR/multihop" --dry-run

    # Ingest and build the graph first (needs the database and a model key)
    uv run sci-rag ingest --manifest "$PCMEM_DATA_DIR/multihop/manifest.jsonl"
    uv run sci-rag graph extract && uv run sci-rag graph communities

    # Then the three conditions; raise concurrency once the provider's TPM fits
    uv run python scripts/run_benchmark_eval.py --dataset ~/data/MultiHopRAG \\
        --corpus-dir "$PCMEM_DATA_DIR/multihop" --concurrency 16 \\
        --output .context/benchmark-multihoprag
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sci_rag.evals.seeds import SeedQuestion

#: The license class MultiHop-RAG publishes (ODC-BY), which allows commercial
#: reuse with attribution. Recorded per document so the rights gate sees it.
LICENSE = "open_commercial"

CONDITIONS = ("plain", "rag", "kg")

PLAIN_SOURCES = "(no sources were retrieved)"

#: Layers the ``rag`` condition keeps. Everything else is the full pipeline.
RAG_LAYERS = {"include_graph": False, "include_community": False, "include_hyde": False}


@dataclass
class Article:
    title: str
    body: str
    source: str = ""
    published_at: str = ""


@dataclass
class Query:
    query: str
    answer: str
    question_type: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ConditionRecord:
    question_id: str
    question_type: str
    condition: str
    answer: str = ""
    cited: int = 0
    correctness: int | None = None
    grounding: int | None = None
    error: str = ""

    @property
    def correct(self) -> bool:
        return (self.correctness or 0) >= 2

    @property
    def grounded(self) -> bool:
        return (self.grounding or 0) >= 2


def load_corpus(path: Path) -> list[Article]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    articles = [
        Article(
            title=str(row.get("title") or f"article-{index}"),
            body=str(row.get("body") or ""),
            source=str(row.get("source") or ""),
            published_at=str(row.get("published_at") or ""),
        )
        for index, row in enumerate(rows)
    ]
    return [article for article in articles if article.body.strip()]


def load_queries(path: Path) -> list[Query]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    queries = []
    for row in rows:
        question = str(row.get("query") or "").strip()
        if not question:
            continue
        queries.append(
            Query(
                query=question,
                answer=str(row.get("answer") or ""),
                question_type=_kind(str(row.get("question_type") or "untyped")),
                evidence=list(row.get("evidence_list") or []),
            )
        )
    return queries


def _kind(raw: str) -> str:
    """Normalize a benchmark question type.

    MultiHop-RAG names its types `comparison_query`, `inference_query`,
    `temporal_query` and `null_query`; the suffix carries no meaning here, and
    `null` has to survive normalization because it becomes the unanswerable
    probe.
    """
    cleaned = raw.strip().casefold()
    return cleaned.removesuffix("_query") or "untyped"


def _slug(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:60] or 'article'}-{digest}"


def _year(published_at: str) -> int | None:
    match = re.match(r"(\d{4})", published_at.strip())
    return int(match.group(1)) if match else None


def write_corpus(articles: list[Article], corpus_dir: Path) -> Path:
    """Write one Markdown file per article plus a manifest; return the manifest."""
    documents = corpus_dir / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    rows = []
    seen: set[str] = set()
    for article in articles:
        slug = _slug(article.title)
        if slug in seen:
            continue
        seen.add(slug)
        relative = Path("documents") / f"{slug}.md"
        heading = article.title
        body = f"# {heading}\n\n{article.body.strip()}\n"
        (corpus_dir / relative).write_text(body, encoding="utf-8")
        row: dict[str, Any] = {
            "path": relative.as_posix(),
            "title": article.title,
            "license_class": LICENSE,
            "source": f"multihoprag:{article.source}" if article.source else "multihoprag",
        }
        year = _year(article.published_at)
        if year is not None:
            row["year"] = year
        rows.append(row)
    manifest = corpus_dir / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return manifest


def stratified_sample(queries: list[Query], limit: int, seed: int = 0) -> list[Query]:
    """Keep the question-type mix when sampling.

    A provider's token budget is the reason to sample at all, and a sample that
    over-represents ``null`` questions would change what the accuracy means.
    """
    if limit <= 0 or limit >= len(queries):
        return list(queries)
    buckets: dict[str, list[Query]] = defaultdict(list)
    for query in queries:
        buckets[query.question_type].append(query)
    rng = random.Random(seed)
    chosen: list[Query] = []
    total = len(queries)
    for name in sorted(buckets):
        bucket = buckets[name]
        share = max(1, round(limit * len(bucket) / total))
        chosen.extend(rng.sample(bucket, min(share, len(bucket))))
    rng.shuffle(chosen)
    return chosen[:limit]


def to_seed_questions(queries: list[Query]) -> list[SeedQuestion]:
    """Map benchmark rows onto the repository's seed-question shape."""
    questions = []
    for index, query in enumerate(queries):
        titles = sorted(
            {str(row.get("title") or row.get("source") or "") for row in query.evidence} - {""}
        )
        phrases = [str(row.get("fact") or "") for row in query.evidence]
        tags = [query.question_type]
        if query.question_type.casefold() == "null":
            tags.append("unanswerable")
        questions.append(
            SeedQuestion(
                id=f"mhr-{index:05d}",
                question=query.query,
                reference_answer=query.answer or None,
                reference_titles=titles,
                evidence_phrases=[phrase for phrase in phrases if phrase],
                tags=tags,
            )
        )
    return questions


def mcnemar(a: list[bool], b: list[bool]) -> dict[str, Any]:
    """Exact two-sided McNemar on paired outcomes."""
    if len(a) != len(b):
        raise ValueError("paired comparison needs equal lengths")
    b_only = sum(1 for left, right in zip(a, b, strict=True) if not left and right)
    a_only = sum(1 for left, right in zip(a, b, strict=True) if left and not right)
    discordant = a_only + b_only
    if discordant == 0:
        p = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(min(a_only, b_only) + 1))
        p = min(1.0, 2 * tail / (2**discordant))
    return {"a_only": a_only, "b_only": b_only, "n": len(a), "p_value": p}


@dataclass
class Condition:
    name: str
    layers: dict[str, Any] = field(default_factory=dict)
    retrieve: bool = True


def _condition_from_name(name: str) -> Condition:
    if name == "plain":
        return Condition(name=name, retrieve=False)
    if name == "rag":
        return Condition(name=name, layers=dict(RAG_LAYERS))
    if name == "kg":
        return Condition(name=name)
    raise SystemExit(f"unknown condition {name!r}; choose from {', '.join(CONDITIONS)}")


class _FixedLayers:
    """A retriever whose layer switches are pinned for one condition."""

    def __init__(self, retriever: Any, layers: dict[str, Any]) -> None:
        self._retriever = retriever
        self._layers = layers

    async def retrieve(self, query: str, **kwargs: Any) -> Any:
        return await self._retriever.retrieve(query, **{**kwargs, **self._layers})

    def __getattr__(self, item: str) -> Any:
        return getattr(self._retriever, item)


async def _answer_plain(engine: Any, question: SeedQuestion, limit: int) -> Any:
    """Answer with no retrieved evidence, through the same prompt template."""
    domain = engine.domain
    prompt = domain.render_prompt(
        "answer",
        DOMAIN_NAME=domain.name,
        QUERY=question.question,
        SOURCES=PLAIN_SOURCES,
    )
    llm = engine._resolve_llm(None)
    answer = await llm.generate(prompt, max_tokens=2048)
    return answer, 0


async def run_condition(
    condition: Condition,
    engine: Any,
    judge: Any,
    questions: list[SeedQuestion],
    *,
    limit: int,
    concurrency: int,
) -> list[ConditionRecord]:
    from sci_rag.evals.judge import grade_correctness, grade_grounding

    limiter = asyncio.Semaphore(max(1, concurrency))

    async def one(question: SeedQuestion) -> ConditionRecord:
        record = ConditionRecord(
            question_id=question.id,
            question_type=question.tags[0] if question.tags else "untyped",
            condition=condition.name,
        )
        async with limiter:
            try:
                if condition.retrieve:
                    result = await engine.answer(question.question, profile="deep", limit=limit)
                    record.answer = result.text
                    record.cited = len(result.cited_sources)
                    sources_block = None
                else:
                    text, cited = await _answer_plain(engine, question, limit)
                    record.answer = text
                    record.cited = cited
                    sources_block = PLAIN_SOURCES
            except Exception as exc:  # one question must not kill the run
                record.error = f"answer: {type(exc).__name__}: {exc}"
                return record

            if sources_block is None:
                from sci_rag.answer.generator import format_sources

                prompt_retrieval = result.prompt_retrieval or result.retrieval
                sources_block = (
                    format_sources(prompt_retrieval) if prompt_retrieval.items else PLAIN_SOURCES
                )
            try:
                record.grounding = (
                    await grade_grounding(
                        judge,
                        engine.domain,
                        question=question.question,
                        answer_text=record.answer,
                        sources_block=sources_block,
                    )
                ).score
            except Exception as exc:
                record.error = f"grounding: {type(exc).__name__}: {exc}"
            if question.reference_answer:
                try:
                    record.correctness = (
                        await grade_correctness(
                            judge,
                            engine.domain,
                            question=question.question,
                            reference_answer=question.reference_answer,
                            answer_text=record.answer,
                        )
                    ).score
                except Exception as exc:
                    record.error = f"correctness: {type(exc).__name__}: {exc}"
        return record

    return list(await asyncio.gather(*(one(question) for question in questions)))


def summarize(records: list[ConditionRecord]) -> dict[str, Any]:
    by_condition: dict[str, list[ConditionRecord]] = defaultdict(list)
    for record in records:
        by_condition[record.condition].append(record)
    summary: dict[str, Any] = {}
    for name, rows in by_condition.items():
        answered = [row for row in rows if not row.error]
        correct = [row for row in answered if row.correct]
        grounded = [row for row in answered if row.grounded]
        by_type: dict[str, dict[str, Any]] = {}
        for kind in sorted({row.question_type for row in rows}):
            typed = [row for row in answered if row.question_type == kind]
            by_type[kind] = {
                "n": len(typed),
                "correct": sum(1 for row in typed if row.correct),
                "accuracy": (sum(1 for row in typed if row.correct) / len(typed))
                if typed
                else None,
            }
        summary[name] = {
            "n": len(rows),
            "answered": len(answered),
            "errors": len(rows) - len(answered),
            "correct": len(correct),
            "accuracy": len(correct) / len(answered) if answered else None,
            "grounded_rate": len(grounded) / len(answered) if answered else None,
            "by_type": by_type,
        }
    return summary


def comparisons(records: list[ConditionRecord]) -> dict[str, Any]:
    """McNemar between ``rag`` and ``kg``, plus ``kg`` against ``plain``."""
    index: dict[tuple[str, str], bool] = {
        (record.question_id, record.condition): record.correct for record in records
    }
    ids = sorted({record.question_id for record in records})
    result: dict[str, Any] = {}
    for left, right in (("plain", "rag"), ("rag", "kg"), ("plain", "kg")):
        pairs = [
            (index[(qid, left)], index[(qid, right)])
            for qid in ids
            if (qid, left) in index and (qid, right) in index
        ]
        if not pairs:
            continue
        result[f"{left}_vs_{right}"] = mcnemar(
            [pair[0] for pair in pairs], [pair[1] for pair in pairs]
        )
    return result


def render_markdown(summary: dict[str, Any], pairs: dict[str, Any], meta: dict[str, Any]) -> str:
    lines = ["# MultiHop-RAG answer comparison", ""]
    lines.append(
        f"Questions: {meta['questions']} (sampled from {meta['dataset_questions']}, "
        f"seed {meta['seed']}). Sources per answer: {meta['limit']}. "
        f"Answer model: `{meta['answer_model']}`, judge: `{meta['judge_model']}`."
    )
    lines.append("")
    lines.append("| Condition | Answered | Accuracy | Grounded | Errors |")
    lines.append("|---|---:|---:|---:|---:|")
    for name in ("plain", "rag", "kg"):
        row = summary.get(name)
        if not row:
            continue
        accuracy = f"{row['accuracy']:.3f}" if row["accuracy"] is not None else "-"
        grounded = f"{row['grounded_rate']:.3f}" if row["grounded_rate"] is not None else "-"
        lines.append(f"| {name} | {row['answered']} | {accuracy} | {grounded} | {row['errors']} |")
    lines.append("")
    types = sorted({kind for row in summary.values() for kind in row["by_type"]})
    if types:
        header = "| Condition | " + " | ".join(types) + " |"
        lines.append(header)
        lines.append("|---|" + "---:|" * len(types))
        for name in ("plain", "rag", "kg"):
            row = summary.get(name)
            if not row:
                continue
            cells = []
            for kind in types:
                cell = row["by_type"].get(kind)
                cells.append(f"{cell['correct']}/{cell['n']}" if cell else "-")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
    if pairs:
        lines.append("| Paired comparison | A only | B only | n | exact McNemar p |")
        lines.append("|---|---:|---:|---:|---:|")
        for label, row in pairs.items():
            lines.append(
                f"| {label} | {row['a_only']} | {row['b_only']} | {row['n']} | "
                f"{row['p_value']:.4f} |"
            )
        lines.append("")
        lines.append(
            "A correct on A only and correct on B only are the discordant pairs; "
            "the p-value is the exact two-sided McNemar tail. n counts questions "
            "answered under both conditions."
        )
        lines.append("")
    lines.append(
        "Accuracy is the share of judged answers scoring 2 or higher on the "
        "0 to 2 correctness scale, so it is a judge's verdict, not exact match."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, required=True, help="folder with corpus.json and MultiHopRAG.json"
    )
    parser.add_argument(
        "--corpus-dir", type=Path, required=True, help="where to write Markdown and the manifest"
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="where to write report.json and report.md"
    )
    parser.add_argument("--limit", type=int, default=0, help="sample this many questions (0 = all)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sources", type=int, default=6, help="sources per answer")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--conditions", default="plain,rag,kg")
    parser.add_argument("--dry-run", action="store_true", help="write the corpus and stop")
    args = parser.parse_args(argv)

    articles = load_corpus(args.dataset / "corpus.json")
    queries = load_queries(args.dataset / "MultiHopRAG.json")
    if not articles or not queries:
        raise SystemExit("dataset looks empty; expected corpus.json and MultiHopRAG.json")
    sampled = stratified_sample(queries, args.limit, args.seed)
    manifest = write_corpus(articles, args.corpus_dir)
    questions = to_seed_questions(sampled)
    print(
        json.dumps(
            {
                "articles": len(articles),
                "manifest": str(manifest),
                "dataset_questions": len(queries),
                "sampled": len(questions),
                "by_type": {
                    kind: sum(1 for question in questions if kind in question.tags)
                    for kind in sorted({tag for question in questions for tag in question.tags})
                },
            },
            indent=2,
        )
    )
    if args.dry_run:
        return 0

    from sci_rag.answer import AnswerEngine
    from sci_rag.config import get_settings
    from sci_rag.llm import get_llm

    settings = get_settings()
    if settings.is_offline():
        raise SystemExit(
            "No generation credential configured. See docs/api-keys.md: set "
            "SCI_RAG_OPENAI_API_KEY with SCI_RAG_OPENAI_BASE_URL for an "
            "OpenAI-compatible endpoint, or SCI_RAG_DEEPSEEK_API_KEY."
        )
    answer_model = str(settings.model_spec_for("answer"))
    judge = get_llm(settings, role="judge")
    judge_model = judge.describe()

    async def run_all() -> list[ConditionRecord]:
        base_engine = AnswerEngine(settings=settings)
        records: list[ConditionRecord] = []
        for name in args.conditions.split(","):
            condition = _condition_from_name(name.strip())
            engine = base_engine
            if condition.retrieve and condition.layers:
                engine = AnswerEngine(
                    settings=settings,
                    retriever=_FixedLayers(base_engine.retriever, condition.layers),
                    llm=base_engine._llm,
                )
            records.extend(
                await run_condition(
                    condition,
                    engine,
                    judge,
                    questions,
                    limit=args.sources,
                    concurrency=args.concurrency,
                )
            )
        return records

    records = asyncio.run(run_all())
    summary = summarize(records)
    pairs = comparisons(records)
    meta = {
        "dataset": str(args.dataset),
        "dataset_questions": len(queries),
        "questions": len(questions),
        "seed": args.seed,
        "limit": args.sources,
        "conditions": args.conditions.split(","),
        "answer_model": answer_model,
        "judge_model": judge_model,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if args.output is not None:
        args.output.mkdir(parents=True, exist_ok=True)
        payload = {
            "meta": meta,
            "summary": summary,
            "comparisons": pairs,
            "records": [record.__dict__ for record in records],
        }
        (args.output / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.output / "report.md").write_text(
            render_markdown(summary, pairs, meta), encoding="utf-8"
        )
        print(str(args.output / "report.md"))
    else:
        print(render_markdown(summary, pairs, meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
