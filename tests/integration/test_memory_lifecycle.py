"""Memory keeps facts, tracks actual access, and labels superseded evidence."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from sci_rag.db import Chunk, Document, KgEntity, get_session_factory


async def test_stale_never_deletes_and_access_is_actual(clean_tables):
    from sci_rag.memory_state import maintain_lifecycle, record_access

    factory = get_session_factory()
    now = datetime(2026, 10, 26, tzinfo=UTC)
    async with factory() as session:
        old = Document(
            title="Older current", content_hash="a" * 64, ingested_at=now - timedelta(days=800)
        )
        new = Document(
            title="Recent current", content_hash="b" * 64, ingested_at=now - timedelta(days=1)
        )
        session.add_all([old, new])
        await session.flush()
        chunks = []
        for doc in [old, new]:
            chunk = Chunk(
                document_id=doc.id,
                chunk_index=0,
                content="Controlled topic appears explicitly in this source.",
                token_count=12,
            )
            session.add(chunk)
            chunks.append(chunk)
        await session.flush()
        session.add(
            KgEntity(
                name="Controlled topic",
                entity_type="Topic",
                document_ids=[old.id, new.id],
                chunk_ids=[c.id for c in chunks],
            )
        )
        await session.commit()
    result = await maintain_lifecycle(factory, now=now)
    assert result["stale"] == 1
    async with factory() as session:
        assert await session.scalar(select(func.count(Document.id))) == 2
        assert (await session.get(Document, old.id)).extra["memory_lifecycle"][
            "reason"
        ] == "inactive_with_new_topic_material"
    await record_access(factory, [old.id], now=now)
    result = await maintain_lifecycle(factory, now=now)
    assert result["stale"] == 0
    async with factory() as session:
        row = await session.get(Document, old.id)
        assert row.access_count == 1 and row.last_accessed_at == now


async def test_history_is_labeled_without_deleting_current_chain(
    clean_tables, tmp_path, local_embedder
):
    from sci_rag.ingest import CorpusEntry, ingest_entries
    from sci_rag.memory_state import maintain_lifecycle
    from sci_rag.relate.read import document_versions

    path = tmp_path / "record.txt"
    path.write_text("Older verified source text for the current project.", encoding="utf-8")
    first = await ingest_entries([CorpusEntry(path=path)], embedder=local_embedder)
    path.write_text(
        "Newer verified source text replaces the earlier current record.", encoding="utf-8"
    )
    await ingest_entries([CorpusEntry(path=path)], embedder=local_embedder)
    await maintain_lifecycle(get_session_factory())
    result = await document_versions(get_session_factory(), first.outcomes[0].document_id)
    assert any("已过期" in str(row) for row in result["versions"] if not row["is_current"])
