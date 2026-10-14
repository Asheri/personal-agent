"""What the export writes, pinned, and the failures it reports without a database.

`exported_columns` reads the model rather than a hand-written list, so a new
column ships automatically instead of being silently dropped. The trade is that
it could just as silently ship something nobody meant to publish, so the column
sets are pinned here: adding a column to a model turns into a failing test and a
decision, which is the point.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from sci_rag.cli.main import app
from sci_rag.export import TABLES, ParquetUnavailableError, exported_columns

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "300"})

EXPECTED = {
    "documents": {
        "id",
        "title",
        "source",
        "source_ref",
        "authors",
        "publication_year",
        "doi",
        "journal",
        "formatted_citation",
        "license_class",
        "license_source",
        "content_hash",
        "page_count",
        "chunk_count",
        "extra",
        "ingested_at",
    },
    "chunks": {
        "id",
        "document_id",
        "chunk_index",
        "content",
        "token_count",
        "section_path",
        "is_table",
        "embedding_version",
        "graph_extracted_at",
    },
    "entities": {
        "id",
        "name",
        "entity_type",
        "description",
        "aliases",
        "document_ids",
        "chunk_ids",
        "canonical_entity_id",
        "created_at",
        "updated_at",
    },
    "relationships": {
        "id",
        "source_entity_id",
        "target_entity_id",
        "relation_type",
        "evidence",
        "confidence",
        "document_id",
        "chunk_id",
        "created_at",
    },
}


@pytest.mark.parametrize("table", sorted(EXPECTED))
def test_the_exported_columns_are_the_ones_we_intend(table: str) -> None:
    assert set(exported_columns(table)) == EXPECTED[table], (
        f"the {table} export changed shape. If a model gained a column, decide whether it "
        "belongs in an export before updating this set."
    )


def test_the_search_vector_is_never_exported() -> None:
    """A generated tsvector is a Postgres index artifact, not corpus data."""
    assert "search_tsv" not in exported_columns("chunks", include_embeddings=True)


def test_embeddings_are_off_by_default_and_on_by_request() -> None:
    assert "embedding" not in exported_columns("chunks")
    assert "embedding" in exported_columns("chunks", include_embeddings=True)


def test_embeddings_only_affect_the_chunks_table() -> None:
    for table in ("documents", "entities", "relationships"):
        assert exported_columns(table) == exported_columns(table, include_embeddings=True)


def test_an_unknown_format_is_rejected_before_the_database_is_touched() -> None:
    result = runner.invoke(app, ["corpus", "export", "/tmp/whatever", "--format", "avro"])

    assert result.exit_code == 1
    assert "Unknown format" in result.output
    assert "jsonl" in result.output


def test_parquet_without_pyarrow_explains_both_ways_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """The message has to name the extra AND the format that needs no extra."""
    import builtins

    from sci_rag import export as export_module

    real_import = builtins.__import__

    def _no_pyarrow(name: str, *args: object, **kwargs: object) -> object:
        if name == "pyarrow":
            raise ImportError("No module named 'pyarrow'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_pyarrow)

    with pytest.raises(ParquetUnavailableError) as caught:
        export_module._require_pyarrow()

    message = str(caught.value)
    assert "--extra export" in message
    assert "JSONL" in message


class _Recorder:
    """Captures what the CLI decided to ask the exporter for."""

    def __init__(self) -> None:
        self.kwargs: dict = {}

    async def __call__(self, _factory, **kwargs):  # type: ignore[no-untyped-def]
        from pathlib import Path

        from sci_rag.export import ExportResult

        self.kwargs = kwargs
        return ExportResult(
            directory=Path(kwargs["directory"]),
            fmt=kwargs["fmt"],
            counts=dict.fromkeys(("documents", "chunks", "entities", "relationships"), 0),
            files=[Path(kwargs["directory"]) / f"{t}.jsonl" for t in TABLES],
            scoped=kwargs["scope"] is not None,
        )


@pytest.fixture()
def cli_export(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Run the command with the database and the writer stubbed out.

    The CLI layer is where `--license` becomes a `RetrievalScope`, and that
    mapping has two opposite failure modes: reading "no flag" as "deny
    everything" exports nothing, and reading an allowlist as "no filter"
    hands out restricted documents. Neither needs a database to pin.
    """
    from sci_rag import export as export_module
    from sci_rag.cli import main as cli_main

    async def _no_db() -> None:
        return None

    recorder = _Recorder()
    monkeypatch.setattr(cli_main, "_check_db", _no_db)
    monkeypatch.setattr(export_module, "export_corpus", recorder)
    return recorder


def test_no_license_flag_means_unrestricted(cli_export: _Recorder, tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = runner.invoke(app, ["corpus", "export", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert cli_export.kwargs["scope"] is None
    assert "Scoped export" not in result.output


def test_a_license_flag_becomes_a_fail_closed_allowlist(cli_export: _Recorder, tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = runner.invoke(
        app,
        ["corpus", "export", str(tmp_path), "--license", "public", "--license", "open_commercial"],
    )

    assert result.exit_code == 0, result.output
    assert cli_export.kwargs["scope"].license_classes == ("public", "open_commercial")
    assert "Scoped export" in result.output


def test_embeddings_are_opt_in_through_the_cli(cli_export: _Recorder, tmp_path) -> None:  # type: ignore[no-untyped-def]
    runner.invoke(app, ["corpus", "export", str(tmp_path)])
    assert cli_export.kwargs["include_embeddings"] is False

    result = runner.invoke(app, ["corpus", "export", str(tmp_path), "--include-embeddings"])
    assert cli_export.kwargs["include_embeddings"] is True
    assert "embeddings were omitted" not in result.output


def test_the_format_reaches_the_exporter(cli_export: _Recorder, tmp_path) -> None:  # type: ignore[no-untyped-def]
    runner.invoke(app, ["corpus", "export", str(tmp_path), "--format", "parquet"])
    assert cli_export.kwargs["fmt"] == "parquet"
