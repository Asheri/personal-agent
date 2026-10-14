"""`sci-rag build`: one command from documents to a queryable corpus.

The command composes the same helpers `ingest`, `graph extract`, and `graph
communities` use, so these tests stub the helpers and check the decisions
`build` makes on top of them: whether the graph steps run, what it says when
they do not, and how a failed ingestion propagates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from typer.testing import CliRunner

from sci_rag.cli import main as cli
from sci_rag.cli.main import app
from sci_rag.config import Settings

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class _IngestReport:
    failed: int = 0


@dataclass
class _ExtractStats:
    batches_failed: int = 0


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:
    """Record which pipeline helpers `build` calls, without a database or a model."""
    calls: dict[str, list[object]] = {"ingest": [], "extract": [], "communities": []}

    def fake_ingest(path, manifest, **kwargs):  # type: ignore[no-untyped-def]
        calls["ingest"].append((path, manifest, kwargs))
        return _IngestReport()

    def fake_extract(**kwargs):  # type: ignore[no-untyped-def]
        calls["extract"].append(kwargs)
        return _ExtractStats()

    def fake_communities(**kwargs):  # type: ignore[no-untyped-def]
        calls["communities"].append(kwargs)

    monkeypatch.setattr(cli, "_ingest_and_report", fake_ingest)
    monkeypatch.setattr(cli, "_run_graph_extract", fake_extract)
    monkeypatch.setattr(cli, "_run_graph_communities", fake_communities)
    return calls


def _settings(**overrides: object) -> Settings:
    base = {"embedding_provider": "local-hash", "google_api_key": None, "gcp_project": None}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_offline_build_ingests_and_says_why_the_graph_was_skipped(
    stubs: dict[str, list[object]], monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(), raising=False)
    monkeypatch.setattr("sci_rag.config.get_settings", lambda: _settings())

    result = runner.invoke(app, ["build", str(tmp_path)])
    output = _ANSI.sub("", result.output)

    assert result.exit_code == 0, output
    assert len(stubs["ingest"]) == 1
    assert stubs["extract"] == []
    assert stubs["communities"] == []
    assert "Skipping the knowledge graph: no LLM provider credentials are configured" in output
    assert "sci-rag graph extract" in output
    assert 'sci-rag answer "..."' in output


def test_credentialed_build_runs_extraction_then_communities(
    stubs: dict[str, list[object]], monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "sci_rag.config.get_settings",
        lambda: _settings(embedding_provider="google", google_api_key="test-key"),
    )

    result = runner.invoke(app, ["build", str(tmp_path), "--batch-size", "4"])
    output = _ANSI.sub("", result.output)

    assert result.exit_code == 0, output
    assert len(stubs["extract"]) == 1
    assert stubs["extract"][0] == {"batch_size": 4, "reprocess_all": False, "max_chunks": None}
    assert len(stubs["communities"]) == 1
    assert "Skipping" not in output


def test_no_graph_skips_the_graph_even_with_a_credential(
    stubs: dict[str, list[object]], monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "sci_rag.config.get_settings",
        lambda: _settings(embedding_provider="google", google_api_key="test-key"),
    )

    result = runner.invoke(app, ["build", str(tmp_path), "--no-graph"])
    output = _ANSI.sub("", result.output)

    assert result.exit_code == 0, output
    assert stubs["extract"] == []
    assert "Skipping the knowledge graph (--no-graph)" in output


def test_a_failed_document_fails_the_build_after_finishing_it(
    stubs: dict[str, list[object]], monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sci_rag.config.get_settings", lambda: _settings())
    monkeypatch.setattr(cli, "_ingest_and_report", lambda *a, **k: _IngestReport(failed=2))

    result = runner.invoke(app, ["build", str(tmp_path)])

    assert result.exit_code == 1


def test_build_needs_exactly_one_input() -> None:
    """The real helper validates the inputs before it touches a database."""
    result = runner.invoke(app, ["build"])
    assert result.exit_code != 0
    assert "exactly one of" in _ANSI.sub("", result.output)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, False),
        ({"embedding_provider": "google", "google_api_key": "k"}, True),
        ({"embedding_provider": "google", "gcp_project": "p"}, True),
        ({"anthropic_api_key": "k"}, True),
        ({"openai_base_url": "http://localhost:11434/v1"}, True),
    ],
)
def test_has_model_credential(overrides: dict[str, object], expected: bool) -> None:
    assert cli._has_model_credential(_settings(**overrides)) is expected


def test_empty_manifest_points_at_a_waiting_proposal(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "corpus.jsonl"
    manifest.write_text("# one JSON object per line\n", encoding="utf-8")
    (tmp_path / "corpus.jsonl.proposed").write_text("{}\n", encoding="utf-8")

    result = runner.invoke(app, ["ingest", "--manifest", str(manifest)])
    output = _ANSI.sub("", result.output)

    assert result.exit_code == 1
    assert "lists no documents" in output
    assert "corpus.jsonl.proposed" in output


def test_help_groups_commands_by_stage() -> None:
    output = _ANSI.sub("", runner.invoke(app, ["--help"]).output)
    positions = [output.index(panel) for panel in cli.PANEL_ORDER]
    assert positions == sorted(positions), "panels should appear in the documented order"
    assert output.index("Start here") < output.index(" new ")
