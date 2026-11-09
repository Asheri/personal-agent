"""The cross-platform runner and the Makefile must not drift apart.

`scripts/tasks.py` exists because `make` is not installed by default on
Windows. That only helps if it runs the same commands, so these tests use the
Makefile as the oracle: `make -n` prints what it would run, and the runner has
to print the same lines.

The comparison covers the targets whose Makefile body is plain commands. A
target with `@echo` lines or a recursive `$(MAKE)` is excluded, because the
dry-run output then contains text the runner deliberately does not reproduce.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
RUNNER = ROOT / "scripts" / "tasks.py"

# Targets whose Makefile body is a plain command list, so `make -n` and
# `--plan` are directly comparable.
COMPARABLE = (
    "db-up",
    "db-down",
    "db-upgrade",
    "demo-cloud",
    "test",
    "lint",
    "typecheck",
    "serve",
    "mcp",
    "eval",
    "eval-ablation",
    "docs-reference",
    "docs-serve",
    "docs-geometry",
    "cast",
    "providers-check",
)

BACKENDS = ("docker", "local", "cloud")


def _load_runner():
    spec = importlib.util.spec_from_file_location("tasks_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _defined_targets() -> list[str]:
    """Targets that actually have a rule.

    `.PHONY` lists one name, `clean-demo`, that no rule defines. It is a stale
    entry in the upstream Makefile, so the guard follows the rules rather than
    the declaration.
    """
    names = []
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([a-z][a-z0-9-]*):.*", line)
        if match is not None:
            names.append(match.group(1))
    return names


def _require_make() -> None:
    if shutil.which("make") is None:
        pytest.skip("GNU make is not installed; the command comparison needs it")


def _make_plan(target: str, backend: str | None = None) -> list[str]:
    command = ["make", "--no-print-directory", "-n", target]
    env = dict(os.environ)
    if backend is not None:
        env["SCI_RAG_DB_BACKEND"] = backend
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, env=env, timeout=30
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return [line for line in lines if not line.startswith(("@", "make"))]


def test_every_makefile_target_is_reachable_from_the_runner() -> None:
    runner = _load_runner()
    known = set(runner.TASKS) | set(runner.COMPOSITES)

    missing = sorted(set(_defined_targets()) - known)

    assert missing == [], f"add these targets to scripts/tasks.py: {missing}"


@pytest.mark.parametrize("target", COMPARABLE)
def test_the_runner_prints_what_the_makefile_would_run(target: str) -> None:
    _require_make()
    runner = _load_runner()
    backend = "docker" if target in {"db-up", "db-down"} else None

    expected = [shlex.split(line) for line in _make_plan(target, backend)]
    actual = runner.plan(target)

    assert actual == expected


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_runner_dispatches_each_database_backend(backend: str) -> None:
    _require_make()
    runner = _load_runner()
    previous = os.environ.get("SCI_RAG_DB_BACKEND")
    os.environ["SCI_RAG_DB_BACKEND"] = backend
    try:
        up = runner.plan("db-up")
        down = runner.plan("db-down")
    finally:
        if previous is None:
            os.environ.pop("SCI_RAG_DB_BACKEND", None)
        else:
            os.environ["SCI_RAG_DB_BACKEND"] = previous

    assert up == [shlex.split(line) for line in _make_plan("db-up", backend)]
    assert down == [shlex.split(line) for line in _make_plan("db-down", backend)]


def test_an_unknown_database_backend_exits_two_with_the_makefile_message() -> None:
    _require_make()
    env = dict(os.environ, SCI_RAG_DB_BACKEND="sqlite")

    runner = subprocess.run(
        [sys.executable, str(RUNNER), "--plan", "db-up"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    # No -n here: the recipe is an echo and an exit, so running it is safe, and
    # a dry run would print the echo instead of writing to stderr.
    make = subprocess.run(
        ["make", "--no-print-directory", "db-up"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert runner.returncode == 2
    assert make.returncode == 2
    message = "Unknown SCI_RAG_DB_BACKEND=sqlite; choose docker, local, or cloud."
    assert message in runner.stderr
    assert message in make.stderr


def test_a_shell_only_target_is_refused_instead_of_half_run() -> None:
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--plan", "benchmark"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    assert "make benchmark" in completed.stderr


def test_list_names_every_task_once() -> None:
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    names = [line.split()[0] for line in completed.stdout.splitlines() if line.strip()]
    assert len(names) == len(set(names))
    assert set(_defined_targets()) <= set(names)
    unknown = sorted(name for name in names if not re.fullmatch(r"[a-z][a-z0-9-]*", name))
    assert unknown == [], f"a task name should be lowercase and hyphenated: {unknown}"
