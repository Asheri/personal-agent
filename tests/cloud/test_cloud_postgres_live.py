"""Credentialed lifecycle proof for the workspace-scoped Cloud SQL backend.

This test never targets an arbitrary database URL. It derives both database
names from ``cloud_postgres.py config`` and refuses to continue unless the
test database is distinct and carries the ``sci_rag_test_`` prefix.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cloud_postgres.py"

pytestmark = [
    pytest.mark.cloud,
    pytest.mark.skipif(
        os.environ.get("SCI_RAG_RUN_CLOUD_TESTS") != "1",
        reason="set SCI_RAG_RUN_CLOUD_TESTS=1 for live Cloud SQL checks",
    ),
]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_live_proxy_serves_distinct_development_and_test_databases() -> None:
    configured = _run("config")
    assert configured.returncode == 0, configured.stdout + configured.stderr
    values = dict(line.split("=", 1) for line in configured.stdout.strip().splitlines())
    assert values["database"].startswith("sci_rag_")
    assert values["test_database"].startswith("sci_rag_test_")
    assert values["database"] != values["test_database"]
    assert "password" not in configured.stdout.lower()

    try:
        started = _run("start")
        assert started.returncode == 0, started.stdout + started.stderr
        status = _run("status")
        assert status.returncode == 0, status.stdout + status.stderr

        for database in (values["database"], values["test_database"]):
            checked = subprocess.run(
                [
                    "psql",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    values["port"],
                    "-U",
                    values["user"],
                    "-d",
                    database,
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-tAc",
                    "SELECT current_database(), extversion "
                    "FROM pg_extension WHERE extname = 'vector'",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                env={**os.environ, "PGPASSFILE": values["pgpass_file"]},
                timeout=60,
            )
            assert checked.returncode == 0, checked.stdout + checked.stderr
            assert checked.stdout.strip().startswith(f"{database}|")
    finally:
        stopped = _run("stop")
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
