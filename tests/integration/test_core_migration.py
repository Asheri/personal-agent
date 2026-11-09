"""Exercise fresh install, old-data backfill, and both core migration reversals."""

import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[2]


def migrate(connection, target, downgrade=False):
    # Simulate a committed legacy corpus inside this test's isolated transaction.
    connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["connection"] = connection
    config.attributes["version_table_schema"] = (
        connection.get_execution_options().get("schema_translate_map", {}).get(None)
    )
    (command.downgrade if downgrade else command.upgrade)(config, target)


async def test_backfill_and_reversal_keep_source_content(database):
    schema = "core_case_" + uuid4().hex
    async with database.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with database.begin() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}",public'))
            connection = await connection.execution_options(schema_translate_map={None: schema})
            await connection.run_sync(lambda c: migrate(c, "head"))
            await connection.run_sync(lambda c: migrate(c, "0011", True))
            await connection.execute(
                text(
                    "INSERT INTO documents(id,title,source,authors,license_class,content_hash,identity_key,extra,ingested_at,chunk_count) VALUES (:id,'Legacy','controlled','{}','public',:hash,:hash,CAST(:extra AS jsonb),'2026-01-01T00:00:00Z',1)"
                ),
                dict(
                    id="a" * 32,
                    hash="a" * 64,
                    extra=json.dumps({"email_datetime": "2025-05-06T07:00:00+08:00"}),
                ),
            )
            await connection.execute(
                text(
                    "INSERT INTO chunks(id,document_id,chunk_index,content,token_count,is_table) VALUES (:id,:id,0,'English control TYPES2026',10,false)"
                ),
                dict(id="a" * 32),
            )
            await connection.run_sync(lambda c: migrate(c, "head"))
            row = (
                await connection.execute(
                    text("SELECT doc_date,doc_date_source,access_count FROM documents")
                )
            ).one()
            assert (
                str(row.doc_date) == "2025-05-06"
                and row.doc_date_source == "email_header"
                and row.access_count == 0
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM chunks WHERE search_zh_tsv @@ websearch_to_tsquery('simple','TYPES2026')"
                    )
                )
                == 1
            )
            assert "file_events" in await connection.run_sync(
                lambda c: inspect(c).get_table_names(schema=schema)
            )
            await connection.run_sync(lambda c: migrate(c, "0012", True))
            assert "file_events" not in await connection.run_sync(
                lambda c: inspect(c).get_table_names(schema=schema)
            )
            await connection.run_sync(lambda c: migrate(c, "0011", True))
            assert "doc_date" not in await connection.run_sync(
                lambda c: {v["name"] for v in inspect(c).get_columns("documents", schema=schema)}
            )
            assert (
                await connection.scalar(text("SELECT content FROM chunks"))
                == "English control TYPES2026"
            )
            await connection.run_sync(lambda c: migrate(c, "head"))
    finally:
        async with database.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
