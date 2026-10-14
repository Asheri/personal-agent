"""Contextual snippet compression is conservative around untrusted model output."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from sci_rag.answer.compress import SnippetCompressor
from sci_rag.domain import load_domain
from sci_rag.llm import LLMClient
from sci_rag.retrieve import RetrievedItem

DOMAIN_DIR = Path(__file__).parents[2] / "domain"


def _item(index: int, content: str) -> RetrievedItem:
    return RetrievedItem(
        kind="chunk",
        id=f"chunk-{index}",
        score=1.0,
        layers=["vector"],
        title=f"Paper {index}",
        content=content,
        document_id=f"doc-{index}",
        license_class="public",
    )


class CompressionLLM(LLMClient):
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    async def generate_json(self, prompt: str, *, system=None, max_tokens=4096):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("compression must use generate_json")

    def stream(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048
    ) -> AsyncIterator[str]:  # type: ignore[no-untyped-def]
        raise AssertionError("compression does not stream")


@pytest.mark.asyncio
async def test_compression_scores_summarizes_and_drops_below_floor() -> None:
    llm = CompressionLLM(
        {
            "snippets": [
                {"index": 1, "relevance_score": 0.9, "summary": "Relevant measurement."},
                {"index": 2, "relevance_score": 0.2, "summary": "Off topic."},
            ]
        }
    )
    compressor = SnippetCompressor(load_domain(DOMAIN_DIR), llm)

    result = await compressor.compress(
        "What was measured?",
        [_item(1, "Long relevant source text."), _item(2, "Unrelated source text.")],
        relevance_floor=0.5,
        max_tokens_per_chunk=40,
    )

    assert [item.id for item in result.items] == ["chunk-1"]
    assert result.items[0].content == "Relevant measurement."
    assert result.dropped_count == 1
    assert result.failure_count == 0
    assert "What was measured?" in llm.prompts[0]
    assert "Long relevant source text." in llm.prompts[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"not_snippets": []},
        {"snippets": [{"index": 1, "relevance_score": "high", "summary": "guess"}]},
        {"snippets": [{"index": 1, "relevance_score": True, "summary": "guess"}]},
        RuntimeError("provider unavailable"),
    ],
)
async def test_malformed_or_failed_compression_falls_back_to_full_text(payload: object) -> None:
    llm = CompressionLLM(payload)
    original = _item(1, "The complete source must survive a bad response.")
    compressor = SnippetCompressor(load_domain(DOMAIN_DIR), llm)

    result = await compressor.compress(
        "question",
        [original],
        relevance_floor=0.5,
        max_tokens_per_chunk=40,
    )

    assert result.items[0].content == original.content
    assert result.failure_count == 1
    assert result.dropped_count == 0


@pytest.mark.asyncio
async def test_community_items_pass_through_without_model_authority_to_drop_them() -> None:
    llm = CompressionLLM({"snippets": []})
    community = RetrievedItem(
        kind="community",
        id="community-1",
        score=1.0,
        layers=["community"],
        title="Overview",
        content="Scoped only when retrieval permits it.",
        license_class="public",
    )

    result = await SnippetCompressor(load_domain(DOMAIN_DIR), llm).compress(
        "question",
        [community],
        relevance_floor=0.5,
        max_tokens_per_chunk=40,
    )

    assert result.items == [community]
    assert result.failure_count == 0
    assert llm.prompts == []
