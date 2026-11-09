"""Document identity, revision transactions, and historical evidence isolation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from sci_rag.corpus import delete_documents
from sci_rag.db import Chunk, Document, get_session_factory
from sci_rag.db.engine import get_engine
from sci_rag.db.models import KgCommunity, KgEntity, KgRelationship
from sci_rag.domain import load_domain
from sci_rag.export import export_corpus
from sci_rag.ingest.ingester import ingest_entries
from sci_rag.ingest.manifest import CorpusEntry
from sci_rag.retrieve import RetrievalScope, Retriever
from sci_rag.retrieve.stages.graph import graph_stage
from sci_rag.retrieve.stages.keyword import keyword_stage
from sci_rag.retrieve.stages.vector import vector_stage
from sci_rag.server.errors import ApiError
from sci_rag.server.service import RagService

pytestmark = pytest.mark.integration
DOMAIN = Path(__file__).resolve().parents[2] / "domain"


def _write(entry: CorpusEntry, version: str) -> None:
    entry.path.write_text(
        f"Version anchor {version}. This synthetic project record describes "
        "the latest experiment, its result, and its supporting local documents. "
        "The record is long enough to remain a complete searchable passage.",
        encoding="utf-8",
    )


def _entry(tmp_path: Path, name: str = "record") -> CorpusEntry:
    entry = CorpusEntry(path=tmp_path / f"{name}.txt", source="versions", license_class="public")
    _write(entry, "oldtoken")
    return entry


async def _rows():  # type: ignore[no-untyped-def]
    async with get_session_factory()() as session:
        return list((await session.scalars(select(Document).order_by(Document.version_seq))).all())


async def test_same_content_at_different_paths_is_preserved(clean_tables, tmp_path, local_embedder):  # type: ignore[no-untyped-def]
    first, second = _entry(tmp_path, "first"), _entry(tmp_path, "second")
    report = await ingest_entries([first, second], embedder=local_embedder)
    assert report.ingested == 2
    rows = await _rows()
    assert len(rows) == 2
    assert rows[0].content_hash == rows[1].content_hash
    assert rows[0].identity_key != rows[1].identity_key
    repeated = await ingest_entries([first, second], embedder=local_embedder)
    assert repeated.skipped == 2 and repeated.failed == 0


async def test_revert_creates_a_new_current_version(clean_tables, tmp_path, local_embedder):  # type: ignore[no-untyped-def]
    entry = _entry(tmp_path)
    await ingest_entries([entry], embedder=local_embedder)
    _write(entry, "newtoken")
    assert (await ingest_entries([entry], embedder=local_embedder)).ingested == 1
    _write(entry, "oldtoken")
    assert (await ingest_entries([entry], embedder=local_embedder)).ingested == 1
    rows = await _rows()
    assert [d.version_seq for d in rows] == [1, 2, 3]
    assert [d.is_current for d in rows] == [False, False, True]
    assert [d.version_of for d in rows] == [None, rows[0].id, rows[1].id]
    assert len({d.identity_key for d in rows}) == 1
    assert rows[0].content_hash == rows[2].content_hash


async def test_members_of_one_path_have_separate_identities(
    clean_tables, tmp_path, local_embedder, monkeypatch
):  # type: ignore[no-untyped-def]
    from sci_rag.ingest.parsers import parse_file

    entry = _entry(tmp_path)
    parsed = parse_file(entry.path)
    monkeypatch.setattr("sci_rag.ingest.ingester.parse_file", lambda *args, **kwargs: parsed)
    parsed.metadata["source_member"] = "message-one"
    assert (await ingest_entries([entry], embedder=local_embedder)).ingested == 1
    parsed.metadata["source_member"] = "message-two"
    assert (await ingest_entries([entry], embedder=local_embedder)).ingested == 1
    rows = await _rows()
    assert len(rows) == 2 and all(d.version_seq == 1 and d.is_current for d in rows)


async def test_insert_failure_rolls_back_predecessor_demotion(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    entry = _entry(tmp_path)
    await ingest_entries([entry], embedder=local_embedder)
    _write(entry, "newtoken")

    def interrupt(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        if statement.lstrip().startswith("INSERT INTO documents"):
            raise RuntimeError("injected interruption after predecessor demotion")

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", interrupt)
    try:
        report = await ingest_entries([entry], embedder=local_embedder)
    finally:
        event.remove(engine, "before_cursor_execute", interrupt)
    assert report.failed == 1
    [old] = await _rows()
    assert old.is_current and old.version_seq == 1
    assert (await ingest_entries([entry], embedder=local_embedder)).ingested == 1
    assert [d.is_current for d in await _rows()] == [False, True]


async def test_concurrent_reingestion_has_one_current_version(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    entry = _entry(tmp_path)
    reports = await asyncio.gather(
        ingest_entries([entry], embedder=local_embedder),
        ingest_entries([entry], embedder=local_embedder),
    )
    assert sum(r.ingested for r in reports) == 1
    assert sum(r.skipped for r in reports) == 1
    assert len(await _rows()) == 1


async def test_database_rejects_two_current_versions(clean_tables, tmp_path, local_embedder):  # type: ignore[no-untyped-def]
    entry = _entry(tmp_path)
    await ingest_entries([entry], embedder=local_embedder)
    [old] = await _rows()
    async with get_session_factory()() as session:
        session.add(
            Document(
                title="Invalid current",
                content_hash="f" * 64,
                identity_key=old.identity_key,
                version_seq=2,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_default_readers_filter_history_before_limit(clean_tables, tmp_path, local_embedder):  # type: ignore[no-untyped-def]
    entry = _entry(tmp_path)
    await ingest_entries([entry], embedder=local_embedder)
    _write(entry, "newtoken")
    await ingest_entries([entry], embedder=local_embedder)
    old, current = await _rows()
    factory = get_session_factory()
    async with factory() as session:
        chunks = list((await session.scalars(select(Chunk))).all())
        session.add(
            KgEntity(
                name="Version anchor",
                entity_type="Feedstock",
                document_ids=[old.id, current.id],
                chunk_ids=[c.id for c in chunks],
            )
        )
        await session.commit()
    scope = RetrievalScope()
    [query_vector] = await local_embedder.embed(["oldtoken"], task="query")
    vector_keys = await vector_stage(factory, query_vector, scope, 1)
    assert vector_keys
    async with factory() as session:
        assert [(await session.get(Chunk, key)).document_id for _, key in vector_keys] == [
            current.id
        ] * len(vector_keys)
    assert await keyword_stage(factory, "oldtoken", scope, 1) == []
    llm = AsyncMock()
    llm.generate_json.return_value = {"entities": ["Version anchor"]}
    keys = await graph_stage(factory, llm, load_domain(DOMAIN), "Version anchor", scope, 1)
    assert keys
    async with factory() as session:
        assert [(await session.get(Chunk, key)).document_id for _, key in keys] == [
            current.id
        ] * len(keys)
    retriever = Retriever(
        domain=load_domain(DOMAIN), embedder=local_embedder, llm=llm, session_factory=factory
    )
    service = RagService(retriever=retriever)
    listed, total = await service.list_documents()
    assert total == 1 and [d.id for d in listed] == [current.id]
    with pytest.raises(ApiError):
        await service.get_document(old.id)
    restored, _ = await service.get_document(old.id, include_superseded=True)
    assert restored.id == old.id
    result = await export_corpus(factory, directory=tmp_path / "export")
    assert result.counts["documents"] == 1
    exported = [
        json.loads(line)
        for line in (tmp_path / "export/documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [d["id"] for d in exported] == [current.id]
    assert result.counts["entities"] == 0


async def test_version_change_invalidates_community_summaries(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    entry = _entry(tmp_path)
    await ingest_entries([entry], embedder=local_embedder)
    async with get_session_factory()() as session:
        session.add(KgCommunity(title="Old aggregate", summary="Old facts", member_entity_ids=[]))
        await session.commit()
    _write(entry, "newtoken")
    await ingest_entries([entry], embedder=local_embedder)
    async with get_session_factory()() as session:
        assert list((await session.scalars(select(KgCommunity))).all()) == []


async def test_historical_edge_cannot_bridge_current_documents(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    entry = _entry(tmp_path)
    old_id = (await ingest_entries([entry], embedder=local_embedder)).outcomes[0].document_id
    _write(entry, "newtoken")
    current_id = (await ingest_entries([entry], embedder=local_embedder)).outcomes[0].document_id
    neighbor = _entry(tmp_path, "neighbor")
    neighbor_id = (
        (await ingest_entries([neighbor], embedder=local_embedder)).outcomes[0].document_id
    )
    factory = get_session_factory()
    async with factory() as session:
        chunks = {c.document_id: c for c in (await session.scalars(select(Chunk))).all()}
        anchor = KgEntity(
            name="Version anchor",
            entity_type="Feedstock",
            document_ids=[current_id],
            chunk_ids=[chunks[current_id].id],
        )
        other = KgEntity(
            name="Historical bridge target",
            entity_type="Feedstock",
            document_ids=[neighbor_id],
            chunk_ids=[chunks[neighbor_id].id],
        )
        session.add_all([anchor, other])
        await session.flush()
        session.add(
            KgRelationship(
                source_entity_id=anchor.id,
                target_entity_id=other.id,
                relation_type="RELATES_TO",
                document_id=old_id,
                chunk_id=chunks[old_id].id,
                evidence="Obsolete bridge",
            )
        )
        await session.commit()
    llm = AsyncMock()
    llm.generate_json.return_value = {"entities": ["Version anchor"]}
    keys = await graph_stage(factory, llm, load_domain(DOMAIN), "query", RetrievalScope(), 5)
    assert ("chunk", chunks[neighbor_id].id) not in keys
    assert ("chunk", chunks[current_id].id) in keys
    history = await graph_stage(
        factory, llm, load_domain(DOMAIN), "query", RetrievalScope(include_superseded=True), 5
    )
    assert ("chunk", chunks[neighbor_id].id) in history


async def test_community_rebuild_discards_historical_only_descriptions(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    from sci_rag.graph.communities import build_communities

    entry = _entry(tmp_path)
    await ingest_entries([entry], embedder=local_embedder)
    _write(entry, "newtoken")
    await ingest_entries([entry], embedder=local_embedder)
    old, _ = await _rows()
    async with get_session_factory()() as session:
        session.add(
            KgEntity(
                name="Old secret", entity_type="Feedstock", document_ids=[old.id], chunk_ids=[]
            )
        )
        session.add(KgCommunity(title="Old aggregate", summary="Old secret", member_entity_ids=[]))
        await session.commit()
    llm = AsyncMock()
    await build_communities(
        session_factory=get_session_factory(),
        llm=llm,
        embedder=local_embedder,
        domain=load_domain(DOMAIN),
        min_size=1,
    )
    assert not llm.generate_json.called
    async with get_session_factory()() as session:
        assert list((await session.scalars(select(KgCommunity))).all()) == []


@pytest.mark.parametrize("change", ["case", "heading"])
async def test_equal_coarse_hash_does_not_hide_text_or_structure_changes(
    clean_tables, tmp_path, local_embedder, change
):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=tmp_path / "structure.md", source="test")
    body = "The Version anchor record contains a stable, searchable experiment description and supporting evidence."
    entry.path.write_text("# First section\n\n" + body, encoding="utf-8")
    assert (await ingest_entries([entry], embedder=local_embedder)).ingested == 1
    entry.path.write_text(
        ("# Second section\n\n" + body)
        if change == "heading"
        else ("# First section\n\n" + body.upper()),
        encoding="utf-8",
    )
    assert (await ingest_entries([entry], embedder=local_embedder)).ingested == 1
    old, current = await _rows()
    assert old.content_hash == current.content_hash
    assert current.version_of == old.id and current.is_current and not old.is_current


async def test_version_change_detaches_old_aggregate_evidence(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    entry, other_entry = _entry(tmp_path), _entry(tmp_path, "other")
    report = await ingest_entries([entry, other_entry], embedder=local_embedder)
    old_id, other_id = [o.document_id for o in report.outcomes]
    async with get_session_factory()() as session:
        chunks = {c.document_id: c.id for c in (await session.scalars(select(Chunk))).all()}
        session.add(
            KgEntity(
                name="Shared concept",
                entity_type="Feedstock",
                document_ids=[old_id, other_id],
                chunk_ids=list(chunks.values()),
                description="Obsolete aggregated fact",
                aliases=["Obsolete alias"],
            )
        )
        await session.commit()
    _write(entry, "newtoken")
    await ingest_entries([entry], embedder=local_embedder)
    async with get_session_factory()() as session:
        entity = await session.scalar(select(KgEntity).where(KgEntity.name == "Shared concept"))
        assert entity.document_ids == [other_id]
        assert entity.chunk_ids == [chunks[other_id]]
        assert entity.description is None and entity.aliases == []


@pytest.mark.parametrize("deleted", [[1], [2], [1, 2]])
async def test_deletion_reconnects_chain_and_promotes_survivor(
    clean_tables, tmp_path, local_embedder, deleted
):  # type: ignore[no-untyped-def]
    entry = _entry(tmp_path)
    for value in ["oldtoken", "middletoken", "newtoken"]:
        _write(entry, value)
        await ingest_entries([entry], embedder=local_embedder)
    rows = await _rows()
    await delete_documents(get_session_factory(), [rows[i].id for i in deleted])
    survivors = [row for i, row in enumerate(rows) if i not in deleted]
    actual = await _rows()
    assert [d.id for d in actual] == [d.id for d in survivors]
    assert [d.version_of for d in actual] == [None, *[d.id for d in actual[:-1]]]
    assert [d.is_current for d in actual] == [False] * (len(actual) - 1) + [True]


async def test_deleting_current_evidence_clears_shared_aggregate_text(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    first, other = _entry(tmp_path), _entry(tmp_path, "other")
    report = await ingest_entries([first, other], embedder=local_embedder)
    first_id, other_id = [outcome.document_id for outcome in report.outcomes]
    async with get_session_factory()() as session:
        chunks = {c.document_id: c.id for c in (await session.scalars(select(Chunk))).all()}
        entity = KgEntity(
            name="Shared concept",
            entity_type="Feedstock",
            document_ids=[first_id, other_id],
            chunk_ids=list(chunks.values()),
            description="Text derived partly from the deleted source",
            aliases=["Old alias"],
        )
        session.add(entity)
        await session.flush()
        session.add(
            KgCommunity(
                title="Shared aggregate", summary="Old facts", member_entity_ids=[entity.id]
            )
        )
        await session.commit()
    await delete_documents(get_session_factory(), [first_id])
    async with get_session_factory()() as session:
        entity = await session.scalar(select(KgEntity).where(KgEntity.name == "Shared concept"))
        assert entity.document_ids == [other_id] and entity.chunk_ids == [chunks[other_id]]
        assert entity.description is None and entity.aliases == []
        assert list((await session.scalars(select(KgCommunity))).all()) == []
