#!/usr/bin/env python
"""Cross-platform task runner: the Makefile targets without needing `make`.

`make` is not installed by default on Windows, so every target a developer runs
day to day is also reachable here. Each command is the same `uv run ...` line
the Makefile prints, which keeps one mental model on all three platforms.

    uv run python scripts/tasks.py check
    python scripts/tasks.py --list
    python scripts/tasks.py --plan demo

`uv` stays a prerequisite: the runner shells out to the same commands the
documentation already publishes, so there is no second copy of the toolchain.

Targets whose Makefile body is a POSIX shell pipeline (`docs`, `benchmark`,
`benchmark-check`, `benchmark-refresh-graph`) stay in the Makefile. This runner
names them and exits instead of pretending to support them.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCIRAG = ["uv", "run", "sci-rag"]
PYTHON = ["uv", "run", "python"]

DB_BACKENDS = {
    "local": ("scripts/local_postgres.py", "start", "stop"),
    "cloud": ("scripts/cloud_postgres.py", "start", "stop"),
}

UNKNOWN_BACKEND = "Unknown SCI_RAG_DB_BACKEND={backend}; choose docker, local, or cloud."


class TaskRefused(RuntimeError):
    """The task cannot run here; the message says what to do instead."""


def _backend() -> str:
    return os.environ.get("SCI_RAG_DB_BACKEND", "docker")


def _db(action: str) -> list[str]:
    backend = _backend()
    if backend == "docker":
        return (
            ["docker", "compose", "up", "-d", "--wait"]
            if action == "up"
            else [
                "docker",
                "compose",
                "down",
            ]
        )
    if backend in DB_BACKENDS:
        script, up, down = DB_BACKENDS[backend]
        return [*PYTHON, script, up if action == "up" else down]
    raise TaskRefused(UNKNOWN_BACKEND.format(backend=backend))


def _served(target: str) -> list[list[str]]:
    return [[*SCIRAG, target]]


def _shell_only(target: str) -> list[list[str]]:
    raise TaskRefused(
        f"`{target}` is a POSIX shell pipeline in the Makefile. "
        "Run `make {0}` on macOS or Linux, or copy the block out of Makefile.".format(target)
    )


# name -> (one-line description, plan builder)
TASKS: dict[str, tuple[str, Callable[[], list[list[str]]]]] = {
    "setup": (
        "install dependencies, start Postgres, create the schema",
        lambda: [
            ["uv", "sync", "--extra", "modelscope-embedding", "--extra", "openai"],
            _db("up"),
            [*SCIRAG, "db", "upgrade"],
        ],
    ),
    "db-up": ("start the selected database backend", lambda: [_db("up")]),
    "db-down": ("stop the selected database backend", lambda: [_db("down")]),
    "db-upgrade": ("apply Alembic revisions", lambda: [[*SCIRAG, "db", "upgrade"]]),
    "demo": (
        "ingest the offline demo corpus and score retrieval",
        lambda: [
            [*SCIRAG, "ingest", "--manifest", "data/demo/manifest.jsonl"],
            [
                *SCIRAG,
                "retrieve",
                "How much rice straw was generated in the Colusa Basin in 2023?",
                "--profile",
                "interactive",
                "--limit",
                "3",
            ],
            [*SCIRAG, "eval", "retrieval"],
        ],
    ),
    "demo-cloud": (
        "the full pipeline on the demo corpus (needs generation credentials)",
        lambda: [
            [*SCIRAG, "graph", "extract"],
            [*SCIRAG, "graph", "communities"],
            [
                *SCIRAG,
                "answer",
                "What conversion route suits rice straw given its ash content, "
                "and what yields should I expect?",
            ],
            [*SCIRAG, "eval", "retrieval", "--ablation"],
        ],
    ),
    "test": ("run the whole test suite", lambda: [["uv", "run", "pytest"]]),
    "lint": (
        "ruff check and format check",
        lambda: [
            ["uv", "run", "ruff", "check", "src", "tests", "examples", "scripts"],
            ["uv", "run", "ruff", "format", "--check", "src", "tests", "examples", "scripts"],
        ],
    ),
    "typecheck": ("mypy over the project", lambda: [["uv", "run", "mypy"]]),
    "serve": ("REST at /docs, MCP at /mcp", lambda: _served("serve")),
    "mcp": ("the MCP server on stdio", lambda: _served("mcp")),
    "eval": ("retrieval evaluation", lambda: [[*SCIRAG, "eval", "retrieval"]]),
    "eval-ablation": (
        "retrieval evaluation with every ablation config",
        lambda: [[*SCIRAG, "eval", "retrieval", "--ablation"]],
    ),
    "providers-check": (
        "ask the provider whether the partner models still answer",
        lambda: [
            [
                "uv",
                "run",
                "--extra",
                "anthropic",
                "--extra",
                "openai",
                "python",
                "scripts/check_partner_models.py",
            ]
        ],
    ),
    "docs-reference": (
        "regenerate the CLI and configuration reference pages",
        lambda: [
            [*PYTHON, "scripts/render_cli_docs.py", "--output", "docs/cli.md"],
            [*PYTHON, "scripts/render_config_docs.py", "--output", "docs/configuration.md"],
        ],
    ),
    "cast": (
        "regenerate the terminal cast on the homepage",
        lambda: [[*PYTHON, "scripts/render_cast.py"]],
    ),
    "docs-serve": ("serve the documentation site", lambda: [["uv", "run", "mkdocs", "serve"]]),
    "docs-geometry": (
        "measure the built site in a browser (needs a site build first)",
        lambda: [
            ["uv", "sync", "--group", "docs", "--group", "docs-test"],
            ["uv", "run", "playwright", "install", "chromium"],
            ["uv", "run", "pytest", "tests/docs", "-q"],
        ],
    ),
    "docs": ("build the site as CI does", lambda: _shell_only("docs")),
    "benchmark": ("reproduce docs/benchmarks.md", lambda: _shell_only("benchmark")),
    "benchmark-check": ("re-derive the published numbers", lambda: _shell_only("benchmark-check")),
    "benchmark-refresh-graph": (
        "record a new immutable graph replay candidate",
        lambda: _shell_only("benchmark-refresh-graph"),
    ),
}

COMPOSITES: dict[str, tuple[str, ...]] = {
    # `check` is `lint typecheck test` in the Makefile. Expand it here so the
    # runner reports which step failed instead of one anonymous exit code.
    "check": ("lint", "typecheck", "test"),
}


def plan(target: str) -> list[list[str]]:
    """The argv lines ``target`` would run, without running any of them."""
    if target in COMPOSITES:
        lines: list[list[str]] = []
        for step in COMPOSITES[target]:
            lines.extend(plan(step))
        return lines
    try:
        _, builder = TASKS[target]
    except KeyError:
        raise SystemExit(f"unknown task {target!r}; run --list") from None
    return builder()


def _run(lines: Sequence[Sequence[str]]) -> int:
    for argv in lines:
        printable = shlex.join(list(argv))
        print(f"$ {printable}", flush=True)
        completed = subprocess.run(list(argv), cwd=ROOT)
        if completed.returncode:
            return completed.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tasks.py",
        description="Run the repository's Makefile targets without needing make.",
    )
    parser.add_argument("target", nargs="?", help="task to run; --list shows them")
    parser.add_argument("--list", action="store_true", help="list tasks and exit")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="print the commands the task would run, then exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        width = max(len(name) for name in TASKS)
        for name in [*TASKS, *COMPOSITES]:
            description = TASKS[name][0] if name in TASKS else "lint, typecheck, then test"
            print(f"{name:<{width}}  {description}")
        return 0

    if not args.target:
        parser.error("a target is required; --list shows them")

    try:
        lines = plan(args.target)
    except TaskRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.plan:
        for line in lines:
            print(shlex.join(line))
        return 0

    return _run(lines)


if __name__ == "__main__":
    raise SystemExit(main())
