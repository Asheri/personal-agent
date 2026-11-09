"""Document-level relation commands; writes are explicit and dry-run by default."""

from __future__ import annotations

import json

import typer

from sci_rag.db import get_session_factory
from sci_rag.relate.mentions import build_mentions
from sci_rag.relate.read import document_versions, related_documents
from sci_rag.relate.vectors import rebuild_document_embeddings
from sci_rag.retrieve import RetrievalScope

app = typer.Typer(help="Inspect source-attributed document relations.", no_args_is_help=True)


def _run(operation):  # type: ignore[no-untyped-def]
    from sci_rag.cli.main import run_async

    try:
        result = run_async(operation)
    except (LookupError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(result, ensure_ascii=False))


def _scope(license: list[str] | None, source: list[str] | None) -> RetrievalScope:
    return RetrievalScope(
        license_classes=tuple(license) if license is not None else None,
        sources=tuple(source) if source is not None else None,
    )


def _read(
    document_id: str, relation: str, license: list[str] | None, source: list[str] | None, limit: int
) -> None:
    _run(
        related_documents(
            get_session_factory(),
            document_id,
            relation=relation,
            scope=_scope(license, source),
            limit=limit,
        )
    )


@app.command()
def similar(
    document_id: str,
    license: list[str] | None = typer.Option(None, "--license"),
    source: list[str] | None = typer.Option(None, "--source"),
    limit: int = typer.Option(8, min=1, max=100),
) -> None:
    """Rank current documents using centered means in the caller's visible corpus."""
    _read(document_id, "similar", license, source, limit)


@app.command()
def projects(
    document_id: str,
    license: list[str] | None = typer.Option(None, "--license"),
    source: list[str] | None = typer.Option(None, "--source"),
    limit: int = typer.Option(8, min=1, max=100),
) -> None:
    """List other visible documents assigned to the same project."""
    _read(document_id, "projects", license, source, limit)


@app.command()
def citations(
    document_id: str,
    license: list[str] | None = typer.Option(None, "--license"),
    source: list[str] | None = typer.Option(None, "--source"),
    limit: int = typer.Option(8, min=1, max=100),
) -> None:
    """Read visible outgoing and incoming references with source evidence."""
    _read(document_id, "citations", license, source, limit)


@app.command()
def versions(
    document_id: str,
    license: list[str] | None = typer.Option(None, "--license"),
    source: list[str] | None = typer.Option(None, "--source"),
) -> None:
    """Explicitly inspect retained revisions, preserving all other scope filters."""
    _run(document_versions(get_session_factory(), document_id, scope=_scope(license, source)))


@app.command()
def mentions(apply: bool = typer.Option(False, "--apply")) -> None:
    """Detect literal local links and DOI mentions; default to a dry run."""
    _run(build_mentions(get_session_factory(), apply=apply))


@app.command()
def embeddings(apply: bool = typer.Option(False, "--apply")) -> None:
    """Rebuild document means from existing chunk vectors without model calls."""
    _run(rebuild_document_embeddings(get_session_factory(), apply=apply))
