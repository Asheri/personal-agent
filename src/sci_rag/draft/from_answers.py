"""Turn questions you already have into draft seed rows.

`sci-rag draft questions` invents the questions. This does the opposite job:
you bring the questions, one per line, and the kit proposes the ground truth
for them by answering each one and reading its own cited evidence back. The
questions worth evaluating against are usually the ones real users asked,
especially the ones the assistant fumbled, and those cannot be invented from
the corpus.

The obvious way to do this would be to ask the model for evidence phrases
alongside the answer, and the obvious way is wrong. Phrases the model writes
are phrases the model can get wrong, and a seed question with a fabricated
evidence phrase silently poisons every retrieval metric computed against it.
So nothing here is taken on the model's word: evidence phrases are extracted
from the retrieved chunk text, kept only when they appear verbatim in both
the answer and a chunk that answer cited, and each finished row is then run
through :func:`sci_rag.evals.retrieval_eval.is_relevant`, the same predicate
the evaluation itself uses. A row that cannot prove itself relevant to its own
evidence is dropped with a reason rather than proposed.

Rows carry the existing ``drafted`` tag rather than a new marker, so they
travel through the same honesty plumbing every other drafter's output does.
See :mod:`sci_rag.evals.seeds` for what that tag promises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sci_rag.draft import DraftError
from sci_rag.draft.questions import tag_as_drafted
from sci_rag.evals.retrieval_eval import is_relevant
from sci_rag.evals.seeds import SeedQuestion

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sci_rag.answer import AnswerEngine
    from sci_rag.retrieve import RetrievedItem

#: Written at the top of a proposal. ``load_seed_questions`` skips ``#`` lines.
HEADER = """\
# Seed questions drafted from your own question list, awaiting expert review.
#
# The questions are yours. Everything else on each row is the kit's proposal:
# the reference answer is what the assistant said, and the evidence phrases
# were extracted from the passages it cited, not written by a model. Both are
# hypotheses. Read each row against the document it names, correct what is
# wrong, then delete the "drafted" tag. That deletion is the sign-off.
"""

#: Matches the floor :func:`is_relevant` applies: anything shorter cannot
#: distinguish one passage from another.
MIN_PHRASE_CHARS = 3

#: More than a handful stops being distinctive and starts being a transcript.
MAX_PHRASES = 4

#: Numbers carry units, ranges, and percent signs, and they are what makes an
#: evidence phrase discriminating. ``docs/evaluation.md`` says so outright:
#: "Numbers with units are ideal".
_NUMERIC_SPAN = re.compile(r"\d[\d,.]*\s*(?:percent|%|[A-Za-z][A-Za-z/·^\-]{0,15})?")

#: Two or more capitalized words: the named things a corpus is about.
_PROPER_SPAN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")

_ID_ALLOWED = re.compile(r"[^a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "by",
        "does",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "which",
        "why",
        "with",
    }
)


@dataclass
class DraftedSeeds:
    """What a conversion produced, and what it refused to produce."""

    questions: list[SeedQuestion] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def read_questions(path: object) -> list[str]:
    """One question per line. Blank lines and ``#`` comments are skipped."""
    from pathlib import Path

    file = Path(str(path))
    if not file.exists():
        raise DraftError(f"No questions file at {file}.")
    lines = [
        line.strip()
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        raise DraftError(
            f"{file} has no questions in it. Write one question per line; "
            "blank lines and # comments are ignored."
        )
    return lines


def make_id(question: str, taken: set[str]) -> str:
    """A readable, stable id, made unique against ids already in the seed file."""
    words = [
        word
        for word in _ID_ALLOWED.sub(" ", question.lower()).split()
        if word and word not in _STOPWORDS
    ]
    base = "-".join(words[:5]) or "question"
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def evidence_phrases(answer: str, cited: list[RetrievedItem]) -> list[str]:
    """Spans present verbatim in both the answer and a chunk the answer cited.

    Appearing in both is the whole test. A span only in the chunk is evidence
    the answer did not use; a span only in the answer is the model's own
    words, which is exactly what must never become ground truth.
    """
    haystacks = [_normalize(item.content) for item in cited]
    if not haystacks:
        return []

    seen: set[str] = set()
    phrases: list[str] = []
    for pattern in (_NUMERIC_SPAN, _PROPER_SPAN):
        for match in pattern.finditer(answer):
            span = match.group(0).strip().rstrip(".,;:")
            if len(span) < MIN_PHRASE_CHARS:
                continue
            key = _normalize(span)
            if key in seen or not any(key in haystack for haystack in haystacks):
                continue
            seen.add(key)
            phrases.append(span)
            if len(phrases) >= MAX_PHRASES:
                return phrases
    return phrases


async def seeds_from_answers(
    engine: AnswerEngine,
    questions: list[str],
    *,
    profile: str = "deep",
    limit: int = 8,
    taken_ids: set[str] | None = None,
) -> DraftedSeeds:
    """Answer each question and propose a seed row from what the answer cited."""
    result = DraftedSeeds()
    taken = set(taken_ids or set())

    for question in questions:
        answer = await engine.answer(question, profile=profile, limit=limit)
        cited_ids = {source.chunk_id for source in answer.cited_sources if source.chunk_id}
        cited_items = [item for item in answer.retrieval.items if item.id in cited_ids]

        if not cited_items:
            result.dropped.append(
                f"{question!r}: the answer cited no sources, so there is no evidence to "
                "propose. Keep the question and write its ground truth by hand, or tag "
                "it 'unanswerable' if that is the honest answer."
            )
            continue

        phrases = evidence_phrases(answer.text, cited_items)
        titles = _unique(item.title for item in cited_items if item.title)
        row = SeedQuestion(
            id=make_id(question, taken),
            question=question,
            reference_answer=answer.text.strip(),
            reference_titles=titles,
            evidence_phrases=phrases,
        )

        # The same predicate the evaluation runs, applied before the row is
        # proposed rather than after somebody trusts it.
        if not any(is_relevant(item, row) for item in answer.retrieval.items):
            result.dropped.append(
                f"{question!r}: nothing retrieved matches the proposed row, so it would "
                "score zero against its own evidence. The answer may have paraphrased "
                "rather than quoted."
            )
            taken.discard(row.id)
            continue

        result.questions.append(row)

    result.questions = tag_as_drafted(result.questions)
    if result.questions and not any(q.evidence_phrases for q in result.questions):
        result.notes.append(
            "No row got an evidence phrase; every one is matching on title alone. "
            "Retrieval metrics will be coarse until you add distinctive phrases by hand."
        )
    if result.dropped:
        result.notes.append(
            f"{len(result.dropped)} question(s) produced no usable row. They are listed "
            "above and are not in the proposal."
        )
    return result


def _unique(values: object) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:  # type: ignore[attr-defined]
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def render_jsonl(questions: list[SeedQuestion]) -> str:
    """The proposal file, header and all."""
    import json

    lines = [HEADER.rstrip("\n")]
    lines += [
        json.dumps(question.model_dump(), ensure_ascii=False, sort_keys=False)
        for question in questions
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "HEADER",
    "DraftedSeeds",
    "evidence_phrases",
    "make_id",
    "read_questions",
    "render_jsonl",
    "seeds_from_answers",
]
