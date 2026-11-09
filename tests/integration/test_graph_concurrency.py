"""Concurrent extraction: same graph, one row per concept, no duplicate evidence.

``extract_graph(concurrency=...)`` is a throughput setting. These tests pin the
invariant that makes it safe to raise: batches overlap while their writes stay
serialized behind the document-write lock, so two batches that meet the same
concept merge into one entity instead of inserting a second row.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, select

from sci_rag.db import Chunk, KgEntity, KgRelationship, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.graph import extract_graph
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import LLMClient

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"

#: Two documents with the same body. Both batches therefore report the same four
#: concepts with evidence they can actually cite, which is the race this file
#: guards against: two batches meeting one concept at the same time.
NOTE = (
    "Rice straw is produced in Colusa County after harvest and can be digested "
    "to biogas through anaerobic digestion. Rice straw is also called paddy straw "
    "or rice residue. Anaerobic digestion yields biogas, and biogas production "
    "creates demand for straw."
)

EXTRACTION = {
    "entities": [
        {
            "name": "rice straw",
            "type": "Feedstock",
            "description": "post-harvest residue",
            "passages": [1],
            "aliases": ["paddy straw"],
        },
        {"name": "Colusa County", "type": "Region", "description": "rice region", "passages": [1]},
        {
            "name": "anaerobic digestion",
            "type": "ConversionProcess",
            "description": "biological conversion",
            "passages": [1],
        },
        {"name": "biogas", "type": "Product", "description": "methane-rich gas", "passages": [1]},
    ],
    "relationships": [
        {
            "source": "rice straw",
            "target": "Colusa County",
            "type": "LOCATED_IN",
            "evidence": "produced in Colusa County",
            "passage": 1,
        },
        {
            "source": "rice straw",
            "target": "anaerobic digestion",
            "type": "CONVERTED_BY",
            "evidence": "digested to biogas",
            "passage": 1,
        },
        {
            "source": "anaerobic digestion",
            "target": "biogas",
            "type": "PRODUCES",
            "evidence": "yields biogas",
            "passage": 1,
        },
        {
            "source": "biogas",
            "target": "rice straw",
            "type": "AFFECTS",
            "evidence": "creates demand for straw",
            "passage": 1,
        },
    ],
}

ENTITY_NAMES = sorted(entity["name"] for entity in EXTRACTION["entities"])
TRIPLE_COUNT = len(EXTRACTION["relationships"])


class SlowExtractionLLM(LLMClient):
    """Answer every extraction prompt, slowly enough for batches to overlap."""

    def __init__(self, delay_s: float = 0.05) -> None:
        self.delay_s = delay_s
        self.live = 0
        self.peak = 0
        self.calls = 0

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        self.live += 1
        self.peak = max(self.peak, self.live)
        self.calls += 1
        try:
            await asyncio.sleep(self.delay_s)
            return json.dumps(deepcopy(EXTRACTION))
        finally:
            self.live -= 1

    async def _stream_impl(self, text: str) -> AsyncIterator[str]:  # type: ignore[no-untyped-def]
        yield text

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream_impl("unused")


@pytest.fixture()
def corpus(tmp_path: Path) -> list[CorpusEntry]:
    entries = []
    for name, title in (("a.md", "Rice Straw in Colusa County"), ("b.md", "Digestion Notes")):
        path = tmp_path / name
        path.write_text(f"# {title}\n\n{NOTE}\n", encoding="utf-8")
        entries.append(CorpusEntry(path=path, license_class="public", source="demo"))
    return entries


@pytest.mark.parametrize("concurrency", [1, 2, 4])
async def test_concurrency_stores_one_row_per_concept(
    concurrency: int, clean_tables, corpus, local_embedder
) -> None:  # type: ignore[no-untyped-def]
    llm = SlowExtractionLLM()
    await ingest_entries(corpus, embedder=local_embedder)
    stats = await extract_graph(
        session_factory=get_session_factory(),
        llm=llm,
        domain=load_domain(DOMAIN_DIR),
        batch_size=1,
        rate_limit_s=0,
        concurrency=concurrency,
    )

    async with get_session_factory()() as session:
        entities = (await session.execute(select(KgEntity))).scalars().all()
        relationships = (await session.execute(select(KgRelationship))).scalars().all()
        unstamped = await session.scalar(
            select(func.count(Chunk.id)).where(Chunk.graph_extracted_at.is_(None))
        )

    assert stats.batches_failed == 0
    assert stats.chunks_processed >= len(corpus)
    # One row per concept: a second batch that met the same name merged into it.
    assert sorted(entity.name for entity in entities) == ENTITY_NAMES
    # Evidence from both documents landed on that single row.
    assert all(len(set(entity.document_ids)) == len(corpus) for entity in entities)
    assert len(
        {(r.source_entity_id, r.target_entity_id, r.relation_type) for r in relationships}
    ) == (TRIPLE_COUNT)
    assert len(relationships) == TRIPLE_COUNT * len(corpus)
    assert unstamped == 0


async def test_concurrency_keeps_several_model_calls_in_flight(
    clean_tables, corpus, local_embedder
) -> None:  # type: ignore[no-untyped-def]
    llm = SlowExtractionLLM()
    await ingest_entries(corpus, embedder=local_embedder)
    await extract_graph(
        session_factory=get_session_factory(),
        llm=llm,
        domain=load_domain(DOMAIN_DIR),
        batch_size=1,
        rate_limit_s=0,
        concurrency=len(corpus),
    )
    # Without overlapping calls this setting would be a no-op, so the peak is
    # the assertion that the flag does anything at all.
    assert llm.peak == len(corpus)


async def test_serial_extraction_never_overlaps(clean_tables, corpus, local_embedder) -> None:  # type: ignore[no-untyped-def]
    llm = SlowExtractionLLM(delay_s=0.0)
    await ingest_entries(corpus, embedder=local_embedder)
    await extract_graph(
        session_factory=get_session_factory(),
        llm=llm,
        domain=load_domain(DOMAIN_DIR),
        batch_size=1,
        rate_limit_s=0,
    )
    assert llm.peak == 1
