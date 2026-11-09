"""The user-facing export defaults must not redistribute unknown-rights input."""

import json
import subprocess
import sys
from pathlib import Path

from sci_rag.ingest import CorpusEntry, ingest_entries


async def test_cli_export_defaults_to_external_safe_rights(clean_tables, tmp_path, local_embedder):
    entries = []
    for name, license_class in [("public", "public"), ("private", "unknown")]:
        path = tmp_path / (name + ".txt")
        path.write_text("Controlled export record " + name, encoding="utf-8")
        entries.append(CorpusEntry(path=path, license_class=license_class))
    assert (await ingest_entries(entries, embedder=local_embedder)).failed == 0
    output = tmp_path / "export"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sci_rag.cli.main import app; app()",
            "corpus",
            "export",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [
        json.loads(line)
        for line in (output / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1 and rows[0]["license_class"] == "public"
    assert "access_count" not in rows[0] and "last_accessed_at" not in rows[0]
