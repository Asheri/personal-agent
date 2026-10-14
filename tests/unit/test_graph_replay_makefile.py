"""The Makefile's reviewed graph-replay entry points."""

from __future__ import annotations

import re
from pathlib import Path

MAKEFILE = Path(__file__).parents[2] / "Makefile"


def _text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def _target_body(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}(?:\s*:[^\n]*)?\n(.*?)(?=^[A-Za-z0-9_.-]+\s*:[^=]|\Z)",
        text,
    )
    assert match, f"Makefile must define {name}"
    return match.group(1)


def test_benchmark_requires_one_explicit_reviewed_graph_replay() -> None:
    """The reproducible benchmark cannot discover replay evidence by recency."""
    text = _text()
    pointer = re.search(r"(?m)^BENCH_GRAPH_REPLAY\s*:=\s*(\S+)\s*$", text)

    assert pointer, "Makefile must name the reviewed graph replay explicitly"
    artifact = pointer.group(1)
    assert artifact.startswith("data/demo/graph-replay/") and artifact.endswith(".json")
    assert not any(marker in artifact for marker in ("$(", "*", "?", "[")), (
        "the reviewed artifact path must not use shell, wildcard, or modification-time discovery"
    )

    benchmark = _target_body(text, "benchmark")
    assert "scripts/graph_replay.py require" in benchmark
    assert '--artifact "$(BENCH_GRAPH_REPLAY)"' in benchmark
    assert '--receipt "$(GRAPH_REPLAY_RECEIPT)"' in benchmark
    assert "sci-rag graph extract" not in benchmark, (
        "the published benchmark must require replay instead of sampling a new graph"
    )
    assert "named, disposable PostgreSQL database" in text
    assert "Do not clear an unrelated development corpus" in text


def test_benchmark_refresh_graph_writes_a_separate_candidate() -> None:
    """Credentialed refresh never selects or overwrites approved evidence."""
    text = _text()
    phony = next(line for line in text.splitlines() if line.startswith(".PHONY:"))
    refresh = _target_body(text, "benchmark-refresh-graph")

    assert "benchmark-refresh-graph" in phony
    assert "scripts/graph_replay.py refresh" in refresh
    assert "--artifact-dir data/demo/graph-replay" in refresh
    assert '--receipt "$(GRAPH_REPLAY_RECEIPT)"' in refresh
    assert "BENCH_GRAPH_REPLAY" not in refresh, (
        "refresh writes a content-addressed candidate; review selects it later"
    )
