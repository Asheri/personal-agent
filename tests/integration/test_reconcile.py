"""Database acceptance cases prepared for the deferred reconciliation run."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from sci_rag.db import Chunk, Document, KgEntity, get_session_factory
from sci_rag.ingest import CorpusEntry, ingest_entries, ingester
from sci_rag.projects import assign_project, create_project, set_manual_tags
from sci_rag.reconcile import ReconcileBusyError, _single_reconcile, reconcile_entries

pytestmark = pytest.mark.integration


async def test_add_skip_update_and_remove_chain_preserves_manual_metadata(
    clean_tables, tmp_path, local_embedder, monkeypatch
):  # type: ignore[no-untyped-def]
    path = tmp_path / "record.txt"
    path.write_text(
        "The initial project record contains a carefully documented experimental procedure.",
        encoding="utf-8",
    )
    entry = CorpusEntry(path=path, license_class="public")
    factory = get_session_factory()

    async def run(entries):  # type: ignore[no-untyped-def]
        return await reconcile_entries(
            entries, root=tmp_path, session_factory=factory, embedder=local_embedder
        )

    first = await run([entry])
    first_id = first.source_outcomes[0].document_id
    project = await create_project(factory, "Controlled project")
    await assign_project(factory, first_id, project.id)
    await set_manual_tags(factory, first_id, ["reviewed"])
    original_parse = ingester.parse_file
    spy = Mock(wraps=original_parse)
    monkeypatch.setattr(ingester, "parse_file", spy)
    assert (await run([entry])).counts()["unchanged"] == 1
    assert not spy.called
    path.write_text(
        "The revised project record now describes a different procedure and updated experimental evidence.",
        encoding="utf-8",
    )
    assert (await run([entry])).counts()["updated"] == 1
    async with factory() as session:
        versions = list(
            (await session.scalars(select(Document).order_by(Document.version_seq))).all()
        )
        assert len(versions) == 2 and not versions[0].is_current and versions[1].is_current
        assert versions[1].version_of == first_id and versions[1].project_id == project.id
        assert versions[1].tags == ["reviewed"]
    path.unlink()
    result = await run([])
    assert result.database_outcomes[0].document_count == 2
    async with factory() as session:
        assert list((await session.scalars(select(Document))).all()) == []


@pytest.mark.parametrize("fault", ["parse", "embedding"])
async def test_failed_update_preserves_head_and_fingerprint(
    clean_tables, tmp_path, local_embedder, monkeypatch, fault
):  # type: ignore[no-untyped-def]
    path = tmp_path / "record.txt"
    path.write_text(
        "The original record contains reproducible procedures and verified source evidence.",
        encoding="utf-8",
    )
    entry = CorpusEntry(path=path)
    factory = get_session_factory()
    await reconcile_entries(
        [entry], root=tmp_path, session_factory=factory, embedder=local_embedder
    )
    async with factory() as session:
        old = (await session.scalars(select(Document))).one()
        old_id, old_fingerprint = old.id, old.extra["source_fingerprint"]
    path.write_text(
        "The revised record has substantially different details about another experiment and its results.",
        encoding="utf-8",
    )
    if fault == "parse":
        monkeypatch.setattr(
            ingester, "parse_file", Mock(side_effect=ValueError("controlled failure"))
        )
    else:
        monkeypatch.setattr(
            local_embedder, "embed", AsyncMock(side_effect=RuntimeError("controlled failure"))
        )
    result = await reconcile_entries(
        [entry], root=tmp_path, session_factory=factory, embedder=local_embedder
    )
    assert result.failed == 1
    async with factory() as session:
        old = (await session.scalars(select(Document))).one()
        assert old.id == old_id and old.is_current and old.version_seq == 1
        assert old.extra["source_fingerprint"] == old_fingerprint


async def test_manifest_rights_refresh_needs_no_embedding_and_invalidates_graph(
    clean_tables, tmp_path, local_embedder, monkeypatch
):  # type: ignore[no-untyped-def]
    path = tmp_path / "record.txt"
    path.write_text(
        "A controlled source contains a named person and a documented project procedure.",
        encoding="utf-8",
    )
    entry = CorpusEntry(path=path, license_class="public")
    factory = get_session_factory()
    await reconcile_entries(
        [entry], root=tmp_path, session_factory=factory, embedder=local_embedder
    )
    async with factory() as session:
        chunk = (await session.scalars(select(Chunk))).one()
        chunk.graph_extracted_at = datetime.now(UTC)
        entity = KgEntity(
            name="Controlled person",
            entity_type="Person",
            document_ids=[chunk.document_id],
            chunk_ids=[chunk.id],
            description="Derived description",
            aliases=["An alias"],
        )
        session.add(entity)
        await session.commit()
        document_id, entity_id = chunk.document_id, entity.id
    embedding = AsyncMock(wraps=local_embedder.embed)
    monkeypatch.setattr(local_embedder, "embed", embedding)
    entry.license_class, entry.title = "unknown", "Updated catalog title"
    result = await reconcile_entries(
        [entry], root=tmp_path, session_factory=factory, embedder=local_embedder
    )
    assert result.counts()["metadata_only"] == 1 and result.graph_changed
    embedding.assert_not_awaited()
    async with factory() as session:
        document = (await session.scalars(select(Document))).one()
        assert document.id == document_id and document.license_class == "unknown"
        entity = await session.get(KgEntity, entity_id)
        assert entity.document_ids == entity.chunk_ids == [] and entity.description is None
        assert (await session.scalars(select(Chunk))).one().graph_extracted_at is None


async def test_missing_sources_outside_selected_root_are_preserved(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    selected = tmp_path / "selected"
    selected.mkdir()
    inside, outside = selected / "inside.txt", tmp_path / "outside.txt"
    for path in [inside, outside]:
        path.write_text(
            "This controlled document provides sufficient text for a reproducible ingestion check.",
            encoding="utf-8",
        )
    await ingest_entries([CorpusEntry(path=p) for p in [inside, outside]], embedder=local_embedder)
    inside.unlink()
    outside.unlink()
    factory = get_session_factory()
    result = await reconcile_entries(
        [], root=selected, session_factory=factory, embedder=local_embedder
    )
    assert result.counts(database=True)["removed"] == 1
    assert result.counts(database=True)["out_of_scope"] == 1
    async with factory() as session:
        document = (await session.scalars(select(Document))).one()
        assert document.extra["path"].endswith("outside.txt")


async def test_second_reconcile_refuses_the_owned_database_lock(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with _single_reconcile(factory):
        with pytest.raises(ReconcileBusyError):
            await reconcile_entries(
                [], root=tmp_path, session_factory=factory, embedder=local_embedder
            )
    assert not (
        await reconcile_entries([], root=tmp_path, session_factory=factory, embedder=local_embedder)
    ).failed
