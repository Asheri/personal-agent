#!/usr/bin/env python
"""Run the project's PostgreSQL without a container runtime.

The helper only needs `initdb`, `pg_ctl`, `psql`, and the pgvector extension
on PATH. A pixi or conda project gets them from conda-forge. A system
PostgreSQL installation works too, including Postgres.app on macOS when its
versioned `bin` directory is added to PATH. This script drives those tools
against a data directory in the project, which is the Docker-free equivalent
of `docker compose up -d --wait`.

It deliberately produces a database that the unmodified `.env.example`
already points at: role `sci_rag`, database `sci_rag`, port 5433 on
127.0.0.1. Swapping compose for this should not mean editing a connection
string.

Authentication is `trust` on the loopback interface only, matching the
posture of the committed compose password: this is a development database
on your own machine and it is not reachable from anywhere else. Do not
point a deployment at it. See docs/adr/0008-supported-postgresql-versions.md
for the supported server versions.

    python scripts/local_postgres.py start    # initdb if needed, then start
    python scripts/local_postgres.py stop
    python scripts/local_postgres.py status
    python scripts/local_postgres.py config   # resolved settings, one per line

Environment:
    SCI_RAG_LOCAL_PG_DIR    data directory, relative to the project (.pgdata)
    SCI_RAG_LOCAL_PG_PORT   port to listen on (5433)
    SCI_RAG_LOCAL_PG_DB     database to create (sci_rag)
    SCI_RAG_LOCAL_PG_USER   role to create (sci_rag)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# The compose service publishes 5433 so it cannot collide with a system
# Postgres on 5432. Matching it here is what lets .env stay untouched.
DEFAULT_PORT = "5433"
DEFAULT_DATA_DIR = ".pgdata"
DEFAULT_DATABASE = "sci_rag"
DEFAULT_USER = "sci_rag"

_MISSING_SERVER = """\
PostgreSQL is not installed in this environment: `initdb` is not on PATH.

The server and the pgvector extension can come from conda-forge, so this path
is available to pixi and conda projects:

    pixi add "postgresql>=16,<19" pgvector
    conda install -c conda-forge "postgresql>=16,<19" pgvector

A system PostgreSQL 16 through 18 with pgvector works as well. On macOS,
Postgres.app includes both; add its versioned bin directory to PATH, for example:

    export PATH="/Applications/Postgres.app/Contents/Versions/16/bin:$PATH"

PyPI ships neither. If neither conda-forge nor a system PostgreSQL is
available, use the bundled container database instead:

    docker compose up -d --wait
"""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: str
    database: str
    user: str

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.user}@127.0.0.1:{self.port}/{self.database}"

    @property
    def logfile(self) -> Path:
        return self.data_dir.parent / f"{self.data_dir.name}.log"

    def as_lines(self) -> list[str]:
        return [
            f"data_dir={self.data_dir}",
            f"port={self.port}",
            f"database={self.database}",
            f"user={self.user}",
            f"url={self.url}",
        ]


def resolve_config() -> Config:
    raw_dir = os.environ.get("SCI_RAG_LOCAL_PG_DIR", DEFAULT_DATA_DIR)
    return Config(
        data_dir=(Path.cwd() / raw_dir).resolve(),
        port=os.environ.get("SCI_RAG_LOCAL_PG_PORT", DEFAULT_PORT),
        database=os.environ.get("SCI_RAG_LOCAL_PG_DB", DEFAULT_DATABASE),
        user=os.environ.get("SCI_RAG_LOCAL_PG_USER", DEFAULT_USER),
    )


def _require_binaries() -> None:
    if shutil.which("initdb") is None or shutil.which("pg_ctl") is None:
        print(_MISSING_SERVER, file=sys.stderr)
        raise SystemExit(1)


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, **kwargs)  # type: ignore[call-overload,no-any-return]


def _is_running(config: Config) -> bool:
    if not (config.data_dir / "PG_VERSION").exists():
        return False
    return _run(["pg_ctl", "-D", str(config.data_dir), "status"]).returncode == 0


def _disable_unix_sockets(config: Config) -> None:
    """Listen on loopback TCP only, written once into the new cluster's config.

    A Unix socket path is capped near 100 characters, and the socket would
    live beside the data directory, so a project a few directories deep makes
    the server refuse to start with a message about sockets rather than about
    paths. Everything here connects over 127.0.0.1 anyway, so the socket is
    only a way to fail.
    """
    conf = config.data_dir / "postgresql.conf"
    with conf.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n# Added by scripts/local_postgres.py: loopback TCP only. A Unix\n"
            "# socket beside a deep project directory exceeds the path limit.\n"
            "unix_socket_directories = ''\n"
        )


def _psql(config: Config, sql: str, *, database: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            config.port,
            "-U",
            config.user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-tAc",
            sql,
        ]
    )


def start(config: Config) -> int:
    _require_binaries()

    if not (config.data_dir / "PG_VERSION").exists():
        # A half-made cluster is worse than none: initdb refuses to run in a
        # non-empty directory, so a failure here has to clean up after itself.
        config.data_dir.mkdir(parents=True, exist_ok=True)
        created = _run(
            ["initdb", "-D", str(config.data_dir), "-U", config.user, "--auth=trust"],
        )
        if created.returncode != 0:
            shutil.rmtree(config.data_dir, ignore_errors=True)
            print(created.stdout + created.stderr, file=sys.stderr)
            return created.returncode
        _disable_unix_sockets(config)
        print(f"initialized {config.data_dir}")

    if _is_running(config):
        print(f"already running on port {config.port}")
    else:
        options = f"-p {config.port} -c listen_addresses=127.0.0.1"
        started = _run(
            [
                "pg_ctl",
                "-D",
                str(config.data_dir),
                "-l",
                str(config.logfile),
                "-o",
                options,
                "-w",
                "start",
            ]
        )
        if started.returncode != 0:
            print(started.stdout + started.stderr, file=sys.stderr)
            print(f"server log: {config.logfile}", file=sys.stderr)
            return started.returncode
        print(f"started on port {config.port}")

    # `createdb` on an existing database is an error, so ask first. Both this
    # and the extension are idempotent by intent: `make setup` runs twice.
    exists = _psql(
        config,
        f"SELECT 1 FROM pg_database WHERE datname = '{config.database}'",
        database="postgres",
    )
    if not exists.stdout.strip():
        created_db = _run(
            ["createdb", "-h", "127.0.0.1", "-p", config.port, "-U", config.user, config.database]
        )
        if created_db.returncode != 0:
            print(created_db.stdout + created_db.stderr, file=sys.stderr)
            return created_db.returncode
        print(f"created database {config.database}")

    extension = _psql(config, "CREATE EXTENSION IF NOT EXISTS vector", database=config.database)
    if extension.returncode != 0:
        print(extension.stdout + extension.stderr, file=sys.stderr)
        print(
            "The pgvector extension is missing from this environment. Install it "
            "alongside the server: pixi add pgvector, or conda install -c conda-forge pgvector.",
            file=sys.stderr,
        )
        return extension.returncode

    print(f"ready: {config.url}")
    return 0


def stop(config: Config) -> int:
    if not _is_running(config):
        print("not running")
        return 0
    stopped = _run(["pg_ctl", "-D", str(config.data_dir), "-m", "fast", "-w", "stop"])
    if stopped.returncode != 0:
        print(stopped.stdout + stopped.stderr, file=sys.stderr)
        return stopped.returncode
    print("stopped")
    return 0


def status(config: Config) -> int:
    if not (config.data_dir / "PG_VERSION").exists():
        print(f"not initialized: {config.data_dir} does not exist")
        return 1
    if not _is_running(config):
        print(f"not running: {config.data_dir}")
        return 1
    print(f"running: {config.url}")
    return 0


def config_command(config: Config) -> int:
    print("\n".join(config.as_lines()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run this project's PostgreSQL without a container runtime.",
    )
    parser.add_argument(
        "command",
        choices=("start", "stop", "status", "config"),
        help="start: initdb if needed, start, and create the database and extension",
    )
    arguments = parser.parse_args(argv)
    config = resolve_config()
    return {
        "start": start,
        "stop": stop,
        "status": status,
        "config": config_command,
    }[arguments.command](config)


if __name__ == "__main__":
    raise SystemExit(main())
