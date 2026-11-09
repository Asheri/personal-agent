"""One-shot refresh commands for existing schedulers and OS task runners."""

import json
from datetime import UTC, datetime
from pathlib import Path

import typer

app = typer.Typer(help="Refresh local files and inspect durable run history.", no_args_is_help=True)


@app.command("run")
def run(
    root: Path = typer.Argument(..., help="Explicit corpus root."),
    channel: str = typer.Option("manual", help="manual, scheduler, hooks, or poll."),
    manifest: Path | None = typer.Option(
        None, help="Optional corpus manifest directly under the root."
    ),
    no_graph: bool = typer.Option(False, help="Disable model-based graph updates."),
    no_docling: bool = typer.Option(False, help="Use the local pypdf route."),
) -> None:
    """Run one guarded refresh, persist its result, and return its actual exit code."""
    from sci_rag.cli.main import run_async
    from sci_rag.refresh import refresh_corpus

    result = run_async(
        refresh_corpus(
            root=root,
            channel=channel,
            manifest=manifest,
            update_graph=not no_graph,
            prefer_docling=not no_docling,
        )
    )
    directory = Path.cwd() / ".context/refresh-reports"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ("run-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(json.dumps(result, ensure_ascii=False))
    raise typer.Exit(result["exit_code"])


@app.command("history")
def history(limit: int = typer.Option(20, min=1, max=100)) -> None:
    """List content-free outcomes, including failed and interrupted runs."""
    from sci_rag.cli.main import run_async
    from sci_rag.db import get_session_factory
    from sci_rag.refresh import refresh_history

    typer.echo(
        json.dumps(
            run_async(refresh_history(get_session_factory(), limit=limit)), ensure_ascii=False
        )
    )
