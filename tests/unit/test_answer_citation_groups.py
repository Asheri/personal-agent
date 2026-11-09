"""Real-model citation lists must mark the same sources in answer metadata."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sci_rag.answer import AnswerEngine
from sci_rag.domain import load_domain
from sci_rag.llm import MockLLM
from sci_rag.retrieve import RetrievalResult, RetrievedItem


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Supported claim [1, 2].", {1, 2}),
        ("Supported claim [1-2].", {1, 2}),
        ("Supported claim [2][99].", {2}),
        ("Unbounded request [1-999999].", {1, 2}),
    ],
)
async def test_answer_metadata_recognizes_citation_groups(text, expected):
    result = RetrievalResult(
        items=[
            RetrievedItem(
                kind="chunk",
                id=str(i),
                score=1,
                layers=["keyword"],
                title=f"source {i}",
                content="Literal controlled evidence.",
                document_id=f"doc-{i}",
                license_class="public",
            )
            for i in [1, 2]
        ],
        traces=[],
        profile="deep",
    )
    retriever = SimpleNamespace(
        domain=load_domain(Path(__file__).parents[2] / "domain"),
        retrieve=AsyncMock(return_value=result),
    )
    answer = await AnswerEngine(retriever=retriever, llm=MockLLM(responses=[text])).answer(
        "question", include_compression=False
    )
    assert {s.index for s in answer.cited_sources} == expected
    assert answer.text == text
