"""Project ownership commands; project names are deliberate user output, not logs."""

import json
from dataclasses import asdict
from pathlib import Path

import typer

from sci_rag.config import get_settings
from sci_rag.db import get_session_factory
from sci_rag.domain import load_domain
from sci_rag.projects import (
    assign_project,
    check_project_rules,
    classify_documents,
    create_project,
    list_projects,
    load_project_rules,
    set_manual_tags,
)

app = typer.Typer(help="Manage document projects and personal metadata.", no_args_is_help=True)
rules_app = typer.Typer(help="Check directory ownership rules.", no_args_is_help=True)
app.add_typer(rules_app, name="rules")


def _run(awaitable):  # type: ignore[no-untyped-def]
    from sci_rag.cli.main import run_async

    try:
        return run_async(awaitable)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@app.command("create")
def create(name: str = typer.Argument(..., help="Project display name.")) -> None:
    """Create a project explicitly and print its stable id."""
    row = _run(create_project(get_session_factory(), name))
    typer.echo(json.dumps({"id": row.id, "name": row.name, "slug": row.slug}, ensure_ascii=False))


@app.command("list")
def list_all() -> None:
    """List projects and their current document counts."""
    rows = _run(list_projects(get_session_factory()))
    typer.echo(
        json.dumps(
            [{"id": p.id, "name": p.name, "slug": p.slug, "documents": n} for p, n in rows],
            ensure_ascii=False,
        )
    )


@app.command("assign")
def assign(
    document_id: str,
    project: str = typer.Option(..., "--project", help="Existing project id or slug."),
) -> None:
    """Assign a current document manually and lock its ownership."""
    _run(assign_project(get_session_factory(), document_id, project))
    typer.echo("Manual ownership saved.")


@app.command("tags")
def tags(
    document_id: str,
    tag: list[str] = typer.Option(..., "--tag", help="Manual tag; repeat for multiple tags."),
) -> None:
    """Replace manual tags while preserving automatic tags."""
    _run(set_manual_tags(get_session_factory(), document_id, tag))
    typer.echo("Manual tags saved.")


@app.command("classify")
def classify(
    rules: Path | None = typer.Option(None, help="Ordered project rules YAML."),
    rules_only: bool = typer.Option(
        False, "--rules-only", help="Apply local rules without model calls."
    ),
) -> None:
    """Apply ownership rules, infer remaining projects, and extract automatic tags."""
    settings = get_settings()
    domain = load_domain(settings.domain_dir)
    from sci_rag.llm import get_llm

    llm = None if rules_only else get_llm(settings, role="extraction")
    selected_rules = load_project_rules(rules or domain.directory / "project_rules.yaml")
    stats = _run(
        classify_documents(
            factory=get_session_factory(),
            domain=domain,
            llm=llm,
            rules=selected_rules,
            infer=not rules_only,
            auto_tags=not rules_only,
        )
    )
    typer.echo(json.dumps(asdict(stats)))
    if stats.inference_failed or stats.tags_failed:
        raise typer.Exit(1)


@rules_app.command("check")
def check(rules: Path | None = typer.Option(None, help="Ordered project rules YAML.")) -> None:
    """Report current documents matching multiple different projects."""
    selected_rules = load_project_rules(rules or get_settings().domain_dir / "project_rules.yaml")
    conflicts = _run(check_project_rules(get_session_factory(), selected_rules))
    typer.echo(json.dumps({"conflicts": conflicts}))
    if conflicts:
        raise typer.Exit(1)
