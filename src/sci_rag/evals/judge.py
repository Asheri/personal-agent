"""The LLM judge, designed around one hard-won rule: keep it blind.

A judge that sees the reference answer while grading groundedness will
happily reward an answer for matching the reference even when the cited
sources do not support it. So grading happens in two independent passes:

* **Grounding pass** (blind): the judge sees the question, the answer, and
  exactly the sources the assistant retrieved. It scores groundedness,
  citation accuracy, and completeness against those sources only. No
  reference answer anywhere in the prompt.
* **Correctness pass** (reference-based): a separate call compares the
  answer to the expert reference, without the sources. It scores factual
  agreement only.

Both passes run at temperature 0, scores are clamped to the 0-to-2 rubric,
and a malformed judge response records as a failure rather than a silent
zero or a retryable guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from sci_rag.domain import DomainProfile
from sci_rag.llm import LLMClient

log = structlog.get_logger(__name__)


@dataclass
class GroundingGrade:
    groundedness: int
    citation_accuracy: int
    completeness: int
    rationale: str

    @property
    def total(self) -> int:
        return self.groundedness + self.citation_accuracy + self.completeness


@dataclass
class CorrectnessGrade:
    correctness: int
    rationale: str


class JudgeResponseError(RuntimeError):
    """The judge model returned something that is not a valid grade."""


def _clamp_score(payload: Any, key: str) -> int:
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, int | float):
        raise JudgeResponseError(f"judge response missing numeric {key!r}: {payload!r}")
    return max(0, min(2, round(value)))


async def grade_grounding(
    llm: LLMClient,
    domain: DomainProfile,
    *,
    question: str,
    answer_text: str,
    sources_block: str,
) -> GroundingGrade:
    prompt = domain.render_prompt(
        "judge_grounding",
        DOMAIN_NAME=domain.name,
        QUERY=question,
        ANSWER=answer_text,
        SOURCES=sources_block,
    )
    payload = await llm.generate_json(prompt, max_tokens=1024)
    return GroundingGrade(
        groundedness=_clamp_score(payload, "groundedness"),
        citation_accuracy=_clamp_score(payload, "citation_accuracy"),
        completeness=_clamp_score(payload, "completeness"),
        rationale=str(payload.get("rationale", "")).strip() if isinstance(payload, dict) else "",
    )


async def grade_correctness(
    llm: LLMClient,
    domain: DomainProfile,
    *,
    question: str,
    reference_answer: str,
    answer_text: str,
) -> CorrectnessGrade:
    prompt = domain.render_prompt(
        "judge_correctness",
        DOMAIN_NAME=domain.name,
        QUERY=question,
        REFERENCE=reference_answer,
        ANSWER=answer_text,
    )
    payload = await llm.generate_json(prompt, max_tokens=512)
    return CorrectnessGrade(
        correctness=_clamp_score(payload, "correctness"),
        rationale=str(payload.get("rationale", "")).strip() if isinstance(payload, dict) else "",
    )
