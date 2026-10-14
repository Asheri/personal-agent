"""Drafting seed questions, and checking that the model did not invent them.

Seed questions are the ground truth every retrieval and answer metric is
computed against, so a plausible-looking question with a fabricated number in
it does more damage than no question at all. The model is asked to quote its
evidence verbatim from passages it was shown; whether it actually did is
checked here, in Python, against those same passages. A phrase that appears in
no passage of a document the question names is a fabrication, and the row goes.

What survives is tagged ``drafted``. That tag is the honesty contract: it
travels into the seed file, out through the evaluation reports, and stays
until a domain expert reads the question and removes it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from sci_rag.draft import DraftError, complete, parse_json_object
from sci_rag.draft import render_prompt as _render_template
from sci_rag.draft.sampling import PassageSample, format_passages
from sci_rag.evals.seeds import DRAFTED_TAG, SeedQuestion

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sci_rag.domain import DomainProfile
    from sci_rag.llm import LLMClient

PROMPT_NAME = "seed_questions"

#: Written at the top of every drafted file. ``load_seed_questions`` skips
#: ``#`` lines, so this is a comment to the reader and nothing to the loader.
DRAFTED_HEADER = """\
# These are model-drafted seed questions, awaiting expert review.
#
# Every row below carries the "drafted" tag. While that tag is present, the
# evaluation reports say out loud that their ground truth is unreviewed and
# their numbers are provisional. Read each question, check its evidence
# phrases against the document it names, then delete the tag. That deletion
# is the expert sign-off, and nothing in the kit does it for you.
"""

#: A phrase shorter than this cannot distinguish one passage from another,
#: matching the floor :func:`sci_rag.evals.retrieval_eval.is_relevant` uses.
_MIN_PHRASE_CHARS = 3

#: Substring identifying the probe note, so a repair round can restate it
#: against the merged set instead of leaving two stale copies behind.
_PROBE_NOTE_MARKER = "honesty probe"
_MISSING_PROBE_NOTE = (
    "The draft contains no `unanswerable` honesty probe. Add one by hand: an "
    "evaluation set without one cannot tell you whether the assistant admits "
    "a gap or invents an answer."
)


def _normalize(text: str) -> str:
    """Whitespace- and case-normalized, the way retrieval judges evidence.

    "Verbatim" has to survive a line wrap: a phrase the model copied out of a
    passage that the parser had broken across two lines is still a quote, not
    an invention.
    """
    return " ".join(text.lower().split())


@dataclass
class DraftedQuestions:
    """What a drafting run produced, and what it refused to keep."""

    questions: list[SeedQuestion] = field(default_factory=list)
    #: ``(question id, why it was dropped)``. Printed, never silently binned.
    dropped: list[tuple[str, str]] = field(default_factory=list)
    #: Observations that did not cost a row, such as a missing honesty probe.
    notes: list[str] = field(default_factory=list)
    #: Where the grounding passages came from, for the run summary.
    origin: str = ""


def render_prompt(
    domain: DomainProfile, *, sample: PassageSample, count: int, rejected: str = ""
) -> str:
    """The corpus-grounded prompt, identical in both lanes.

    ``rejected`` is empty on the first pass and carries the verification
    failures on a repair round, so one template covers both and the repair
    wording stays in ``domain/prompts/`` with everything else.
    """
    return _render_template(
        domain.directory,
        PROMPT_NAME,
        DOMAIN_NAME=domain.name,
        ENTITY_TYPES=domain.entity_types_block(),
        QUERY_CLASSES="\n".join(
            f"- {q.name}: {', '.join(q.keywords)}" if q.keywords else f"- {q.name}"
            for q in domain.config.query_classes
        ),
        PASSAGES=format_passages(sample.passages),
        COUNT=str(count),
        REJECTED=rejected,
    )


def parse_reply(raw: str) -> list[SeedQuestion]:
    """Validate an untrusted reply into seed questions, or say why not."""
    payload = parse_json_object(raw, expecting="questions")
    rows = payload.get("questions")
    if not isinstance(rows, list) or not rows:
        raise DraftError(
            "The reply carried no 'questions' list. Expected "
            '{"questions": [{"id": ..., "question": ...}, ...]}.'
        )

    questions: list[SeedQuestion] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise DraftError(f"Question {index} is not a JSON object.")
        try:
            question = SeedQuestion.model_validate(row)
        except ValidationError as exc:
            raise DraftError(f"Question {index} did not validate: {exc}") from exc
        if question.id in seen:
            raise DraftError(f"The reply contains a duplicate question id {question.id!r}.")
        seen.add(question.id)
        questions.append(question)
    return questions


def verify_grounding(questions: list[SeedQuestion], sample: PassageSample) -> DraftedQuestions:
    """Drop every question whose evidence is not in the passages it names.

    Two independent claims are checked, because a model can get either one
    wrong on its own: that each ``reference_title`` names a document the
    sample actually contains, and that each ``evidence_phrase`` appears in a
    passage belonging to one of those documents. Getting the phrase right but
    the document wrong is the common failure, and it is the one that quietly
    corrupts a retrieval metric.
    """
    passages_by_title: dict[str, list[str]] = {}
    for passage in sample.passages:
        passages_by_title.setdefault(_normalize(passage.document_title), []).append(
            _normalize(passage.text)
        )

    result = DraftedQuestions(origin=sample.origin)
    probes = 0
    for question in questions:
        if not question.answerable:
            probes += 1
            if question.reference_titles or question.evidence_phrases:
                result.notes.append(
                    f"{question.id}: an unanswerable probe cannot cite evidence, so its "
                    "reference titles and evidence phrases were cleared."
                )
                question = question.model_copy(
                    update={"reference_titles": [], "evidence_phrases": []}
                )
            result.questions.append(question)
            continue

        if not question.reference_titles:
            result.dropped.append((question.id, "it names no reference document."))
            continue

        unknown = [
            title
            for title in question.reference_titles
            if _normalize(title) not in passages_by_title
        ]
        if unknown:
            result.dropped.append(
                (
                    question.id,
                    "it names a document that is not in the sampled corpus: "
                    + ", ".join(repr(title) for title in unknown)
                    + ".",
                )
            )
            continue

        if not question.evidence_phrases:
            result.dropped.append((question.id, "it quotes no evidence phrase."))
            continue

        haystack = [
            text
            for title in question.reference_titles
            for text in passages_by_title[_normalize(title)]
        ]
        ungrounded = [
            phrase
            for phrase in question.evidence_phrases
            if len(phrase.strip()) < _MIN_PHRASE_CHARS
            or not any(_normalize(phrase) in text for text in haystack)
        ]
        if ungrounded:
            result.dropped.append(
                (
                    question.id,
                    "these evidence phrases appear in no passage of the documents it "
                    "names: " + ", ".join(repr(phrase) for phrase in ungrounded) + ".",
                )
            )
            continue

        result.questions.append(question)

    if probes == 0:
        result.notes.append(_MISSING_PROBE_NOTE)
    elif probes > 1:
        result.notes.append(
            f"The draft contains {probes} `unanswerable` probes. One is the convention; "
            "keep the best and delete the rest."
        )
    return result


def _rejection_note(dropped: list[tuple[str, str]]) -> str:
    lines = [
        "A previous attempt was rejected. These questions failed verification "
        "against the passages above:",
        "",
    ]
    lines += [f"- {qid}: {reason}" for qid, reason in dropped]
    lines += [
        "",
        "Do not repeat them. Copy your evidence phrases character for character "
        "out of the passages, and name only the documents those passages belong to.",
    ]
    return "\n".join(lines)


async def draft_questions(
    domain: DomainProfile,
    *,
    sample: PassageSample,
    count: int,
    llm: LLMClient | None = None,
    settings: Any = None,
    raw_reply: str | None = None,
    repair: bool = True,
) -> DraftedQuestions:
    """Draft seed questions and keep only the ones the passages support.

    ``raw_reply`` is Lane B: the reply came from an assistant this kit never
    spoke to, and it goes through exactly the parsing and verification Lane A's
    own reply does. A repair round only makes sense in Lane A, because Lane B
    has no model to ask again.
    """
    if raw_reply is not None:
        return _stamped(verify_grounding(parse_reply(raw_reply), sample))

    prompt = render_prompt(domain, sample=sample, count=count)
    result = verify_grounding(
        parse_reply(await complete(prompt, llm=llm, settings=settings)), sample
    )
    if not repair or not result.dropped:
        return _stamped(result)

    shortfall = count - len(result.questions)
    if shortfall <= 0:
        return _stamped(result)

    repair_prompt = render_prompt(
        domain, sample=sample, count=shortfall, rejected=_rejection_note(result.dropped)
    )
    try:
        repaired = verify_grounding(
            parse_reply(await complete(repair_prompt, llm=llm, settings=settings)), sample
        )
    except DraftError as exc:
        # A failed repair is not a failed run: the first pass already produced
        # verified questions, and losing them to a bad second reply would be
        # the worse outcome.
        result.notes.append(f"The repair round did not return usable JSON ({exc}).")
        return _stamped(result)

    known = {question.id for question in result.questions}
    # The repair fills the shortfall and stops there. A model that over-delivers
    # on the first pass keeps every row it grounded, but a second pass must not
    # quietly double the set someone asked for.
    replacements = [q for q in repaired.questions if q.id not in known][:shortfall]
    result.questions.extend(replacements)
    result.dropped.extend(repaired.dropped)
    # The probe note is about the combined set, so both passes' versions of it
    # are stale here and the question is re-asked once against the merged rows.
    result.notes = [note for note in result.notes if _PROBE_NOTE_MARKER not in note]
    result.notes.extend(note for note in repaired.notes if _PROBE_NOTE_MARKER not in note)
    if all(question.answerable for question in result.questions):
        result.notes.append(_MISSING_PROBE_NOTE)
    return result


def tag_as_drafted(questions: list[SeedQuestion]) -> list[SeedQuestion]:
    """Stamp provenance on every row, without disturbing the model's own tags."""
    return [
        question
        if question.drafted
        else question.model_copy(update={"tags": [*question.tags, DRAFTED_TAG]})
        for question in questions
    ]


def _stamped(result: DraftedQuestions) -> DraftedQuestions:
    """Provenance is not optional, so it is applied on the way out, once.

    Both lanes funnel through here, which is what makes it impossible to
    write a drafted question into a seed file without its tag.
    """
    result.questions = tag_as_drafted(result.questions)
    return result


def render_jsonl(questions: list[SeedQuestion]) -> str:
    """The seed-question file a drafting run proposes, header and all."""
    lines = [DRAFTED_HEADER.rstrip("\n")]
    lines += [
        json.dumps(question.model_dump(), ensure_ascii=False, sort_keys=False)
        for question in questions
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "DRAFTED_HEADER",
    "PROMPT_NAME",
    "DraftedQuestions",
    "draft_questions",
    "parse_reply",
    "render_jsonl",
    "render_prompt",
    "tag_as_drafted",
    "verify_grounding",
]
