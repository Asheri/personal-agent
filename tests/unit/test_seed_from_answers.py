"""Drafting seed rows from questions you already have.

The tests that matter here are the ones about what is refused. A seed question
is the ground truth every retrieval metric is computed against, so a row whose
evidence phrase came from the model's prose rather than from a retrieved
passage would silently poison the numbers computed against it, and it would
look completely normal in the file. `test_a_phrase_only_the_model_wrote_is_not
_evidence` and `test_a_row_that_cannot_prove_itself_relevant_is_dropped` are
the two guards against that.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sci_rag.draft import DraftError
from sci_rag.draft.from_answers import (
    MAX_PHRASES,
    evidence_phrases,
    make_id,
    read_questions,
    render_jsonl,
    seeds_from_answers,
)
from sci_rag.evals.retrieval_eval import is_relevant
from sci_rag.evals.seeds import DRAFTED_TAG, SeedQuestion
from sci_rag.llm import LLMClient
from sci_rag.retrieve import RetrievedItem


def _item(item_id: str, title: str, content: str) -> RetrievedItem:
    return RetrievedItem(
        kind="chunk",
        id=item_id,
        score=1.0,
        layers=["vector"],
        title=title,
        content=content,
        citation=None,
        license_class="public",
        document_id="d1",
        section_path=None,
    )


@dataclass
class _Source:
    chunk_id: str | None
    cited: bool = True


@dataclass
class _Answer:
    text: str
    retrieval: object
    sources: list[_Source]

    @property
    def cited_sources(self) -> list[_Source]:
        return [s for s in self.sources if s.cited]


@dataclass
class _Retrieval:
    items: list[RetrievedItem]


class _StubEngine:
    """Answers from a script, so the drafting logic is what is under test."""

    def __init__(self, answers: dict[str, _Answer]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    async def answer(self, question: str, **_kwargs: object) -> _Answer:
        self.asked.append(question)
        return self.answers[question]


CHUNK = _item(
    "c1",
    "Anaerobic Digestion of Crop Residues",
    "Alkali pretreated rice straw reached 320 cubic meters per dry ton at 54 percent methane.",
)


def _engine(
    text: str, items: list[RetrievedItem], cited: list[str], question: str = "q"
) -> _StubEngine:
    answer = _Answer(
        text=text,
        retrieval=_Retrieval(items=items),
        sources=[_Source(chunk_id=chunk_id) for chunk_id in cited],
    )
    return _StubEngine({question: answer})


# --- evidence phrase extraction ---------------------------------------------


def test_a_number_in_both_the_answer_and_its_source_is_evidence() -> None:
    phrases = evidence_phrases(
        "Alkali pretreated straw yields 320 cubic meters per dry ton.", [CHUNK]
    )

    assert any("320" in phrase for phrase in phrases)


def test_a_phrase_only_the_model_wrote_is_not_evidence() -> None:
    """The whole point: the model's own words must never become ground truth."""
    phrases = evidence_phrases(
        "The yield reaches 999 cubic meters, per Fabricated Institute.", [CHUNK]
    )

    assert not any("999" in phrase for phrase in phrases)
    assert not any("Fabricated" in phrase for phrase in phrases)


def test_a_phrase_only_in_the_source_is_not_evidence() -> None:
    """A span the answer did not use is not evidence the answer used it."""
    phrases = evidence_phrases("Digestion works well for this feedstock.", [CHUNK])

    assert not any("320" in phrase for phrase in phrases)


def test_no_cited_sources_means_no_phrases() -> None:
    assert evidence_phrases("320 cubic meters per dry ton.", []) == []


def test_phrases_are_capped_and_deduplicated() -> None:
    chunk = _item("c1", "T", "1 a 2 b 3 c 4 d 5 e 6 f 7 g 8 h")
    phrases = evidence_phrases("1 a 2 b 3 c 4 d 5 e 6 f 7 g 8 h 1 a 2 b", [chunk])

    assert len(phrases) <= MAX_PHRASES
    assert len(phrases) == len({phrase.casefold() for phrase in phrases})


def test_extracted_phrases_satisfy_the_evaluations_own_predicate() -> None:
    """Whatever comes out has to match under `is_relevant`, or it is decoration."""
    phrases = evidence_phrases(
        "Alkali pretreated rice straw reached 320 cubic meters per dry ton.", [CHUNK]
    )
    row = SeedQuestion(id="x", question="q", evidence_phrases=phrases, reference_titles=[])

    assert phrases
    assert is_relevant(CHUNK, row)


# --- ids ---------------------------------------------------------------------


def test_ids_are_readable_and_skip_filler_words() -> None:
    assert make_id("What biogas yield does pretreated rice straw achieve?", set()) == (
        "biogas-yield-pretreated-rice-straw"
    )


def test_ids_do_not_collide_with_what_is_already_in_the_seed_file() -> None:
    taken = {"biogas-yield"}
    first = make_id("Biogas yield?", taken)
    second = make_id("Biogas yield?", taken)

    assert first == "biogas-yield-2"
    assert second == "biogas-yield-3"


def test_an_id_is_produced_even_for_a_question_of_pure_filler() -> None:
    assert make_id("What is the?", set()) == "question"


# --- the conversion ----------------------------------------------------------


async def test_a_question_becomes_a_drafted_row() -> None:
    engine = _engine(
        "Alkali pretreated rice straw reached 320 cubic meters per dry ton.", [CHUNK], ["c1"]
    )

    result = await seeds_from_answers(engine, ["q"])  # type: ignore[arg-type]

    assert len(result.questions) == 1
    row = result.questions[0]
    assert row.question == "q"
    assert row.reference_answer.startswith("Alkali pretreated")
    assert row.reference_titles == ["Anaerobic Digestion of Crop Residues"]
    assert any("320" in phrase for phrase in row.evidence_phrases)


async def test_every_row_carries_the_existing_drafted_tag() -> None:
    """The same tag every other drafter writes, not a second parallel marker."""
    engine = _engine("Straw reached 320 cubic meters per dry ton.", [CHUNK], ["c1"])

    result = await seeds_from_answers(engine, ["q"])  # type: ignore[arg-type]

    assert result.questions[0].tags == [DRAFTED_TAG]
    assert result.questions[0].drafted


async def test_an_answer_that_cited_nothing_is_dropped_with_a_reason() -> None:
    engine = _engine("I cannot answer that from the sources.", [CHUNK], [])

    result = await seeds_from_answers(engine, ["q"])  # type: ignore[arg-type]

    assert result.questions == []
    assert len(result.dropped) == 1
    assert "cited no sources" in result.dropped[0]
    assert "unanswerable" in result.dropped[0], "the reason should say what to do next"


async def test_a_row_that_cannot_prove_itself_relevant_is_dropped() -> None:
    """A paraphrasing answer produces a row that would score zero against itself."""
    paraphrase = _item("c1", "", "Rice straw performs well after an alkali soak.")
    engine = _engine("It roughly doubles the output.", [paraphrase], ["c1"])

    result = await seeds_from_answers(engine, ["q"])  # type: ignore[arg-type]

    assert result.questions == []
    assert "score zero against its own evidence" in result.dropped[0]


async def test_a_title_match_alone_is_enough_to_keep_a_row() -> None:
    """`is_relevant` accepts a title match, so a row with no phrases can still stand."""
    titled = _item("c1", "Anaerobic Digestion", "Rice straw performs well after an alkali soak.")
    engine = _engine("It works well.", [titled], ["c1"])

    result = await seeds_from_answers(engine, ["q"])  # type: ignore[arg-type]

    assert len(result.questions) == 1
    assert result.questions[0].evidence_phrases == []
    assert any("title alone" in note for note in result.notes)


async def test_a_dropped_row_does_not_consume_its_id() -> None:
    """Otherwise the next question with the same wording gets a needless `-2` suffix."""
    empty = _item("c1", "", "nothing matching here")
    engine = _StubEngine(
        {
            "Biogas yield?": _Answer(
                text="Unrelated prose.",
                retrieval=_Retrieval(items=[empty]),
                sources=[_Source(chunk_id="c1")],
            ),
            "Biogas yield again?": _Answer(
                text="Straw reached 320 cubic meters per dry ton.",
                retrieval=_Retrieval(items=[CHUNK]),
                sources=[_Source(chunk_id="c1")],
            ),
        }
    )

    result = await seeds_from_answers(
        engine,  # type: ignore[arg-type]
        ["Biogas yield?", "Biogas yield again?"],
    )

    assert [row.id for row in result.questions] == ["biogas-yield-again"]


async def test_ids_avoid_the_ones_already_in_the_seed_file() -> None:
    engine = _engine(
        "Straw reached 320 cubic meters per dry ton.", [CHUNK], ["c1"], question="Biogas yield?"
    )

    result = await seeds_from_answers(
        engine,  # type: ignore[arg-type]
        ["Biogas yield?"],
        taken_ids={"biogas-yield"},
    )

    assert result.questions[0].id == "biogas-yield-2"


async def test_the_dropped_count_is_reported_in_the_notes() -> None:
    engine = _engine("No citation here.", [CHUNK], [])

    result = await seeds_from_answers(engine, ["q"])  # type: ignore[arg-type]

    assert any("1 question(s) produced no usable row" in note for note in result.notes)


# --- the questions file ------------------------------------------------------


def test_blank_lines_and_comments_are_skipped(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "questions.txt"
    path.write_text("# real user questions\n\nWhat yield?\n   \nWhat cost?\n")

    assert read_questions(path) == ["What yield?", "What cost?"]


def test_a_missing_questions_file_is_a_draft_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(DraftError, match="No questions file"):
        read_questions(tmp_path / "nope.txt")


def test_a_questions_file_with_nothing_in_it_says_what_it_wanted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "questions.txt"
    path.write_text("# only a comment\n\n")

    with pytest.raises(DraftError, match="one question per line"):
        read_questions(path)


# --- the proposal file -------------------------------------------------------


def test_the_proposal_says_the_reference_answer_is_a_hypothesis() -> None:
    text = render_jsonl([SeedQuestion(id="x", question="q", tags=[DRAFTED_TAG])])

    assert text.startswith("#"), "the loader skips # lines, so the header is free"
    assert "hypotheses" in text
    assert "drafted" in text


def test_the_proposal_reads_back_through_the_real_loader(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.evals.seeds import load_seed_questions

    row = SeedQuestion(
        id="biogas-yield",
        question="What biogas yield?",
        reference_answer="About 320 cubic meters per dry ton.",
        reference_titles=["Anaerobic Digestion"],
        evidence_phrases=["320"],
        tags=[DRAFTED_TAG],
    )
    path = tmp_path / "proposed.jsonl"
    path.write_text(render_jsonl([row]), encoding="utf-8")

    loaded = load_seed_questions(path)

    assert len(loaded) == 1
    assert loaded[0].drafted
    assert loaded[0].evidence_phrases == ["320"]


# --- the real answer engine, end to end --------------------------------------


class _AnswerLLM(LLMClient):
    """Enough of a model to drive the real `AnswerEngine`, with no provider."""

    model = "mock-seed-drafting"

    async def generate_json(self, prompt, *, system=None, max_tokens=4096):  # type: ignore[no-untyped-def]
        # Compression is on in the shipped domain, so the engine asks for
        # summaries first. Keeping the number is what makes the answer citable.
        return {
            "snippets": [
                {
                    "index": 1,
                    "relevance_score": 0.95,
                    "summary": "Straw reached 320 cubic meters per dry ton.",
                }
            ]
        }

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("answer generation should stream")

    async def _stream(self):  # type: ignore[no-untyped-def]
        yield "Alkali pretreated rice straw reached 320 cubic meters per dry ton [1]."

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream()


class _StaticRetriever:
    def __init__(self) -> None:
        from pathlib import Path

        from sci_rag.domain import load_domain
        from sci_rag.retrieve import RetrievalResult

        self.domain = load_domain(Path(__file__).parents[2] / "domain")
        self.result = RetrievalResult(items=[CHUNK], traces=[], profile="deep")

    async def retrieve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self.result


async def test_the_real_answer_engine_produces_a_verified_drafted_row() -> None:
    """The stubs above test the logic; this tests that it is wired to the real thing.

    It runs the shipped answer path, including compression, so the evidence
    phrases have to survive being extracted from the FULL retrieved chunk while
    the answer was written against a summary of it. Reading phrases off the
    compressed view instead would still pass every stub test above and produce
    seed rows that score zero in a real evaluation.
    """
    from sci_rag.answer import AnswerEngine

    engine = AnswerEngine(retriever=_StaticRetriever(), llm=_AnswerLLM())  # type: ignore[arg-type]

    result = await seeds_from_answers(engine, ["What biogas yield?"])

    assert len(result.questions) == 1, result.dropped
    row = result.questions[0]
    assert row.id == "biogas-yield"
    assert row.tags == [DRAFTED_TAG]
    assert row.reference_titles == ["Anaerobic Digestion of Crop Residues"]
    assert any("320" in phrase for phrase in row.evidence_phrases)
    assert is_relevant(CHUNK, row), "the row has to match the evidence it names"
