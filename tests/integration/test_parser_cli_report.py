"""A partial parser failure returns exit 1 and keeps a content-free receipt."""

import json
import os
import subprocess
import sys

from sqlalchemy import select

from sci_rag.db import Document, get_session_factory


async def test_cli_persists_parser_counts_and_nonzero_exit(clean_tables, tmp_path):
    folder = tmp_path / "sources"
    folder.mkdir()
    (folder / "good.txt").write_text(
        "Controlled local source with enough evidence to ingest.", encoding="utf-8"
    )
    (folder / "encrypted.xlsx").write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"controlled")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sci_rag.cli.main import app; app()",
            "ingest",
            str(folder),
            "--no-docling",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "SCI_RAG_EMBEDDING_PROVIDER": "local-hash",
            "SCI_RAG_EMBEDDING_DIM": "64",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "parser=text ok=1 failed=0" in result.stdout
    assert "parser=xlsx ok=0 failed=1" in result.stdout
    reports = list((tmp_path / ".context/ingest-reports").glob("*.json"))
    assert len(reports) == 1
    receipt = json.loads(reports[0].read_text(encoding="utf-8"))
    assert receipt["source_files"] == 2 and receipt["failed"] == 1
    assert receipt["parsers"]["xlsx"] == {"ok": 0, "failed": 1, "skipped": 0}
    assert "good.txt" not in reports[0].read_text(encoding="utf-8")
    async with get_session_factory()() as session:
        rows = list((await session.scalars(select(Document))).all())
    assert len(rows) == 1 and rows[0].license_class == "unknown"
