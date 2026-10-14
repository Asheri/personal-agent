"""What happens when one batch's model response is unusable, every time.

The documented `make demo-cloud` route stopped at graph extraction because a
single ten-chunk response was invalid JSON. The command was right to leave
that batch unprocessed, and its only advice was to rerun. An exact rerun hit
the same batch and failed at the same parse position, because nothing about
the request had changed. Reducing the batch to five completed all ten chunks.

That is the shape of a truncated response: a batch large enough that the
model's JSON exceeds the output cap produces the same broken output on every
identical attempt, and halving the batch halves the JSON it has to write. So
the recovery is to try smaller, deterministically, rather than to try again.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select

from sci_rag.db import Chunk, KgEntity, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.graph import extract_graph
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import LLMClient

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"


def _extraction(passage_count: int) -> str:
    """A valid response naming one entity per passage."""
    return json.dumps(
        {
            "entities": [
                {
                    "name": f"feedstock {index}",
                    "type": "Feedstock",
                    "description": "a residue",
                    "passages": [index],
                }
                for index in range(1, passage_count + 1)
            ],
            "relationships": [],
        }
    )


class TruncatingLLM(LLMClient):
    """Answers only when the batch is small enough to fit the output cap.

    Above the threshold the response is cut off mid-object, which is what a
    response truncated at ``max_tokens`` looks like to the parser, and what
    the audit saw as a ``JSONDecodeError`` at a stable position.
    """

    def __init__(self, *, max_passages: int) -> None:
        self.max_passages = max_passages
        self.batch_sizes: list[int] = []

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        if "knowledge graph for this domain" not in prompt:
            return "unused"
        passage_count = sum(1 for line in prompt.splitlines() if line[:1].isdigit())
        self.batch_sizes.append(passage_count)
        body = _extraction(passage_count)
        if passage_count > self.max_passages:
            return body[: len(body) // 2]
        return body

    async def _stream_impl(self, text: str) -> AsyncIterator[str]:
        yield text

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream_impl("unused")


@pytest.fixture()
async def ten_chunks(clean_tables, local_embedder, tmp_path: Path):  # type: ignore[no-untyped-def]
    entries = []
    for index in range(10):
        path = tmp_path / f"doc-{index:02d}.md"
        path.write_text(
            f"# Residue {index}\n\nResidue {index} is collected after harvest and can be "
            "digested to biogas through anaerobic digestion.",
            encoding="utf-8",
        )
        entries.append(CorpusEntry(path=path, license_class="public", source="tests"))
    await ingest_entries(entries, embedder=local_embedder)


async def test_a_batch_the_model_cannot_answer_whole_is_retried_smaller(ten_chunks) -> None:  # type: ignore[no-untyped-def]
    """Ten chunks, a model that can only answer five, and no manual override."""
    llm = TruncatingLLM(max_passages=5)

    stats = await extract_graph(
        session_factory=get_session_factory(),
        llm=llm,
        domain=load_domain(DOMAIN_DIR),
        batch_size=10,
        rate_limit_s=0,
    )

    assert stats.chunks_processed == 10
    assert stats.batches_failed == 0
    # Deterministic halving: the whole batch, then each half.
    assert llm.batch_sizes == [10, 5, 5]

    async with get_session_factory()() as session:
        unstamped = (
            (await session.execute(select(Chunk).where(Chunk.graph_extracted_at.is_(None))))
            .scalars()
            .all()
        )
        entities = (await session.execute(select(KgEntity))).scalars().all()
    assert unstamped == []
    assert entities


async def test_a_chunk_the_model_never_answers_stays_unprocessed(ten_chunks) -> None:  # type: ignore[no-untyped-def]
    """Recovery is bounded. A single chunk that still fails is not guessed at.

    Splitting stops at one, the chunk keeps its null stamp so a later run
    retries it, and the command still reports a failure rather than a silent
    partial graph.
    """
    llm = TruncatingLLM(max_passages=0)

    stats = await extract_graph(
        session_factory=get_session_factory(),
        llm=llm,
        domain=load_domain(DOMAIN_DIR),
        batch_size=10,
        rate_limit_s=0,
    )

    assert stats.chunks_processed == 0
    assert stats.batches_failed == 10, "one failure per chunk that could not be answered"
    assert min(llm.batch_sizes) == 1, "the split has to reach a single chunk"
    assert 1 not in set(llm.batch_sizes[:1]), "and it has to start from the whole batch"

    async with get_session_factory()() as session:
        stamped = (
            (await session.execute(select(Chunk).where(Chunk.graph_extracted_at.is_not(None))))
            .scalars()
            .all()
        )
    assert stamped == [], "a chunk with no valid extraction must stay unstamped"
