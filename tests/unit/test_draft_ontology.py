"""Drafting an ontology against the corpus, not against a one-line description.

The wizard's cold draft is a guess made before any document exists. Once a
corpus is on disk the field's own vocabulary is right there, and the useful
question changes from "what might this field contain" to "what do these
documents actually talk about". These tests cover both routes, the refinement
that reports what it would remove and why, and the line that matters most:
the tuned `retrieval:` and `compression:` blocks are numbers an ablation
earned, not domain semantics, so a redrafted ontology never touches them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from sci_rag.domain import DomainConfig, load_domain
from sci_rag.draft import DraftError
from sci_rag.draft.ontology import (
    NO_EXISTING_ONTOLOGY,
    DraftedOntology,
    apply_refinement,
    draft_from_corpus,
    parse_reply,
    render_prompt,
    render_yaml,
    summarize_change,
)
from sci_rag.draft.sampling import Passage, PassageSample
from sci_rag.llm import MockLLM

REPO_ROOT = Path(__file__).parents[2]
DOMAIN_DIR = REPO_ROOT / "domain"

_SAMPLE = PassageSample(
    passages=(
        Passage(
            document_title="Colusa Basin Rice Straw Resource Assessment 2023",
            text="The basin generated 302,000 dry tons of rice straw in 2023.",
        ),
        Passage(
            document_title="Anaerobic Digestion of Crop Residues: A Working Primer",
            text="Alkali pretreated rice straw reached 320 cubic meters of biogas per dry ton.",
        ),
    ),
    origin="corpus",
    document_count=2,
)

_FULL_REPLY = json.dumps(
    {
        "entity_types": [
            {"name": "Feedstock", "description": "A residue stream"},
            {
                "name": "ConversionProcess",
                "description": "A process turning feedstock into products",
            },
            {"name": "Property", "description": "A measured characteristic"},
        ],
        "relation_types": [{"name": "CONVERTED_BY", "description": "Feedstock is converted by"}],
        "query_classes": [
            {
                "name": "availability",
                "keywords": ["tons", "supply"],
                "hyde_instruction": "Write a resource assessment passage.",
            }
        ],
    }
)

_REFINE_REPLY = json.dumps(
    {
        "additions": {
            "entity_types": [{"name": "Pretreatment", "description": "A step before conversion"}],
            "relation_types": [],
            "query_classes": [],
        },
        "removals": [
            {
                "kind": "entity_type",
                "name": "Equipment",
                "reason": "no sampled passage names machinery",
            }
        ],
    }
)


def test_the_prompt_carries_the_corpus_and_the_existing_ontology() -> None:
    domain = load_domain(DOMAIN_DIR)
    prompt = render_prompt(domain, sample=_SAMPLE, existing=domain.config)

    assert domain.name in prompt
    assert "302,000 dry tons" in prompt
    assert "Feedstock" in prompt, "the ontology being refined belongs in the prompt"


def test_a_fresh_draft_says_there_is_no_ontology_yet() -> None:
    domain = load_domain(DOMAIN_DIR)
    prompt = render_prompt(domain, sample=_SAMPLE, existing=None)

    assert "302,000 dry tons" in prompt
    assert NO_EXISTING_ONTOLOGY in prompt
    # `ConversionProcess` is in the shipped ontology and in none of the
    # template's own examples, so its absence proves the block was not filled.
    assert "ConversionProcess" not in prompt


def test_a_full_reply_validates_through_the_real_model() -> None:
    result = parse_reply(_FULL_REPLY)

    assert isinstance(result, DraftedOntology)
    assert [e.name for e in result.entity_types] == [
        "Feedstock",
        "ConversionProcess",
        "Property",
    ]
    assert result.removals == []


def test_a_refinement_reply_carries_removals_with_reasons() -> None:
    result = parse_reply(_REFINE_REPLY)

    assert [e.name for e in result.entity_types] == ["Pretreatment"]
    assert result.removals == [("entity_type", "Equipment", "no sampled passage names machinery")]


def test_a_non_json_reply_is_rejected() -> None:
    with pytest.raises(DraftError, match="JSON"):
        parse_reply("I am sorry")


def test_a_wrongly_shaped_reply_is_rejected() -> None:
    with pytest.raises(DraftError):
        parse_reply(json.dumps({"entity_types": ["Feedstock"]}))


def test_an_empty_draft_is_rejected() -> None:
    with pytest.raises(DraftError, match="entity type"):
        parse_reply(json.dumps({"entity_types": [], "relation_types": [], "query_classes": []}))


def test_a_refinement_adds_and_removes_against_the_current_ontology() -> None:
    current = load_domain(DOMAIN_DIR).config
    assert any(e.name == "Equipment" for e in current.entity_types)

    revised = apply_refinement(current, parse_reply(_REFINE_REPLY))

    names = [e.name for e in revised.entity_types]
    assert "Pretreatment" in names
    assert "Equipment" not in names
    assert "Feedstock" in names, "untouched types survive a refinement"


def test_a_refinement_never_empties_the_ontology() -> None:
    """A model asking to remove everything is a bad refinement, not an instruction."""
    current = load_domain(DOMAIN_DIR).config
    wipe = json.dumps(
        {
            "additions": {"entity_types": [], "relation_types": [], "query_classes": []},
            "removals": [
                {"kind": "entity_type", "name": e.name, "reason": "unused"}
                for e in current.entity_types
            ],
        }
    )

    with pytest.raises(DraftError, match="entity type"):
        apply_refinement(current, parse_reply(wipe))


def test_the_tuned_blocks_survive_a_redraft() -> None:
    """`retrieval:` and `compression:` are numbers an ablation earned."""
    current = load_domain(DOMAIN_DIR).config
    tuned = current.model_copy(deep=True)
    tuned.retrieval.weights["vector"] = 9.5
    tuned.retrieval.rrf_k = 17
    tuned.compression.enabled = True

    merged = apply_refinement(tuned, parse_reply(_FULL_REPLY), replace=True)

    assert merged.retrieval.weights["vector"] == 9.5
    assert merged.retrieval.rrf_k == 17
    assert merged.compression.enabled is True
    assert [e.name for e in merged.entity_types] == [
        "Feedstock",
        "ConversionProcess",
        "Property",
    ]


def test_the_proposed_yaml_reloads_as_the_same_config(tmp_path: Path) -> None:
    current = load_domain(DOMAIN_DIR).config
    merged = apply_refinement(current, parse_reply(_FULL_REPLY), replace=True)

    path = tmp_path / "domain.yaml"
    path.write_text(render_yaml(merged), encoding="utf-8")
    reloaded = DomainConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    assert reloaded == merged


def test_the_summary_names_what_changed() -> None:
    current = load_domain(DOMAIN_DIR).config
    merged = apply_refinement(current, parse_reply(_REFINE_REPLY))

    lines = summarize_change(current, merged)

    assert any("Pretreatment" in line and "+" in line for line in lines)
    assert any("Equipment" in line and "-" in line for line in lines)


async def test_drafting_from_the_corpus_calls_the_model_once() -> None:
    domain = load_domain(DOMAIN_DIR)
    llm = MockLLM(responses=[_FULL_REPLY])

    result = await draft_from_corpus(domain, sample=_SAMPLE, existing=None, llm=llm)

    assert len(llm.calls) == 1
    assert [e.name for e in result.entity_types] == [
        "Feedstock",
        "ConversionProcess",
        "Property",
    ]


async def test_a_supplied_reply_is_used_instead_of_a_call() -> None:
    domain = load_domain(DOMAIN_DIR)
    llm = MockLLM(responses=["should not be used"])

    result = await draft_from_corpus(
        domain, sample=_SAMPLE, existing=None, llm=llm, raw_reply=_FULL_REPLY
    )

    assert llm.calls == []
    assert [e.name for e in result.entity_types] == [
        "Feedstock",
        "ConversionProcess",
        "Property",
    ]


def test_the_prompt_template_ships_with_the_domain() -> None:
    assert (DOMAIN_DIR / "prompts" / "ontology_from_corpus.md").exists()
