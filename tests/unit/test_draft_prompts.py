"""Localizing prompt wording, with the judge prompts walled off.

Two of the kit's prompts encode a measurement rule rather than domain wording.
The grounding judge is blind to the reference answer on purpose, and
correctness is a separate reference-based pass; a well-meaning rewrite that
merges them would not break anything visibly, it would just quietly make every
judged number mean something else. So this drafter refuses them by name, and
the refusal is tested rather than documented.

The other risk is subtler: a rewrite that reads beautifully and drops a
`$SLOT`. That template still loads and only fails at the moment it is
rendered, deep inside a pipeline run, so it is checked here instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.domain import load_domain
from sci_rag.draft import DraftError
from sci_rag.draft.prompts import (
    EDITABLE_PROMPTS,
    REFUSED_PROMPTS,
    parse_reply,
    render_prompt,
    required_slots,
    verify_rewrite,
)
from sci_rag.llm import MockLLM

REPO_ROOT = Path(__file__).parents[2]
DOMAIN_DIR = REPO_ROOT / "domain"


def test_only_the_wording_prompts_are_editable() -> None:
    assert set(EDITABLE_PROMPTS) == {"entity_extraction", "answer"}


def test_the_judge_prompts_are_refused_by_name() -> None:
    for name in ("judge_grounding", "judge_correctness", "snippet_compression", "ontology_draft"):
        assert name in REFUSED_PROMPTS
        assert REFUSED_PROMPTS[name], f"{name} needs a reason a user can read"


@pytest.mark.parametrize("name", ["judge_grounding", "judge_correctness"])
def test_rendering_a_refused_prompt_fails_with_its_reason(name: str) -> None:
    domain = load_domain(DOMAIN_DIR)

    with pytest.raises(DraftError) as exc:
        render_prompt(domain, name=name)

    assert name in str(exc.value)
    assert REFUSED_PROMPTS[name].split(".")[0] in str(exc.value)


def test_rendering_an_unknown_prompt_fails() -> None:
    domain = load_domain(DOMAIN_DIR)

    with pytest.raises(DraftError, match="entity_extraction"):
        render_prompt(domain, name="not_a_prompt")


def test_the_prompt_carries_the_current_text_and_the_required_slots() -> None:
    domain = load_domain(DOMAIN_DIR)

    prompt = render_prompt(domain, name="entity_extraction")

    assert "entity_extraction" in prompt
    assert "$ENTITY_TYPES" in prompt, "the slots the rewrite must keep are named"
    assert "Never invent facts" in prompt, "the current text is what gets rewritten"
    assert domain.name in prompt


def test_required_slots_are_read_off_the_current_template() -> None:
    slots = required_slots((DOMAIN_DIR / "prompts" / "entity_extraction.md").read_text())

    assert slots == {"DOMAIN_NAME", "ENTITY_TYPES", "RELATION_TYPES", "PASSAGES"}


def test_a_rewrite_that_drops_a_slot_is_rejected() -> None:
    original = (DOMAIN_DIR / "prompts" / "entity_extraction.md").read_text()
    without_passages = original.replace("$PASSAGES", "the passages")

    with pytest.raises(DraftError, match="PASSAGES"):
        verify_rewrite(original, without_passages)


def test_a_rewrite_that_keeps_every_slot_is_accepted() -> None:
    original = (DOMAIN_DIR / "prompts" / "entity_extraction.md").read_text()
    reworded = original.replace("knowledge graph", "knowledge network")

    verify_rewrite(original, reworded)


def test_a_rewrite_that_will_not_render_is_rejected() -> None:
    """A stray `$` is a template that only explodes mid-pipeline."""
    original = (DOMAIN_DIR / "prompts" / "entity_extraction.md").read_text()
    broken = original + "\n\nCosts are in $USD per ton.\n"

    with pytest.raises(DraftError):
        verify_rewrite(original, broken)


def test_an_empty_rewrite_is_rejected() -> None:
    original = (DOMAIN_DIR / "prompts" / "entity_extraction.md").read_text()

    with pytest.raises(DraftError):
        verify_rewrite(original, "   ")


def test_a_reply_returns_the_rewritten_template() -> None:
    text = parse_reply(json.dumps({"prompt": "You extract $ENTITY_TYPES from $PASSAGES."}))

    assert text == "You extract $ENTITY_TYPES from $PASSAGES."


def test_a_reply_without_a_prompt_is_rejected() -> None:
    with pytest.raises(DraftError, match="prompt"):
        parse_reply(json.dumps({"text": "wrong key"}))


def test_a_non_json_reply_is_rejected() -> None:
    with pytest.raises(DraftError, match="JSON"):
        parse_reply("here is your prompt")


async def test_drafting_verifies_before_returning() -> None:
    from sci_rag.draft.prompts import draft_prompt

    domain = load_domain(DOMAIN_DIR)
    llm = MockLLM(responses=[json.dumps({"prompt": "Extract from $PASSAGES only."})])

    with pytest.raises(DraftError, match="ENTITY_TYPES"):
        await draft_prompt(domain, name="entity_extraction", llm=llm)


def test_the_prompt_template_ships_with_the_domain() -> None:
    assert (DOMAIN_DIR / "prompts" / "prompt_localization.md").exists()
