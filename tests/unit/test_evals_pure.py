from pathlib import Path

import pytest

from sci_rag.evals import (
    JudgeResponseError,
    SeedQuestion,
    is_relevant,
    load_seed_questions,
)
from sci_rag.evals.retrieval_eval import QuestionRetrievalRecord, RetrievalEvalResult
from sci_rag.retrieve import RetrievedItem

REPO_ROOT = Path(__file__).parents[2]


def _item(title: str = "Some Doc", content: str = "") -> RetrievedItem:
    return RetrievedItem(
        kind="chunk", id="c1", score=1.0, layers=["vector"], title=title, content=content
    )


def test_relevance_by_title_is_case_and_space_insensitive() -> None:
    question = SeedQuestion(id="q", question="?", reference_titles=["Rice  Straw REPORT"])
    assert is_relevant(_item(title="rice straw report"), question)
    assert not is_relevant(_item(title="Almond Guide"), question)


def test_relevance_by_evidence_phrase_survives_line_wrapping() -> None:
    question = SeedQuestion(id="q", question="?", evidence_phrases=["18 dollars per dry ton"])
    wrapped = "The credit pays facilities 18\ndollars   per dry ton of residue."
    assert is_relevant(_item(content=wrapped), question)


def test_tiny_evidence_phrases_are_ignored() -> None:
    question = SeedQuestion(id="q", question="?", evidence_phrases=["18"])
    assert not is_relevant(_item(content="18 things"), question)


def test_retrieval_metrics_math() -> None:
    records = [
        QuestionRetrievalRecord("a", 1, True, True, 10, []),
        QuestionRetrievalRecord("b", 7, False, True, 10, []),
        QuestionRetrievalRecord("c", None, False, False, 10, []),
    ]
    from sci_rag.evals.retrieval_eval import AblationConfig

    metrics = RetrievalEvalResult(AblationConfig("x", "test"), records).metrics
    assert metrics["hit_at_5"] == pytest.approx(1 / 3)
    assert metrics["hit_at_10"] == pytest.approx(2 / 3)
    assert metrics["mrr"] == pytest.approx((1.0 + 1 / 7) / 3)


def test_shipped_seed_questions_load_cleanly() -> None:
    questions = load_seed_questions(REPO_ROOT / "domain" / "eval_seed_questions.jsonl")
    assert len(questions) >= 8
    ids = [q.id for q in questions]
    assert len(ids) == len(set(ids))
    assert any(not q.answerable for q in questions), "expected an honesty probe"
    for question in questions:
        if question.answerable:
            assert question.reference_titles or question.evidence_phrases


def test_seed_loader_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    path.write_text('{"id": "a", "question": "x"}\n{"id": "a", "question": "y"}\n')
    with pytest.raises(ValueError, match="duplicate"):
        load_seed_questions(path)


async def test_judge_clamps_scores_and_parses_fences() -> None:
    from sci_rag.domain import load_domain
    from sci_rag.evals import grade_grounding
    from sci_rag.llm import MockLLM

    domain = load_domain(REPO_ROOT / "domain")
    llm = MockLLM(
        responses=[
            '```json\n{"groundedness": 5, "citation_accuracy": -1, '
            '"completeness": 1.6, "rationale": "ok"}\n```'
        ]
    )
    grade = await grade_grounding(llm, domain, question="q", answer_text="a", sources_block="[1] s")
    assert grade.groundedness == 2  # clamped down
    assert grade.citation_accuracy == 0  # clamped up
    assert grade.completeness == 2  # rounded then clamped
    # The blind pass must never receive a reference answer slot.
    assert "Reference answer" not in llm.calls[0]["prompt"]


async def test_judge_rejects_malformed_response() -> None:
    from sci_rag.domain import load_domain
    from sci_rag.evals import grade_correctness
    from sci_rag.llm import MockLLM

    domain = load_domain(REPO_ROOT / "domain")
    llm = MockLLM(responses=['{"rationale": "no score here"}'])
    with pytest.raises(JudgeResponseError):
        await grade_correctness(llm, domain, question="q", reference_answer="r", answer_text="a")
