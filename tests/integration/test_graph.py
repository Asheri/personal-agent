"""Graph build + graph-powered retrieval, offline via scripted mocks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, select

from sci_rag.db import Chunk, KgCommunity, KgEntity, KgRelationship, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.graph import build_communities, extract_graph, resolve_entities
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import LLMClient
from sci_rag.retrieve import RetrievalScope, Retriever

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"

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
            "confidence": 0.82,
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


class ScriptedLLM(LLMClient):
    """Extraction prompts get the scripted graph; everything else gets prose."""

    def __init__(
        self,
        query_entities: list[str] | None = None,
        extraction: dict | None = None,
    ) -> None:
        self.query_entities = query_entities or []
        self.extraction = extraction or EXTRACTION

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        if "knowledge graph for this domain" in prompt:
            return json.dumps(self.extraction)
        if '"entities"' in prompt:
            names = ", ".join(f'"{e}"' for e in self.query_entities)
            return f'{{"entities": [{names}]}}'
        return "Rice straw availability and biogas production form one connected theme."

    async def _stream_impl(self, text: str) -> AsyncIterator[str]:
        yield text

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream_impl("unused")


@pytest.fixture()
def corpus(tmp_path: Path) -> list[CorpusEntry]:
    rice = tmp_path / "rice.md"
    rice.write_text(
        "# Rice Straw in Colusa County\n\nRice straw is produced in Colusa County after "
        "harvest and can be digested to biogas through anaerobic digestion."
    )
    almond = tmp_path / "almond.md"
    almond.write_text(
        "# Almond Prunings\n\nAlmond orchards are pruned each winter and the chipped "
        "prunings can be used as boiler fuel or soil amendment."
    )
    return [
        CorpusEntry(path=rice, license_class="public", source="demo"),
        CorpusEntry(path=almond, license_class="public", source="demo"),
    ]


async def _build_graph(corpus, local_embedder, llm) -> None:  # type: ignore[no-untyped-def]
    await ingest_entries(corpus, embedder=local_embedder)
    await extract_graph(
        session_factory=get_session_factory(),
        llm=llm,
        domain=load_domain(DOMAIN_DIR),
        rate_limit_s=0,
    )


async def test_extraction_populates_graph_with_provenance(clean_tables, corpus, local_embedder):  # type: ignore[no-untyped-def]
    llm = ScriptedLLM()
    await _build_graph(corpus, local_embedder, llm)

    async with get_session_factory()() as session:
        entities = (await session.execute(select(KgEntity))).scalars().all()
        relationships = (await session.execute(select(KgRelationship))).scalars().all()
        unstamped = await session.scalar(
            select(func.count(Chunk.id)).where(Chunk.graph_extracted_at.is_(None))
        )
    assert {e.name for e in entities} == {
        "rice straw",
        "Colusa County",
        "anaerobic digestion",
        "biogas",
    }
    assert all(e.chunk_ids for e in entities)
    rice_straw = next(entity for entity in entities if entity.name == "rice straw")
    assert rice_straw.aliases == ["paddy straw"]
    assert len(relationships) == 4
    assert all(r.evidence for r in relationships)
    located_in = next(
        relationship for relationship in relationships if relationship.relation_type == "LOCATED_IN"
    )
    assert located_in.confidence == 0.82
    assert unstamped == 0


async def test_extraction_is_incremental_and_duplicate_safe(clean_tables, corpus, local_embedder):  # type: ignore[no-untyped-def]
    llm = ScriptedLLM()
    await _build_graph(corpus, local_embedder, llm)
    # Nothing new: a second run processes zero chunks.
    second = await extract_graph(
        session_factory=get_session_factory(),
        llm=llm,
        domain=load_domain(DOMAIN_DIR),
        rate_limit_s=0,
    )
    assert second.chunks_processed == 0
    # A forced full pass must not duplicate anything.
    third = await extract_graph(
        session_factory=get_session_factory(),
        llm=llm,
        domain=load_domain(DOMAIN_DIR),
        reprocess_all=True,
        rate_limit_s=0,
    )
    assert third.entities_created == 0
    async with get_session_factory()() as session:
        entity_count = await session.scalar(select(func.count(KgEntity.id)))
        relationship_count = await session.scalar(select(func.count(KgRelationship.id)))
    assert entity_count == 4
    assert relationship_count == 4


async def test_reextraction_merges_aliases_and_keeps_higher_confidence(
    clean_tables, corpus, local_embedder
) -> None:  # type: ignore[no-untyped-def]
    first_payload = deepcopy(EXTRACTION)
    first_payload["relationships"][0]["confidence"] = 0.55
    await _build_graph(corpus, local_embedder, ScriptedLLM(extraction=first_payload))

    second_payload = deepcopy(EXTRACTION)
    second_payload["entities"][0]["aliases"] = ["rice residue"]
    second_payload["relationships"][0]["confidence"] = 0.91
    await extract_graph(
        session_factory=get_session_factory(),
        llm=ScriptedLLM(extraction=second_payload),
        domain=load_domain(DOMAIN_DIR),
        reprocess_all=True,
        rate_limit_s=0,
    )

    lower_payload = deepcopy(EXTRACTION)
    lower_payload["relationships"][0]["confidence"] = 0.2
    await extract_graph(
        session_factory=get_session_factory(),
        llm=ScriptedLLM(extraction=lower_payload),
        domain=load_domain(DOMAIN_DIR),
        reprocess_all=True,
        rate_limit_s=0,
    )

    async with get_session_factory()() as session:
        rice_straw = await session.scalar(select(KgEntity).where(KgEntity.name == "rice straw"))
        located_in = await session.scalar(
            select(KgRelationship).where(KgRelationship.relation_type == "LOCATED_IN")
        )
    assert rice_straw is not None
    assert rice_straw.aliases == ["paddy straw", "rice residue"]
    assert located_in is not None
    assert located_in.confidence == 0.91


async def test_reextraction_through_tombstone_enriches_canonical_entity(
    clean_tables, corpus, local_embedder, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    await _build_graph(corpus, local_embedder, ScriptedLLM())
    async with get_session_factory()() as session:
        winner = await session.scalar(select(KgEntity).where(KgEntity.name == "rice straw"))
        assert winner is not None
        winner.aliases = [*winner.aliases, "rice residue"]
        session.add(
            KgEntity(
                id="f" * 32,
                name="Paddy Straw",
                entity_type="Feedstock",
                aliases=[],
            )
        )
        await session.commit()
    report = await resolve_entities(get_session_factory(), dry_run=False, no_llm=True)
    assert report.merged == 1

    new_path = tmp_path / "new-paddy-evidence.md"
    new_path.write_text("Rice residue has a newly reported use in biogas systems.")
    [outcome] = (
        await ingest_entries(
            [CorpusEntry(path=new_path, license_class="public", source="incremental")],
            embedder=local_embedder,
        )
    ).outcomes
    assert outcome.document_id is not None
    payload = {
        "entities": [
            {"name": "rice residue", "type": "Feedstock", "passages": [1]},
            {"name": "biogas", "type": "Product", "passages": [1]},
        ],
        "relationships": [
            {
                "source": "rice residue",
                "target": "biogas",
                "type": "AFFECTS",
                "evidence": "newly reported use",
                "passage": 1,
            }
        ],
    }
    stats = await extract_graph(
        session_factory=get_session_factory(),
        llm=ScriptedLLM(extraction=payload),
        domain=load_domain(DOMAIN_DIR),
        rate_limit_s=0,
    )
    assert stats.batches_failed == 0

    async with get_session_factory()() as session:
        winner = await session.scalar(select(KgEntity).where(KgEntity.name == "rice straw"))
        loser = await session.scalar(select(KgEntity).where(KgEntity.name == "Paddy Straw"))
        new_chunk = await session.scalar(
            select(Chunk).where(Chunk.document_id == outcome.document_id)
        )
        relationship = await session.scalar(
            select(KgRelationship).where(
                KgRelationship.document_id == outcome.document_id,
                KgRelationship.relation_type == "AFFECTS",
            )
        )
    assert winner is not None and loser is not None and new_chunk is not None
    assert relationship is not None
    assert new_chunk.id in winner.chunk_ids
    assert loser.chunk_ids == []
    assert relationship.source_entity_id == winner.id
    async with get_session_factory()() as session:
        duplicate = await session.scalar(select(KgEntity).where(KgEntity.name == "rice residue"))
    assert duplicate is None


async def test_stats_shows_relationship_confidence_distribution(
    clean_tables, corpus, local_embedder
) -> None:  # type: ignore[no-untyped-def]
    await _build_graph(corpus, local_embedder, ScriptedLLM())

    result = subprocess.run(
        [sys.executable, "-m", "sci_rag.cli.main", "stats"],
        cwd=Path(__file__).parents[2],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Relationship confidence" in result.stdout
    assert "direct=" in result.stdout
    assert "strong=" in result.stdout
    assert "inferred=" in result.stdout


async def test_graph_layer_reaches_evidence_and_new_fields_preserve_baseline(
    clean_tables, corpus, local_embedder
) -> None:  # type: ignore[no-untyped-def]
    old_format = deepcopy(EXTRACTION)
    for entity in old_format["entities"]:
        entity.pop("aliases", None)
    for relationship in old_format["relationships"]:
        relationship.pop("confidence", None)

    baseline_llm = ScriptedLLM(query_entities=["biogas"], extraction=old_format)
    await _build_graph(corpus, local_embedder, baseline_llm)
    baseline_retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=baseline_llm,
        session_factory=get_session_factory(),
    )
    baseline = await baseline_retriever.retrieve(
        "what feedstock ends up as biogas", profile="deep", include_hyde=False
    )

    enhanced_llm = ScriptedLLM(query_entities=["biogas"])
    await extract_graph(
        session_factory=get_session_factory(),
        llm=enhanced_llm,
        domain=load_domain(DOMAIN_DIR),
        reprocess_all=True,
        rate_limit_s=0,
    )
    enhanced_retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=enhanced_llm,
        session_factory=get_session_factory(),
    )
    enhanced = await enhanced_retriever.retrieve(
        "what feedstock ends up as biogas", profile="deep", include_hyde=False
    )

    graph_trace = enhanced.trace_for("graph")
    assert graph_trace is not None and graph_trace.status == "success"
    assert any("graph" in item.layers for item in enhanced.items)
    assert [item.id for item in enhanced.items] == [item.id for item in baseline.items]


async def test_communities_build_and_serve_unrestricted_queries(
    clean_tables, corpus, local_embedder
):  # type: ignore[no-untyped-def]
    llm = ScriptedLLM()
    await _build_graph(corpus, local_embedder, llm)
    stats = await build_communities(
        session_factory=get_session_factory(),
        llm=llm,
        embedder=local_embedder,
        domain=load_domain(DOMAIN_DIR),
        min_size=2,
    )
    assert stats.communities_created >= 1
    async with get_session_factory()() as session:
        missing_embedding = await session.scalar(
            select(func.count(KgCommunity.id)).where(KgCommunity.summary_embedding.is_(None))
        )
    assert missing_embedding == 0

    retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=llm,
        session_factory=get_session_factory(),
    )
    open_result = await retriever.retrieve(
        "rice straw availability and biogas production theme",
        profile="deep",
        include_hyde=False,
        include_graph=False,
        limit=10,
    )
    community_trace = open_result.trace_for("community")
    assert community_trace is not None and community_trace.status == "success"
    assert any(item.kind == "community" for item in open_result.items)

    scoped = await retriever.retrieve(
        "rice straw availability",
        profile="deep",
        scope=RetrievalScope(license_classes=("public",)),
    )
    scoped_trace = scoped.trace_for("community")
    assert scoped_trace is not None and scoped_trace.status == "skipped"


async def test_rebuilding_communities_replaces_rather_than_appends(
    clean_tables, corpus, local_embedder
):  # type: ignore[no-untyped-def]
    llm = ScriptedLLM()
    await _build_graph(corpus, local_embedder, llm)
    for _ in range(2):
        await build_communities(
            session_factory=get_session_factory(),
            llm=llm,
            embedder=local_embedder,
            domain=load_domain(DOMAIN_DIR),
            min_size=2,
        )
    async with get_session_factory()() as session:
        count_first = await session.scalar(select(func.count(KgCommunity.id)))
    await build_communities(
        session_factory=get_session_factory(),
        llm=llm,
        embedder=local_embedder,
        domain=load_domain(DOMAIN_DIR),
        min_size=2,
    )
    async with get_session_factory()() as session:
        count_second = await session.scalar(select(func.count(KgCommunity.id)))
    assert count_first == count_second
