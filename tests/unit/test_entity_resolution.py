from __future__ import annotations

import json

import pytest

from sci_rag.graph.resolve import EntityRecord, classify_entity_pairs, resolve_ambiguous_pairs
from sci_rag.llm import LLMClient


def entity(
    entity_id: str,
    name: str,
    entity_type: str = "Feedstock",
    aliases: tuple[str, ...] = (),
) -> EntityRecord:
    return EntityRecord(entity_id, name, entity_type, aliases, (), ())


def test_exact_alias_match_is_automatic() -> None:
    automatic, ambiguous = classify_entity_pairs(
        [
            entity("a", "rice straw", aliases=("paddy straw",)),
            entity("b", "Paddy Straw"),
        ]
    )

    assert [(item.method, item.confidence, item.merge) for item in automatic] == [
        ("alias", 1.0, True)
    ]
    assert ambiguous == []


def test_high_fuzzy_match_is_automatic() -> None:
    automatic, ambiguous = classify_entity_pairs(
        [entity("a", "anaerobic digestion"), entity("b", "anaerobic digestions")],
        fuzzy_threshold=0.90,
    )

    assert len(automatic) == 1
    assert automatic[0].method == "fuzzy"
    assert automatic[0].merge is True
    assert ambiguous == []


def test_different_entity_types_never_fuzzy_match() -> None:
    automatic, ambiguous = classify_entity_pairs(
        [
            entity("a", "rice straw", "Feedstock"),
            entity("b", "rice straws", "Product"),
        ],
        fuzzy_threshold=0.80,
        ambiguous_threshold=0.70,
    )

    assert automatic == []
    assert ambiguous == []


class DecisionLLM(LLMClient):
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        self.calls += 1
        return json.dumps(self.payload)

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        raise NotImplementedError


@pytest.mark.asyncio
async def test_llm_decline_does_not_merge_and_candidates_are_batched() -> None:
    pairs = classify_entity_pairs(
        [entity("a", "rice residue"), entity("b", "rice residues")],
        fuzzy_threshold=0.999,
        ambiguous_threshold=0.80,
    )[1]
    llm = DecisionLLM(
        {
            "decisions": [
                {
                    "left_id": "a",
                    "right_id": "b",
                    "merge": False,
                    "confidence": 0.93,
                }
            ]
        }
    )

    decisions, failures = await resolve_ambiguous_pairs(pairs, llm)

    assert llm.calls == 1
    assert pairs[0].left_name == "rice residue"
    assert pairs[0].right_name == "rice residues"
    assert failures == 0
    assert len(decisions) == 1
    assert decisions[0].method == "llm"
    assert decisions[0].merge is False


@pytest.mark.asyncio
async def test_malformed_llm_response_is_a_recorded_failure() -> None:
    pairs = classify_entity_pairs(
        [entity("a", "rice residue"), entity("b", "rice residues")],
        fuzzy_threshold=0.999,
        ambiguous_threshold=0.80,
    )[1]
    llm = DecisionLLM({"unexpected": []})

    decisions, failures = await resolve_ambiguous_pairs(pairs, llm)

    assert decisions == []
    assert failures == 1
