"""Thin CLI front door for scoped corpus browsing."""

import json

import typer

app = typer.Typer(
    help="Browse current files by project, document date, and named topic.", no_args_is_help=True
)


def run(dimension, by=None, filters=None, page=1, page_size=20):  # type: ignore[no-untyped-def]
    from sci_rag.cli.main import run_async
    from sci_rag.server.errors import ApiError
    from sci_rag.server.service import RagService

    try:
        values = json.loads(filters) if filters else {}
        result = run_async(
            RagService().browse_corpus(
                dimension=dimension, by=by, filters=values, page=page, page_size=page_size
            )
        )
    except (ValueError, ApiError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command("documents")
def documents(
    filters: str | None = typer.Option(
        None,
        help="JSON filter object: sources, projects, date_min/date_max, tags, auto_tags, entity_names.",
    ),
    page: int = typer.Option(1, min=1),
    page_size: int = typer.Option(20, min=1, max=100),
) -> None:
    """List current files in document-date order, with explicit pagination."""
    run("documents", filters=filters, page=page, page_size=page_size)


@app.command("facets")
def facets(filters: str | None = typer.Option(None, help="JSON filter object.")) -> None:
    """Count every registered dimension, including empty-value buckets."""
    run("facets", filters=filters)


@app.command("projects")
def projects(
    by: str | None = typer.Option(None, help="Stable project id to browse; omit for counts."),
    filters: str | None = None,
    page: int = typer.Option(1, min=1),
    page_size: int = typer.Option(20, min=1, max=100),
) -> None:
    """Browse project counts or documents belonging to one project."""
    run("project", by=by, filters=filters, page=page, page_size=page_size)


@app.command("timeline")
def timeline(
    by: str | None = typer.Option(None, help="Month YYYY-MM; omit for monthly counts."),
    filters: str | None = None,
    page: int = typer.Option(1, min=1),
    page_size: int = typer.Option(20, min=1, max=100),
) -> None:
    """Browse document-date months, retaining the unknown-date bucket."""
    run("time", by=by, filters=filters, page=page, page_size=page_size)


@app.command("topics")
def topics(
    by: str | None = typer.Option(None, help="Exact named topic; omit for counts."),
    filters: str | None = None,
    page: int = typer.Option(1, min=1),
    page_size: int = typer.Option(20, min=1, max=100),
) -> None:
    """Browse literal named topics; community summaries never define filters."""
    run("topic", by=by, filters=filters, page=page, page_size=page_size)
