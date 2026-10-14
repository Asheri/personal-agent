"""LLM-drafted ontologies are model output, so they are validated before use.

A malformed draft has to fail loudly rather than write junk YAML that only
breaks later, when the graph extractor reads it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.llm import MockLLM
from sci_rag.scaffold.ontology import OntologyDraftError, draft_ontology

DOMAIN_DIR = Path(__file__).parents[2] / "domain"

_GOOD_DRAFT = json.dumps(
    {
        "entity_types": [
            {"name": "Membrane", "description": "A separation layer"},
            {"name": "Contaminant", "description": "Something removed from water"},
        ],
        "relation_types": [{"name": "REMOVES", "description": "Membrane removes contaminant"}],
        "query_classes": [
            {
                "name": "performance",
                "keywords": ["flux", "rejection"],
                "hyde_instruction": "Write a performance summary.",
            }
        ],
    }
)


async def test_draft_parses_a_well_formed_response() -> None:
    llm = MockLLM(responses=[_GOOD_DRAFT])
    config = await draft_ontology(
        DOMAIN_DIR, project_name="Membrane KB", description="Membrane chemistry", llm=llm
    )
    assert [e.name for e in config.entity_types] == ["Membrane", "Contaminant"]
    assert [r.name for r in config.relation_types] == ["REMOVES"]
    assert [q.name for q in config.query_classes] == ["performance"]


async def test_the_prompt_carries_the_domain_description() -> None:
    llm = MockLLM(responses=[_GOOD_DRAFT])
    await draft_ontology(
        DOMAIN_DIR, project_name="Membrane KB", description="Membrane chemistry", llm=llm
    )
    assert "Membrane chemistry" in llm.calls[0]["prompt"]


async def test_a_non_json_response_is_rejected() -> None:
    llm = MockLLM(responses=["I am sorry, I cannot help with that."])
    with pytest.raises(OntologyDraftError):
        await draft_ontology(DOMAIN_DIR, project_name="KB", description="d", llm=llm)


async def test_a_wrongly_shaped_response_is_rejected() -> None:
    """Valid JSON, wrong schema: entity_types must be objects with names."""
    llm = MockLLM(responses=[json.dumps({"entity_types": ["Membrane"], "relation_types": []})])
    with pytest.raises(OntologyDraftError):
        await draft_ontology(DOMAIN_DIR, project_name="KB", description="d", llm=llm)


async def test_an_empty_ontology_is_rejected() -> None:
    """A draft with no entity types is a failed draft, not a blank ontology."""
    llm = MockLLM(
        responses=[json.dumps({"entity_types": [], "relation_types": [], "query_classes": []})]
    )
    with pytest.raises(OntologyDraftError, match="entity type"):
        await draft_ontology(DOMAIN_DIR, project_name="KB", description="d", llm=llm)


def test_the_draft_prompt_template_ships_with_the_domain() -> None:
    assert (DOMAIN_DIR / "prompts" / "ontology_draft.md").exists()
