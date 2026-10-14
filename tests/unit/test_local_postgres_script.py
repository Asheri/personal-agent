"""scripts/local_postgres.py, exercised as a real subprocess.

The parts that need no server run everywhere. The start and stop path needs
`initdb` on PATH, which is true in the Docker-free CI job and in a pixi or
conda project, and false in the uv development environment the rest of the
suite runs in, so it skips with a reason rather than pretending to pass.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
SCRIPT = REPO_ROOT / "scripts" / "local_postgres.py"

needs_postgres_binaries = pytest.mark.skipif(
    shutil.which("initdb") is None,
    reason="needs the conda-forge postgresql package on PATH (pixi or conda)",
)


def _run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os

    environment = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=environment,
        timeout=180,
    )


def test_config_reports_the_defaults(tmp_path: Path) -> None:
    """The defaults have to match docker-compose, or .env needs editing."""
    result = _run("config", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert values["port"] == "5433"
    assert values["database"] == "sci_rag"
    assert values["user"] == "sci_rag"
    assert Path(values["data_dir"]) == tmp_path / ".pgdata"
    assert values["url"] == "postgresql+asyncpg://sci_rag:sci_rag@127.0.0.1:5433/sci_rag"


def test_config_honours_the_environment(tmp_path: Path) -> None:
    result = _run(
        "config",
        cwd=tmp_path,
        env={
            "SCI_RAG_LOCAL_PG_DIR": "elsewhere",
            "SCI_RAG_LOCAL_PG_PORT": "5999",
            "SCI_RAG_LOCAL_PG_DB": "other",
        },
    )

    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert values["port"] == "5999"
    assert values["database"] == "other"
    assert Path(values["data_dir"]) == tmp_path / "elsewhere"


def test_status_is_not_an_error_before_the_first_start(tmp_path: Path) -> None:
    """`make db-down` on a project that never started must not fail the build."""
    result = _run("status", cwd=tmp_path)

    assert result.returncode == 1
    assert "not initialized" in result.stdout.lower()


def test_stop_on_a_server_that_was_never_started_succeeds(tmp_path: Path) -> None:
    result = _run("stop", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "not running" in result.stdout.lower()


def test_start_without_postgres_installed_says_who_provides_it(tmp_path: Path) -> None:
    """A uv or venv+pip user has no server, and the error has to say so."""
    result = _run("start", cwd=tmp_path, env={"PATH": str(tmp_path / "empty-bin")})

    assert result.returncode != 0
    message = result.stdout + result.stderr
    assert "initdb" in message
    assert "pixi" in message and "conda" in message
    assert "system PostgreSQL" in message
    assert "Postgres.app" in message
    assert "docker compose up" in message
    assert not (tmp_path / ".pgdata").exists(), "a failed start must leave no half-made state"


@needs_postgres_binaries
def test_start_creates_a_usable_database_and_stop_releases_it(tmp_path: Path) -> None:
    """The whole point: a working pgvector database with no container runtime."""
    env = {"SCI_RAG_LOCAL_PG_PORT": "5455"}
    try:
        started = _run("start", cwd=tmp_path, env=env)
        assert started.returncode == 0, started.stdout + started.stderr

        assert (tmp_path / ".pgdata" / "PG_VERSION").exists()
        assert _run("status", cwd=tmp_path, env=env).returncode == 0

        # Starting again is what `make setup` does on a second run.
        again = _run("start", cwd=tmp_path, env=env)
        assert again.returncode == 0, again.stdout + again.stderr

        version = subprocess.run(
            [
                "psql",
                "-h",
                "127.0.0.1",
                "-p",
                "5455",
                "-U",
                "sci_rag",
                "-d",
                "sci_rag",
                "-tAc",
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert version.stdout.strip(), "the vector extension has to be created by start"
    finally:
        stopped = _run("stop", cwd=tmp_path, env=env)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr

    assert _run("status", cwd=tmp_path, env=env).returncode == 1
