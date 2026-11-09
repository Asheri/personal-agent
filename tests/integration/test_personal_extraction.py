"""Personal graph provenance and exact-name audit receipts in PostgreSQL."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from sci_rag.db import Document, EntityResolutionAudit, KgEntity, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.graph import extract_graph
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.retrieve import RetrievalScope
from sci_rag.retrieve.stages.graph import graph_stage

pytestmark = pytest.mark.integration
DOMAIN = Path(__file__).resolve().parents[2] / "domain-personal"


@pytest.mark.parametrize("visible_name", [True, False])
async def test_chinese_graph_seed_requires_literal_evidence_in_allowed_source(
    clean_tables, tmp_path, local_embedder, visible_name
):  # type: ignore[no-untyped-def]
    from sci_rag.db import Chunk

    path = tmp_path / "public.txt"
    path.write_text(
        "陈林负责 Atlas 项目并整理实验记录。"
        if visible_name
        else "本页仅包含公开的项目记录和实验说明,不提供任何具体负责人的姓名。",
        encoding="utf-8",
    )
    await ingest_entries([CorpusEntry(path=path, license_class="public")], embedder=local_embedder)
    factory = get_session_factory()
    async with factory() as session:
        chunk = (await session.scalars(select(Chunk))).one()
        session.add(
            KgEntity(
                name="陈林",
                entity_type="Person",
                document_ids=[chunk.document_id],
                chunk_ids=[chunk.id],
            )
        )
        await session.commit()
        chunk_id = chunk.id
    llm = AsyncMock()
    llm.generate_json.return_value = {"entities": ["陈林"]}
    result = await graph_stage(
        factory,
        llm,
        load_domain(DOMAIN),
        "陈林负责什么项目?",
        RetrievalScope(license_classes=("public",)),
        8,
    )
    assert result == ([("chunk", chunk_id)] if visible_name else [])


async def test_same_person_across_files_has_one_entity_and_exact_receipt(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    llm = AsyncMock()
    llm.generate_json.return_value = {
        "entities": [{"name": "Chen Lin", "type": "Person", "passages": [1]}],
        "relationships": [],
    }
    for index in range(2):
        path = tmp_path / f"record-{index}.txt"
        path.write_text(
            f"Record {index}. Chen Lin works on the shared research project and prepares its documents.",
            encoding="utf-8",
        )
        await ingest_entries(
            [CorpusEntry(path=path, authors=["Catalog author"], license_class="public")],
            embedder=local_embedder,
        )
        await extract_graph(
            session_factory=get_session_factory(),
            llm=llm,
            domain=load_domain(DOMAIN),
            rate_limit_s=0,
        )
    async with get_session_factory()() as session:
        entities = list((await session.scalars(select(KgEntity))).all())
        assert len(entities) == 1 and len(entities[0].document_ids) == 2
        receipts = list(
            (
                await session.scalars(
                    select(EntityResolutionAudit).where(EntityResolutionAudit.method == "exact")
                )
            ).all()
        )
        assert receipts and receipts[0].surviving_entity_id == entities[0].id
        documents = list((await session.scalars(select(Document))).all())
        assert all(d.authors == ["Catalog author"] for d in documents)
        assert all(d.extra["person_entities_source"] == "graph_chunks" for d in documents)


async def test_unknown_rights_are_not_sent_for_graph_extraction(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    path = tmp_path / "private.txt"
    path.write_text(
        "A private source contains a person and a project which must remain local.",
        encoding="utf-8",
    )
    await ingest_entries([CorpusEntry(path=path)], embedder=local_embedder)
    llm = AsyncMock()
    stats = await extract_graph(
        session_factory=get_session_factory(), llm=llm, domain=load_domain(DOMAIN)
    )
    assert stats.chunks_skipped_outbound == 1 and stats.chunks_processed == 0
    assert not llm.generate_json.called


async def test_version_change_during_model_call_discards_stale_graph(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    path = tmp_path / "changing.txt"
    path.write_text(
        "Chen Lin prepares the original experimental notes for the Atlas project.", encoding="utf-8"
    )
    entry = CorpusEntry(path=path, license_class="public")
    await ingest_entries([entry], embedder=local_embedder)

    async def changed(*args, **kwargs):  # type: ignore[no-untyped-def]
        path.write_text(
            "The revised project notes now describe another approved result and updated supporting evidence.",
            encoding="utf-8",
        )
        await ingest_entries([entry], embedder=local_embedder)
        return {
            "entities": [{"name": "Chen Lin", "type": "Person", "passages": [1]}],
            "relationships": [],
        }

    llm = AsyncMock()
    llm.generate_json.side_effect = changed
    stats = await extract_graph(
        session_factory=get_session_factory(), llm=llm, domain=load_domain(DOMAIN)
    )
    assert stats.stale_batches == 1 and stats.chunks_processed == 0
    async with get_session_factory()() as session:
        assert list((await session.scalars(select(KgEntity))).all()) == []


async def test_explicit_graph_reset_retains_documents_and_exact_audits(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    from sci_rag.db import Chunk
    from sci_rag.graph.extractor import reset_graph

    path = tmp_path / "record.txt"
    path.write_text(
        "Chen Lin prepares reproducible records for the Atlas project and its knowledge graph.",
        encoding="utf-8",
    )
    await ingest_entries([CorpusEntry(path=path, license_class="public")], embedder=local_embedder)
    llm = AsyncMock()
    llm.generate_json.return_value = {
        "entities": [{"name": "Chen Lin", "type": "Person", "passages": [1]}],
        "relationships": [],
    }
    for _ in range(2):
        await extract_graph(
            session_factory=get_session_factory(),
            llm=llm,
            domain=load_domain(DOMAIN),
            reprocess_all=True,
            rate_limit_s=0,
        )
    await reset_graph(get_session_factory())
    async with get_session_factory()() as session:
        assert list((await session.scalars(select(KgEntity))).all()) == []
        assert len((await session.scalars(select(Document))).all()) == 1
        assert len((await session.scalars(select(EntityResolutionAudit))).all()) == 1
        assert all(
            c.graph_extracted_at is None for c in (await session.scalars(select(Chunk))).all()
        )
