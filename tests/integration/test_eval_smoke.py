"""The CI smoke eval: the shipped demo corpus + shipped seed questions must
keep clearing a conservative retrieval bar, entirely offline.

This is the tripwire that catches a broken layer, a broken chunker, or a
broken seed file before it ships. The thresholds are deliberately modest:
the offline hash embedder is lexical, so real embeddings should only do
better.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from sci_rag.answer import AnswerEngine
from sci_rag.db import get_session_factory
from sci_rag.domain import load_domain
from sci_rag.evals import (
    DEFAULT_ABLATIONS,
    load_seed_questions,
    run_answer_eval,
    run_retrieval_eval,
    summarize_answer_records,
)
from sci_rag.ingest import ingest_entries, load_manifest
from sci_rag.llm import LLMClient
from sci_rag.retrieve import Retriever

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).parents[2]
DOMAIN_DIR = REPO_ROOT / "domain"


class SmokeLLM(LLMClient):
    """Deterministic stand-in for every generation role in the smoke eval."""

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        if "Sources the assistant retrieved" in prompt:
            return '{"groundedness": 2, "citation_accuracy": 1, "completeness": 2, "rationale": "smoke"}'
        if "Reference answer (ground truth)" in prompt:
            return '{"correctness": 2, "rationale": "smoke"}'
        if '"entities"' in prompt:
            return '{"entities": []}'
        return "A short hypothetical passage about agricultural residues and conversion."

    async def _stream_impl(self) -> AsyncIterator[str]:
        yield "Grounded smoke answer with a citation [1]."

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream_impl()


@pytest.fixture()
async def demo_corpus(clean_tables, local_embedder):  # type: ignore[no-untyped-def]
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    report = await ingest_entries(entries, embedder=local_embedder)
    assert report.failed == 0, [o.detail for o in report.outcomes if o.status == "failed"]
    return report


async def test_smoke_retrieval_clears_the_bar(demo_corpus, local_embedder):  # type: ignore[no-untyped-def]
    questions = load_seed_questions(DOMAIN_DIR / "eval_seed_questions.jsonl")
    retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=SmokeLLM(),
        session_factory=get_session_factory(),
    )
    [full] = await run_retrieval_eval(retriever, questions, limit=10)
    metrics = full.metrics
    assert metrics["n"] >= 8
    assert metrics["hit_at_10"] >= 0.65, f"retrieval smoke regressed: {metrics}"
    assert metrics["mrr"] >= 0.35, f"retrieval smoke regressed: {metrics}"


async def test_smoke_ablations_run_every_config(demo_corpus, local_embedder):  # type: ignore[no-untyped-def]
    questions = load_seed_questions(DOMAIN_DIR / "eval_seed_questions.jsonl")[:4]
    retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=SmokeLLM(),
        session_factory=get_session_factory(),
    )
    results = await run_retrieval_eval(retriever, questions, configs=DEFAULT_ABLATIONS, limit=10)
    assert [r.config.name for r in results] == [c.name for c in DEFAULT_ABLATIONS]
    for result in results:
        assert result.metrics["n"] == 4.0


async def test_smoke_answer_eval_with_blind_judge(demo_corpus, local_embedder, tmp_path):  # type: ignore[no-untyped-def]
    questions = load_seed_questions(DOMAIN_DIR / "eval_seed_questions.jsonl")[:3]
    llm = SmokeLLM()
    engine = AnswerEngine(
        retriever=Retriever(
            domain=load_domain(DOMAIN_DIR),
            embedder=local_embedder,
            llm=llm,
            session_factory=get_session_factory(),
        ),
        llm=llm,
    )
    records = await run_answer_eval(engine, llm, questions, profile="interactive")
    summary = summarize_answer_records(records)
    assert summary["graded"] == 3.0
    assert summary["failed"] == 0.0
    assert summary["groundedness_mean"] == 2.0

    from sci_rag.evals.report import (
        answers_markdown,
        answers_payload,
        corpus_fingerprint,
        write_report,
    )

    fingerprint = await corpus_fingerprint(get_session_factory())
    json_path, md_path = write_report(
        kind="answers",
        payload=answers_payload(records, fingerprint),
        markdown=answers_markdown(records, fingerprint),
        base_dir=tmp_path,
    )
    payload = json.loads(json_path.read_text())
    assert payload["corpus"]["documents"] == 5
    assert "| groundedness | 2.00 [2.00, 2.00] |" in md_path.read_text()
