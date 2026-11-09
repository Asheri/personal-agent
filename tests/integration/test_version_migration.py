"""Real PostgreSQL migration paths, with every case in its own temporary schema."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _migration(connection, target: str, *, downgrade: bool = False) -> None:  # type: ignore[no-untyped-def]
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["connection"] = connection
    config.attributes["version_table_schema"] = (
        connection.get_execution_options().get("schema_translate_map", {}).get(None)
    )
    (command.downgrade if downgrade else command.upgrade)(config, target)


def _legacy_row(connection, marker: str, path: str | None) -> None:  # type: ignore[no-untyped-def]
    connection.execute(
        text(
            "INSERT INTO documents(id,title,source,source_ref,authors,license_class,content_hash,chunk_count,extra) "
            "VALUES (:id,'Synthetic legacy','test',:path,'{}','public',:hash,0,'{}')"
        ),
        {"id": marker * 32, "hash": marker * 64, "path": path},
    )


@pytest.fixture
async def migration_connection(database):  # type: ignore[no-untyped-def]
    name = "version_case_" + uuid4().hex
    async with database.begin() as connection:
        public_count = await connection.scalar(text("SELECT count(*) FROM public.documents"))
        await connection.execute(text(f'CREATE SCHEMA "{name}"'))
    try:
        async with database.begin() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{name}", public'))
            connection = await connection.execution_options(schema_translate_map={None: name})
            yield connection
    finally:
        async with database.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
            assert (
                await connection.scalar(text("SELECT count(*) FROM public.documents"))
                == public_count
            )


async def test_fresh_upgrade_downgrade_and_legacy_data_round_trip(migration_connection):  # type: ignore[no-untyped-def]
    connection = migration_connection
    await connection.run_sync(lambda c: _migration(c, "head"))
    columns = await connection.run_sync(
        lambda c: {v["name"] for v in inspect(c).get_columns("documents")}
    )
    assert {"identity_key", "version_seq", "version_of", "is_current"} <= columns
    await connection.run_sync(lambda c: _migration(c, "0007", downgrade=True))
    columns = await connection.run_sync(
        lambda c: {v["name"] for v in inspect(c).get_columns("documents")}
    )
    assert "identity_key" not in columns
    await connection.run_sync(lambda c: _legacy_row(c, "a", r"D:\Samples\notes.txt"))
    await connection.run_sync(lambda c: _migration(c, "head"))
    row = (
        await connection.execute(
            text("SELECT identity_key,version_seq,is_current,extra FROM documents")
        )
    ).one()
    assert row.version_seq == 1 and row.is_current
    assert row.extra["path"] == r"d:\samples\notes.txt"
    identity = row.identity_key
    await connection.run_sync(lambda c: _migration(c, "0007", downgrade=True))
    assert await connection.scalar(text("SELECT count(*) FROM documents")) == 1
    await connection.run_sync(lambda c: _migration(c, "head"))
    assert await connection.scalar(text("SELECT identity_key FROM documents")) == identity


async def test_legacy_same_path_rows_form_a_chain_and_unknown_paths_stay_separate(
    migration_connection,
):  # type: ignore[no-untyped-def]
    connection = migration_connection
    await connection.run_sync(lambda c: _migration(c, "head"))
    await connection.run_sync(lambda c: _migration(c, "0007", downgrade=True))
    await connection.run_sync(lambda c: _legacy_row(c, "a", r"D:\Samples\notes.txt"))
    await connection.run_sync(lambda c: _legacy_row(c, "b", "d:/samples/./notes.txt"))
    await connection.run_sync(lambda c: _legacy_row(c, "c", "https://example.invalid/unknown"))
    await connection.run_sync(lambda c: _migration(c, "head"))
    rows = (
        await connection.execute(
            text(
                "SELECT id,identity_key,version_seq,version_of,is_current,extra FROM documents ORDER BY id"
            )
        )
    ).all()
    assert rows[0].identity_key == rows[1].identity_key != rows[2].identity_key
    assert [r.version_seq for r in rows] == [1, 2, 1]
    assert [r.is_current for r in rows] == [False, True, True]
    assert rows[1].version_of == rows[0].id
    assert rows[2].extra["identity_origin"] == "legacy_unresolved"
    with pytest.raises(RuntimeError, match="would discard"):
        await connection.run_sync(lambda c: _migration(c, "0007", downgrade=True))
    assert await connection.scalar(text("SELECT count(*) FROM documents")) == 3
    assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"


async def test_downgrade_refuses_to_merge_distinct_source_copies(migration_connection):  # type: ignore[no-untyped-def]
    connection = migration_connection
    await connection.run_sync(lambda c: _migration(c, "head"))
    for marker in ["a", "b"]:
        await connection.execute(
            text(
                "INSERT INTO documents(id,title,source,authors,license_class,content_hash,chunk_count,extra,identity_key) "
                "VALUES (:id,'Synthetic copy','test','{}','public',:hash,0,'{}',:identity)"
            ),
            {"id": marker * 32, "hash": "f" * 64, "identity": marker * 64},
        )
    with pytest.raises(RuntimeError, match="would discard"):
        await connection.run_sync(lambda c: _migration(c, "0007", downgrade=True))
    assert await connection.scalar(text("SELECT count(*) FROM documents")) == 2


async def test_project_migration_round_trip_and_loss_guard(migration_connection):  # type: ignore[no-untyped-def]
    connection = migration_connection
    await connection.run_sync(lambda c: _migration(c, "head"))
    await connection.run_sync(lambda c: _migration(c, "0008", downgrade=True))
    columns = await connection.run_sync(
        lambda c: {v["name"] for v in inspect(c).get_columns("documents")}
    )
    assert "project_id" not in columns
    await connection.run_sync(lambda c: _migration(c, "head"))
    await connection.execute(
        text("INSERT INTO projects(id,name,slug) VALUES ('project-case','Synthetic','synthetic')")
    )
    with pytest.raises(RuntimeError, match="would discard"):
        await connection.run_sync(lambda c: _migration(c, "0008", downgrade=True))
    assert await connection.scalar(text("SELECT count(*) FROM projects")) == 1
    assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009"


async def test_relation_migration_round_trip_and_loss_guard(migration_connection):  # type: ignore[no-untyped-def]
    connection = migration_connection
    await connection.run_sync(lambda c: _migration(c, "head"))
    await connection.run_sync(lambda c: _migration(c, "0009", downgrade=True))
    columns = await connection.run_sync(
        lambda c: {v["name"] for v in inspect(c).get_columns("document_citations")}
    )
    assert "cited_key" not in columns
    await connection.run_sync(lambda c: _migration(c, "head"))
    await connection.run_sync(lambda c: _legacy_row(c, "a", r"D:\Samples\relations.txt"))
    await connection.execute(
        text(
            "INSERT INTO document_embeddings(document_id,embedding,embedding_version) VALUES (:id,CAST(:vector AS vector),'controlled')"
        ),
        {"id": "a" * 32, "vector": "[" + ",".join(["1"] + ["0"] * 63) + "]"},
    )
    with pytest.raises(RuntimeError, match="would discard"):
        await connection.run_sync(lambda c: _migration(c, "0009", downgrade=True))
    assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010"


async def test_chinese_index_backfills_legacy_chunks_and_round_trips(migration_connection):  # type: ignore[no-untyped-def]
    connection = migration_connection
    await connection.run_sync(lambda c: _migration(c, "head"))
    await connection.run_sync(lambda c: _migration(c, "0010", downgrade=True))
    await connection.run_sync(lambda c: _legacy_row(c, "d", r"D:\Samples\chinese.txt"))
    await connection.execute(
        text(
            "INSERT INTO chunks(id,document_id,chunk_index,content,token_count,is_table) "
            "VALUES ('legacy-chinese',:doc,0,'陈林负责当前项目。',10,false)"
        ),
        {"doc": "d" * 32},
    )
    await connection.run_sync(lambda c: _migration(c, "head"))
    assert await connection.scalar(
        text(
            "SELECT search_zh_tsv @@ plainto_tsquery('simple','陈林') FROM chunks WHERE id='legacy-chinese'"
        )
    )
    await connection.run_sync(lambda c: _migration(c, "0010", downgrade=True))
    assert (
        await connection.scalar(text("SELECT content FROM chunks WHERE id='legacy-chinese'"))
        == "陈林负责当前项目。"
    )
    columns = await connection.run_sync(
        lambda c: {v["name"] for v in inspect(c).get_columns("chunks")}
    )
    assert "search_tokens" not in columns and "search_zh_tsv" not in columns
    await connection.run_sync(lambda c: _migration(c, "head"))
    assert await connection.scalar(
        text("SELECT search_tokens FROM chunks WHERE id='legacy-chinese'")
    )
