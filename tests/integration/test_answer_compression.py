"""Answer assembly uses compressed text without changing citation provenance."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from sci_rag.answer import AnswerEngine
from sci_rag.domain import load_domain
from sci_rag.llm import LLMClient
from sci_rag.retrieve import RetrievalResult, RetrievedItem

pytestmark = pytest.mark.integration
DOMAIN_DIR = Path(__file__).parents[2] / "domain"


class StaticRetriever:
    def __init__(self) -> None:
        self.domain = load_domain(DOMAIN_DIR)
        self.result = RetrievalResult(
            items=[
                RetrievedItem(
                    kind="chunk",
                    id="chunk-1",
                    score=1.0,
                    layers=["keyword"],
                    title="Measured study",
                    content=("Background material. " * 80) + "Yield was 42 kg per tonne.",
                    document_id="doc-1",
                    section_path="Results",
                    citation="Example et al. (2026)",
                    license_class="public",
                )
            ],
            traces=[],
            profile="interactive",
        )

    async def retrieve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self.result


class AnswerCompressionLLM(LLMClient):
    model = "mock-compression"

    def __init__(self) -> None:
        self.answer_prompt = ""

    async def generate_json(self, prompt: str, *, system=None, max_tokens=4096):  # type: ignore[no-untyped-def]
        return {
            "snippets": [
                {"index": 1, "relevance_score": 0.95, "summary": "Yield was 42 kg per tonne."}
            ]
        }

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("answer generation should stream")

    async def _stream(self) -> AsyncIterator[str]:
        yield "The measured yield was 42 kg per tonne [1]."

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        self.answer_prompt = prompt
        return self._stream()


@pytest.mark.asyncio
async def test_compression_rewrites_the_prompt_and_preserves_citations() -> None:
    """The compression path itself, asked for explicitly.

    Whether the shipped domain turns it on is an evidence-gated tuning
    decision that flips with the benchmark (see docs/benchmarks.md), so this
    passes the flag rather than depending on today's default. The default is
    covered separately below.
    """
    retriever = StaticRetriever()
    llm = AnswerCompressionLLM()
    engine = AnswerEngine(retriever=retriever, llm=llm)  # type: ignore[arg-type]

    result = await engine.answer("What yield was measured?", include_compression=True)

    assert "Yield was 42 kg per tonne." in llm.answer_prompt
    assert "Background material." not in llm.answer_prompt
    assert result.sources[0].index == 1
    assert result.sources[0].chunk_id == "chunk-1"
    assert result.sources[0].cited is True
    assert result.retrieval.items[0].content.startswith("Background material.")
    assert result.prompt_retrieval.items[0].content == "Yield was 42 kg per tonne."
    assert result.prompt_tokens_before > result.prompt_tokens_after
    assert result.compression_failure_count == 0


async def test_the_shipped_domain_default_is_what_actually_runs() -> None:
    """Whatever domain.yaml says, the engine has to honour it unasked.

    This is the test that would have caught a domain profile whose committed
    default disagreed with what answering actually did.
    """
    from pathlib import Path

    from sci_rag.config import get_settings
    from sci_rag.domain import load_domain

    configured = load_domain(Path(get_settings().domain_dir)).config.compression.enabled

    retriever = StaticRetriever()
    llm = AnswerCompressionLLM()
    engine = AnswerEngine(retriever=retriever, llm=llm)  # type: ignore[arg-type]

    result = await engine.answer("What yield was measured?")

    compressed = result.prompt_tokens_before > result.prompt_tokens_after
    assert compressed is configured, (
        f"domain.yaml sets compression.enabled={configured}, "
        f"but answering {'compressed' if compressed else 'did not compress'}"
    )
