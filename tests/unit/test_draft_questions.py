"""Drafted seed questions are model output, so they are verified in Python.

The model is asked to quote its evidence verbatim from passages it was shown.
Whether it actually did is checked here, not there: an evidence phrase that
appears in no passage of a document the question names is a fabrication, and
the row goes. What survives is tagged `drafted`, because a model-drafted
question is not expert ground truth until an expert has read it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.domain import load_domain
from sci_rag.draft import DraftError
from sci_rag.draft.questions import (
    DRAFTED_HEADER,
    draft_questions,
    parse_reply,
    render_jsonl,
    render_prompt,
    verify_grounding,
)
from sci_rag.draft.sampling import Passage, PassageSample
from sci_rag.evals.seeds import DRAFTED_TAG, SeedQuestion, load_seed_questions
from sci_rag.llm import MockLLM

REPO_ROOT = Path(__file__).parents[2]
DOMAIN_DIR = REPO_ROOT / "domain"

_SAMPLE = PassageSample(
    passages=(
        Passage(
            document_title="Colusa Basin Rice Straw Resource Assessment 2023",
            text="The basin generated 302,000 dry tons of rice straw in 2023 across "
            "141,000 harvested acres.",
        ),
        Passage(
            document_title="Anaerobic Digestion of Crop Residues: A Working Primer",
            text="Alkali pretreated rice straw reached 320 cubic meters of biogas per "
            "dry ton at 54 percent methane.",
        ),
    ),
    origin="files",
    document_count=2,
)

_GOOD_ROW = {
    "id": "rice-straw-generated",
    "question": "How much rice straw did the Colusa Basin generate in 2023?",
    "reference_answer": "About 302,000 dry tons from roughly 141,000 harvested acres.",
    "reference_titles": ["Colusa Basin Rice Straw Resource Assessment 2023"],
    "evidence_phrases": ["302,000 dry tons"],
    "tags": ["availability"],
}
_UNGROUNDED_ROW = {
    "id": "invented-number",
    "question": "How much switchgrass did the basin generate?",
    "reference_answer": "Nine hundred tons.",
    "reference_titles": ["Colusa Basin Rice Straw Resource Assessment 2023"],
    "evidence_phrases": ["900 dry tons of switchgrass"],
    "tags": ["availability"],
}
_WRONG_DOCUMENT_ROW = {
    "id": "right-phrase-wrong-document",
    "question": "What biogas yield does pretreated straw reach?",
    "reference_answer": "320 cubic meters per dry ton.",
    # The phrase is real, but it lives in the primer, not the assessment.
    "reference_titles": ["Colusa Basin Rice Straw Resource Assessment 2023"],
    "evidence_phrases": ["320 cubic meters of biogas"],
    "tags": ["conversion"],
}
_UNKNOWN_TITLE_ROW = {
    "id": "phantom-document",
    "question": "What does the phantom report say?",
    "reference_answer": "Nothing, it does not exist.",
    "reference_titles": ["A Report Nobody Wrote"],
    "evidence_phrases": ["302,000 dry tons"],
    "tags": ["availability"],
}
_PROBE_ROW = {
    "id": "switchgrass-honesty",
    "question": "What sugar yield does enzymatic hydrolysis of switchgrass achieve here?",
    "reference_answer": "The corpus does not cover switchgrass; a grounded answer says so.",
    "reference_titles": [],
    "evidence_phrases": [],
    "tags": ["unanswerable"],
}


def _reply(*rows: dict) -> str:
    return json.dumps({"questions": list(rows)})


def _questions(*rows: dict) -> list[SeedQuestion]:
    return [SeedQuestion.model_validate(row) for row in rows]


def test_the_prompt_carries_the_ontology_and_the_passages() -> None:
    domain = load_domain(DOMAIN_DIR)
    prompt = render_prompt(domain, sample=_SAMPLE, count=7)

    assert domain.name in prompt
    assert "Feedstock" in prompt, "entity types belong in the prompt"
    assert "availability" in prompt, "query classes belong in the prompt"
    assert "302,000 dry tons" in prompt, "real passage text belongs in the prompt"
    assert "7" in prompt


def test_a_non_json_reply_is_rejected() -> None:
    with pytest.raises(DraftError, match="JSON"):
        parse_reply("I am sorry, I cannot help with that.")


def test_a_wrongly_shaped_reply_is_rejected() -> None:
    with pytest.raises(DraftError):
        parse_reply(json.dumps({"questions": [{"question": "no id here"}]}))


def test_duplicate_ids_inside_one_reply_are_rejected() -> None:
    with pytest.raises(DraftError, match="duplicate"):
        parse_reply(_reply(_GOOD_ROW, _GOOD_ROW))


def test_an_ungrounded_evidence_phrase_drops_the_row() -> None:
    result = verify_grounding(_questions(_GOOD_ROW, _UNGROUNDED_ROW), _SAMPLE)

    assert [q.id for q in result.questions] == ["rice-straw-generated"]
    assert [qid for qid, _ in result.dropped] == ["invented-number"]
    assert "900 dry tons of switchgrass" in result.dropped[0][1]


def test_a_real_phrase_from_the_wrong_document_drops_the_row() -> None:
    """Grounding is per document: the phrase must be in a document the row names."""
    result = verify_grounding(_questions(_WRONG_DOCUMENT_ROW), _SAMPLE)

    assert result.questions == []
    assert [qid for qid, _ in result.dropped] == ["right-phrase-wrong-document"]


def test_a_reference_title_that_resolves_to_nothing_drops_the_row() -> None:
    result = verify_grounding(_questions(_UNKNOWN_TITLE_ROW), _SAMPLE)

    assert result.questions == []
    assert "A Report Nobody Wrote" in result.dropped[0][1]


def test_the_unanswerable_probe_survives_verification() -> None:
    result = verify_grounding(_questions(_GOOD_ROW, _PROBE_ROW), _SAMPLE)

    assert [q.id for q in result.questions] == ["rice-straw-generated", "switchgrass-honesty"]


def test_an_unanswerable_probe_may_not_claim_evidence() -> None:
    """A probe that cites a document contradicts its own purpose; the claim goes."""
    contradictory = dict(_PROBE_ROW) | {
        "reference_titles": ["Colusa Basin Rice Straw Resource Assessment 2023"],
        "evidence_phrases": ["302,000 dry tons"],
    }
    result = verify_grounding(_questions(contradictory), _SAMPLE)

    (kept,) = result.questions
    assert kept.reference_titles == []
    assert kept.evidence_phrases == []
    assert any("unanswerable" in note for note in result.notes)


def test_verification_notices_a_missing_honesty_probe() -> None:
    result = verify_grounding(_questions(_GOOD_ROW), _SAMPLE)

    assert any("unanswerable" in note for note in result.notes)


def test_whitespace_and_case_do_not_defeat_a_verbatim_quote() -> None:
    wrapped = dict(_GOOD_ROW) | {"evidence_phrases": ["302,000  Dry\nTons"]}
    result = verify_grounding(_questions(wrapped), _SAMPLE)

    assert [q.id for q in result.questions] == ["rice-straw-generated"]


async def test_drafting_tags_every_row_as_drafted() -> None:
    llm = MockLLM(responses=[_reply(_GOOD_ROW, _PROBE_ROW)])
    result = await draft_questions(
        load_domain(DOMAIN_DIR), sample=_SAMPLE, count=2, llm=llm, repair=False
    )

    assert result.questions
    for question in result.questions:
        assert DRAFTED_TAG in question.tags


async def test_a_repair_round_replaces_the_rows_that_failed() -> None:
    llm = MockLLM(responses=[_reply(_GOOD_ROW, _UNGROUNDED_ROW), _reply(_PROBE_ROW)])
    result = await draft_questions(
        load_domain(DOMAIN_DIR), sample=_SAMPLE, count=2, llm=llm, repair=True
    )

    assert len(llm.calls) == 2, "one draft call and one repair call"
    assert [q.id for q in result.questions] == ["rice-straw-generated", "switchgrass-honesty"]
    assert [qid for qid, _ in result.dropped] == ["invented-number"]


async def test_a_reply_the_model_supplies_is_used_instead_of_a_call() -> None:
    """Lane B: the reply came from an assistant the kit never spoke to."""
    llm = MockLLM(responses=["should not be used"])
    result = await draft_questions(
        load_domain(DOMAIN_DIR),
        sample=_SAMPLE,
        count=2,
        llm=llm,
        raw_reply=_reply(_GOOD_ROW),
        repair=True,
    )

    assert llm.calls == []
    assert [q.id for q in result.questions] == ["rice-straw-generated"]


def test_the_rendered_file_says_its_rows_are_unreviewed(tmp_path: Path) -> None:
    questions = [
        q.model_copy(update={"tags": [*q.tags, DRAFTED_TAG]})
        for q in _questions(_GOOD_ROW, _PROBE_ROW)
    ]
    text = render_jsonl(questions)

    assert text.startswith(DRAFTED_HEADER)
    assert "model-drafted" in DRAFTED_HEADER
    assert text.endswith("\n")

    path = tmp_path / "eval_seed_questions.jsonl"
    path.write_text(text, encoding="utf-8")
    loaded = load_seed_questions(path)
    assert [q.id for q in loaded] == ["rice-straw-generated", "switchgrass-honesty"]
    assert all(DRAFTED_TAG in q.tags for q in loaded)


def test_the_prompt_template_ships_with_the_domain() -> None:
    assert (DOMAIN_DIR / "prompts" / "seed_questions.md").exists()
