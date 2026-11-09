"""All trigger channels use one guarded refresh and durable content-free events."""

from sqlalchemy import func, select

from sci_rag.db import Document, get_session_factory


async def test_three_channels_match_and_repeat_without_embedding(
    clean_tables, tmp_path, local_embedder
):
    from sci_rag.db.models import FileEvent
    from sci_rag.refresh import refresh_corpus

    path = tmp_path / "record.txt"
    path.write_text("Controlled initial local record with a persistent source.", encoding="utf-8")
    results = []
    for channel in ["scheduler", "hooks", "poll"]:
        path.write_text(f"Controlled updated local record for channel {channel}.", encoding="utf-8")
        result = await refresh_corpus(
            root=tmp_path, channel=channel, embedder=local_embedder, update_graph=False
        )
        assert result["status"] == "success", result
        results.append(result)
    repeated = await refresh_corpus(
        root=tmp_path, channel="poll", embedder=local_embedder, update_graph=False
    )
    assert repeated["counts"]["unchanged"] == 1
    async with get_session_factory()() as session:
        assert await session.scalar(select(func.count(Document.id)).where(Document.is_current)) == 1
        assert await session.scalar(select(func.count(Document.id))) == 3
        events = list((await session.scalars(select(FileEvent))).all())
    assert {row.channel for row in events} == {"scheduler", "hooks", "poll"}
    assert all("record.txt" not in str(row.__dict__) for row in events)


async def test_second_refresh_exits_before_any_database_mutation(
    clean_tables, tmp_path, local_embedder
):
    from sci_rag.db.models import FileEvent
    from sci_rag.reconcile import _single_reconcile
    from sci_rag.refresh import refresh_corpus

    (tmp_path / "record.txt").write_text("Controlled competing refresh test.", encoding="utf-8")
    async with _single_reconcile(get_session_factory()):
        result = await refresh_corpus(
            root=tmp_path, channel="poll", embedder=local_embedder, update_graph=False
        )
        assert result["status"] == "busy" and result["exit_code"] == 2
    async with get_session_factory()() as session:
        assert await session.scalar(select(func.count(Document.id))) == 0
        assert await session.scalar(select(func.count(FileEvent.id))) == 0


async def test_failed_refresh_keeps_old_rows_and_records_failure(
    clean_tables, tmp_path, local_embedder
):
    from sci_rag.db.models import FileEvent
    from sci_rag.refresh import refresh_corpus

    path = tmp_path / "record.json"
    path.write_text('{"record":"valid controlled record"}', encoding="utf-8")
    assert (
        await refresh_corpus(
            root=tmp_path, channel="hooks", embedder=local_embedder, update_graph=False
        )
    )["status"] == "success"
    path.write_text("{broken", encoding="utf-8")
    result = await refresh_corpus(
        root=tmp_path, channel="hooks", embedder=local_embedder, update_graph=False
    )
    assert result["status"] == "failed" and result["exit_code"] == 1
    async with get_session_factory()() as session:
        assert await session.scalar(select(func.count(Document.id))) == 1
        assert (
            await session.scalar(
                select(func.count(FileEvent.id)).where(FileEvent.status == "failed")
            )
            >= 1
        )


async def test_restart_reclassifies_orphaned_running_marker(clean_tables, tmp_path, local_embedder):
    from sci_rag.db.models import FileEvent
    from sci_rag.refresh import _key, refresh_corpus

    (tmp_path / "record.txt").write_text("Controlled recovery source.", encoding="utf-8")
    async with get_session_factory()() as session:
        event = FileEvent(
            run_id="a" * 32, root_key=_key(tmp_path), kind="run", channel="poll", status="running"
        )
        session.add(event)
        await session.commit()
        key = event.id
    result = await refresh_corpus(
        root=tmp_path, channel="poll", embedder=local_embedder, update_graph=False
    )
    assert result["status"] == "success"
    async with get_session_factory()() as session:
        assert (await session.get(FileEvent, key)).status == "interrupted"
        assert await session.scalar(select(func.count(Document.id))) == 1
