"""The sci-rag command line.

Run everything from the project root (paths in settings are resolved
relative to where you run the command). The short path from documents to
answers:

    sci-rag doctor                # is the database up, is a model reachable?
    sci-rag build data/raw        # ingest a folder, then build the graph
    sci-rag answer "question"     # a cited answer from your documents
    sci-rag retrieve "question"   # the evidence behind it, layer by layer
    sci-rag stats                 # what is in the knowledge base

The commands are grouped in `--help` in the order a new project meets them:
start here, build the knowledge base, ask questions, measure quality, serve,
maintain. The grouping is presentation only; every command is reachable
regardless of which panel lists it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from sci_rag.campaigns.screen import ScreeningReport

app = typer.Typer(
    name="sci-rag",
    help="Retrieval-augmented generation, built around your scientific domain.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

# The panels `sci-rag --help` groups commands under, in the order a new
# project meets them. Every top-level command names one of these.
PANEL_START = "Start here"
PANEL_BUILD = "Build your knowledge base"
PANEL_ASK = "Ask questions"
PANEL_MEASURE = "Measure quality"
PANEL_SERVE = "Serve"
PANEL_MAINTAIN = "Maintain"
PANEL_ORDER = (PANEL_START, PANEL_BUILD, PANEL_ASK, PANEL_MEASURE, PANEL_SERVE, PANEL_MAINTAIN)

db_app = typer.Typer(help="Create or upgrade the database tables.", no_args_is_help=True)
app.add_typer(db_app, name="db", rich_help_panel=PANEL_START)
graph_app = typer.Typer(
    help=(
        "Build the knowledge graph: extract concepts and relationships from your documents, "
        "then summarize the clusters they form."
    ),
    no_args_is_help=True,
)
app.add_typer(graph_app, name="graph", rich_help_panel=PANEL_BUILD)
eval_app = typer.Typer(
    help=(
        "Measure quality against your seed questions: retrieval scores, what each "
        "retrieval layer contributes, and graded answers."
    ),
    no_args_is_help=True,
)
app.add_typer(eval_app, name="eval", rich_help_panel=PANEL_MEASURE)
embed_app = typer.Typer(
    help="Re-embed rows left behind after an embedding model change.",
    no_args_is_help=True,
)
app.add_typer(embed_app, name="embed", rich_help_panel=PANEL_MAINTAIN)
corpus_app = typer.Typer(
    help=(
        "Look after the corpus: rights report, publication metadata, snapshots, "
        "export, and deletion."
    ),
    no_args_is_help=True,
)
app.add_typer(corpus_app, name="corpus", rich_help_panel=PANEL_MAINTAIN)
campaign_app = typer.Typer(
    help=(
        "Find papers to add: search by topic or DOI list, check each one's rights, "
        "and download the open-access PDFs into a manifest you can ingest."
    ),
    no_args_is_help=True,
)
app.add_typer(campaign_app, name="campaign", rich_help_panel=PANEL_BUILD)
manifest_app = typer.Typer(
    help="Check a corpus manifest (data/corpus.jsonl) before you ingest it.",
    no_args_is_help=True,
)
app.add_typer(manifest_app, name="manifest", rich_help_panel=PANEL_BUILD)

console = Console()


def _load_dotenv_into_environ(path: Path | None = None) -> list[str]:
    """Export `.env` into the process environment, without overriding it.

    pydantic-settings reads `.env` into :class:`~sci_rag.config.Settings` but
    never exports it, so anything that reads the environment directly could
    not see values the documentation tells users to put there: Typer's
    ``envvar=`` lookups, and third-party keys like ``OPENALEX_API_KEY`` that
    can never be `Settings` fields because they carry no ``SCI_RAG_`` prefix.

    A real environment variable always wins, so a one-off ``VAR=x sci-rag ...``
    still overrides the file.
    """
    env_path = path if path is not None else Path(".env")
    if not env_path.is_file():
        return []
    exported: list[str] = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.removeprefix("export ").partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("\"'")
        exported.append(key)
    return exported


@app.callback()
def _bootstrap() -> None:
    """Runs before every command; see :func:`_load_dotenv_into_environ`."""
    _load_dotenv_into_environ()


def find_repo_root() -> Path:
    """Walk up from the current directory to the folder holding alembic.ini."""
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "alembic.ini").exists():
            return candidate
    raise typer.BadParameter(
        "Could not find the project root (the directory holding alembic.ini). "
        "Run sci-rag commands from inside your project directory."
    )


def run_async(coro):  # type: ignore[no-untyped-def]
    """asyncio.run with the common first-run failures translated into
    short, actionable messages instead of tracebacks."""
    from sci_rag.config import get_settings

    try:
        return asyncio.run(coro)
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()
        if "does not exist" in lowered and ("relation" in lowered or "table" in lowered):
            console.print(
                "[red]The database schema is missing.[/red] Create it with:\n"
                "  [bold]uv run sci-rag db upgrade[/bold]"
            )
        elif any(
            marker in lowered
            for marker in (
                "connection refused",
                "connect call failed",
                "connection was closed",
                "name or service not known",
                "nodename nor servname",
            )
        ):
            from sci_rag.cli.doctor import _database_start_hint

            console.print(
                f"[red]Cannot reach Postgres[/red] at "
                f"[bold]{get_settings().database_url.split('@')[-1]}[/bold].\n"
                f"{_database_start_hint()}, or run [bold]make db-up[/bold]. "
                "If the database lives elsewhere, point SCI_RAG_DATABASE_URL at it. "
                "Then retry.\n"
                "Run [bold]uv run sci-rag doctor[/bold] for a full checkup."
            )
        elif (
            "no google credentials configured" in lowered
            or "no llm provider credentials configured" in lowered
        ):
            console.print(f"[red]{exc}[/red]")
        else:
            raise
        raise typer.Exit(1) from None


async def _check_db() -> None:
    """Fail fast with a clear message when Postgres is unreachable.

    Retrieval itself degrades per stage by design, which is right for a
    server but misleading in a terminal: a dead database would read as
    "no results". A cheap SELECT 1 up front turns that into the real story.
    """
    from sqlalchemy import text

    from sci_rag.db import get_engine

    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


def _csv(value: str | None) -> tuple[str, ...]:
    """Split a comma-separated option into a tuple, dropping blanks."""
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _campaign_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        raise typer.BadParameter("campaign name must contain a letter or number")
    return slug[:80].rstrip("-")


def _print_screening_report(report: ScreeningReport) -> None:
    decisions = Table(title="Campaign screening decisions")
    decisions.add_column("DOI")
    decisions.add_column("Decision")
    decisions.add_column("Confidence", justify="right")
    decisions.add_column("Reason")
    for item in report.decisions:
        confidence = "" if item.confidence is None else f"{item.confidence:.2f}"
        decisions.add_row(item.doi, item.decision, confidence, item.reason)
    console.print(decisions)

    prisma = Table(title="PRISMA-aligned screening counts")
    prisma.add_column("Measure")
    prisma.add_column("Count", justify="right")
    for label, count in (
        ("identified", report.prisma.identified),
        ("duplicates removed", report.prisma.duplicates_removed),
        ("screened", report.prisma.screened),
        ("excluded", report.prisma.excluded),
        ("included", report.prisma.included),
        ("awaiting review", report.prisma.awaiting_review),
    ):
        prisma.add_row(label, str(count))
    for reason, count in report.prisma.excluded_by_reason.items():
        prisma.add_row(f"  excluded: {reason}", str(count))
    console.print(prisma)
    console.print(
        f"{report.prisma.included} included, {report.prisma.excluded} excluded, "
        f"{report.prisma.awaiting_review} awaiting review, "
        f"{report.malformed_responses} malformed model response(s), "
        f"{report.missing_abstracts} missing abstract(s)."
    )


def _scope(  # type: ignore[no-untyped-def]
    license_classes: str | None,
    sources: str | None,
    *,
    year_min: int | None = None,
    year_max: int | None = None,
    authors: str | None = None,
    journals: str | None = None,
    exclude_dois: str | None = None,
    exclude_retracted: bool = False,
):
    from sci_rag.retrieve import RetrievalScope

    return RetrievalScope(
        license_classes=_csv(license_classes) if license_classes else None,
        sources=_csv(sources) if sources else None,
        year_min=year_min,
        year_max=year_max,
        authors=_csv(authors),
        journals=_csv(journals),
        exclude_dois=_csv(exclude_dois),
        exclude_retracted=exclude_retracted,
    )


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Create or upgrade the database schema (runs the Alembic migrations)."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    root = find_repo_root()
    config = AlembicConfig(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    alembic_command.upgrade(config, "head")
    console.print("[green]Database schema is up to date.[/green]")


def _has_model_credential(settings) -> bool:  # type: ignore[no-untyped-def]
    """Whether any generation provider could be reached with the current settings."""
    if settings.is_offline():
        return False
    if settings.credentials_mode() != "none":
        return True
    return bool(settings.anthropic_api_key or settings.openai_api_key or settings.openai_base_url)


def _ingest_and_report(  # type: ignore[no-untyped-def]
    path: Path | None,
    manifest: Path | None,
    *,
    source: str,
    no_docling: bool,
    chunk_tokens: int,
    overlap_tokens: int,
):
    """Load the documents, ingest them, print the report; shared by ingest and build."""
    from sci_rag.config import get_settings
    from sci_rag.embed import get_embedder
    from sci_rag.ingest import discover_folder, ingest_entries, load_manifest

    if (path is None) == (manifest is None):
        raise typer.BadParameter("Provide exactly one of: a folder PATH, or --manifest FILE.")
    entries = load_manifest(manifest) if manifest else discover_folder(path, source=source)  # type: ignore[arg-type]
    if not entries:
        if manifest is not None:
            hint = f"[yellow]Nothing to ingest: {manifest} lists no documents.[/yellow]"
            proposed = manifest.with_name(manifest.name + ".proposed")
            if proposed.exists():
                hint += (
                    f"\nA drafted manifest is waiting at [bold]{proposed}[/bold]. Review it, "
                    f"set each row's license_class, then move it over {manifest.name}."
                )
            else:
                hint += (
                    "\nAdd one JSON line per document, or draft the file from a folder with "
                    "[bold]sci-rag draft manifest --folder data/raw[/bold]."
                )
        else:
            hint = (
                f"[yellow]Nothing to ingest: no supported files under {path}.[/yellow]\n"
                "Supported: PDF, HTML, Markdown, and plain text."
            )
        console.print(hint)
        raise typer.Exit(1)
    console.print(f"Ingesting [bold]{len(entries)}[/bold] document(s)...")

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        # Built inside the coroutine so a missing credential reaches run_async's
        # short message instead of surfacing as a traceback.
        embedder = get_embedder(get_settings())
        return await ingest_entries(
            entries,
            embedder=embedder,
            target_tokens=chunk_tokens,
            overlap_tokens=overlap_tokens,
            prefer_docling=not no_docling,
        )

    report = run_async(run())

    table = Table(title="Ingestion report")
    table.add_column("Document")
    table.add_column("Status")
    table.add_column("Chunks", justify="right")
    table.add_column("Detail")
    for outcome in report.outcomes:
        color = {"ingested": "green", "skipped_duplicate": "yellow", "failed": "red"}[
            outcome.status
        ]
        table.add_row(
            Path(outcome.path).name,
            f"[{color}]{outcome.status}[/{color}]",
            str(outcome.chunk_count or ""),
            outcome.detail,
        )
    console.print(table)
    console.print(
        f"[green]{report.ingested} ingested[/green], "
        f"[yellow]{report.skipped} skipped[/yellow], "
        f"[red]{report.failed} failed[/red]."
    )
    return report


@app.command(rich_help_panel=PANEL_BUILD)
def ingest(
    path: Path | None = typer.Argument(
        None, help="Folder of documents to ingest (PDF, HTML, Markdown, or plain text)."
    ),
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help="A JSONL corpus manifest: one line per document with title, authors, and rights.",
    ),
    source: str = typer.Option(
        "local", "--source", help="Source label recorded on documents ingested from a folder."
    ),
    no_docling: bool = typer.Option(
        False, "--no-docling", help="Skip Docling even if installed (use the pypdf fallback)."
    ),
    chunk_tokens: int = typer.Option(800, help="Target tokens per chunk."),
    overlap_tokens: int = typer.Option(150, help="Overlap tokens between chunks."),
) -> None:
    """Ingest documents: parse, chunk, embed, and store them.

    Pass a folder for a first run (every document is recorded with
    license_class "unknown"), or a manifest once you have declared each
    document's rights. `sci-rag build` runs this and the graph steps together.
    """
    report = _ingest_and_report(
        path,
        manifest,
        source=source,
        no_docling=no_docling,
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
    )
    if report.failed:
        raise typer.Exit(1)


@app.command(rich_help_panel=PANEL_BUILD)
def build(
    path: Path | None = typer.Argument(
        None, help="Folder of documents to ingest (PDF, HTML, Markdown, or plain text)."
    ),
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help="A JSONL corpus manifest: one line per document with title, authors, and rights.",
    ),
    source: str = typer.Option(
        "local", "--source", help="Source label recorded on documents ingested from a folder."
    ),
    no_docling: bool = typer.Option(
        False, "--no-docling", help="Skip Docling even if installed (use the pypdf fallback)."
    ),
    no_graph: bool = typer.Option(
        False, "--no-graph", help="Stop after ingestion; skip the knowledge graph."
    ),
    batch_size: int = typer.Option(10, help="Chunks per graph-extraction model call."),
) -> None:
    """Build the knowledge base in one go: ingest, then extract the graph and its summaries.

    Ingestion works with any embedding setup, including offline. The graph
    steps need LLM provider credentials; without them, or with --no-graph, they are
    skipped and the command says so. Re-running only processes new chunks.
    """
    from sci_rag.config import get_settings

    report = _ingest_and_report(
        path,
        manifest,
        source=source,
        no_docling=no_docling,
        chunk_tokens=800,
        overlap_tokens=150,
    )
    failed = bool(report.failed)

    settings = get_settings()
    if no_graph:
        console.print("[dim]Skipping the knowledge graph (--no-graph).[/dim]")
    elif not _has_model_credential(settings):
        console.print(
            "[yellow]Skipping the knowledge graph: no LLM provider credentials are configured.[/yellow] "
            "Vector and keyword retrieval already work. To add the graph later, set "
            "SCI_RAG_GOOGLE_API_KEY (or SCI_RAG_GCP_PROJECT) in .env and run "
            "[bold]sci-rag graph extract[/bold] then [bold]sci-rag graph communities[/bold]."
        )
    else:
        console.print("\nBuilding the knowledge graph (one model call per batch of chunks)...")
        extraction = _run_graph_extract(batch_size=batch_size, reprocess_all=False, max_chunks=None)
        if extraction.batches_failed:
            failed = True
        console.print("Summarizing entity clusters...")
        _run_graph_communities(min_size=3)

    console.print(
        '\nDone. Ask a question with [bold]sci-rag answer "..."[/bold], or see what came back '
        'with [bold]sci-rag retrieve "..."[/bold]. [bold]sci-rag stats[/bold] shows the counts.'
    )
    if failed:
        raise typer.Exit(1)


@manifest_app.command("lint")
def manifest_lint(
    path: Path = typer.Argument(..., help="The JSONL corpus manifest to check."),
) -> None:
    """Check a corpus manifest before ingesting it.

    Ingestion reports a bad manifest one document at a time, after the run has
    already started. This reports every problem at once, before anything is
    parsed, embedded, or written.
    """
    from sci_rag.ingest.manifest import lint_manifest

    if not path.is_file():
        console.print(f"[red]No manifest at {path}[/red]")
        raise typer.Exit(1)

    report = lint_manifest(path)

    if report.findings:
        table = Table(title=f"Manifest problems in {path.name}")
        table.add_column("Line", justify="right")
        table.add_column("Level")
        table.add_column("Check")
        table.add_column("Detail")
        for finding in report.findings:
            color = "red" if finding.level == "error" else "yellow"
            table.add_row(
                str(finding.line),
                f"[{color}]{finding.level}[/{color}]",
                finding.code,
                finding.message,
            )
        console.print(table)

    summary = (
        f"{report.entry_count} entr{'y' if report.entry_count == 1 else 'ies'} checked, "
        f"[red]{len(report.errors)} error(s)[/red], "
        f"[yellow]{len(report.warnings)} warning(s)[/yellow]."
    )
    console.print(summary)
    if not report.ok:
        raise typer.Exit(1)
    console.print(f"[green]{path.name} is ready to ingest.[/green]")


@app.command(rich_help_panel=PANEL_ASK)
def retrieve(
    query: str = typer.Argument(..., help="The question to search for."),
    profile: str = typer.Option(
        "deep",
        help=(
            "Which retrieval layers run: interactive (vector and keyword, fast), "
            "deep (all five), or auto (a router picks per question)."
        ),
    ),
    limit: int = typer.Option(8, help="How many results to return after the layers are combined."),
    license_classes: str | None = typer.Option(
        None, "--license", help="Comma-separated license allowlist (e.g. public,open_commercial)."
    ),
    sources: str | None = typer.Option(None, "--source", help="Comma-separated source allowlist."),
    year_min: int | None = typer.Option(
        None, "--year-min", help="Earliest publication year to include."
    ),
    year_max: int | None = typer.Option(
        None, "--year-max", help="Latest publication year to include."
    ),
    authors: str | None = typer.Option(
        None, "--author", help="Comma-separated author allowlist (exact strings)."
    ),
    journals: str | None = typer.Option(
        None, "--journal", help="Comma-separated journal allowlist."
    ),
    exclude_dois: str | None = typer.Option(
        None, "--exclude-doi", help="Comma-separated DOIs to drop."
    ),
    explain_routing: bool = typer.Option(
        False,
        "--explain-routing",
        help="Print what the auto router decides for this query (and why) before retrieving.",
    ),
) -> None:
    """Search the corpus and show the evidence: which layer found each result, and why it ranked."""
    from sci_rag.retrieve import Retriever

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        retriever = Retriever()
        decision = None
        if explain_routing:
            from sci_rag.retrieve.router import route

            decision = await route(query, retriever.domain)
        result = await retriever.retrieve(
            query,
            profile=profile,
            limit=limit,
            scope=_scope(
                license_classes,
                sources,
                year_min=year_min,
                year_max=year_max,
                authors=authors,
                journals=journals,
                exclude_dois=exclude_dois,
            ),
        )
        return result, decision

    result, decision = run_async(run())

    if decision is not None:
        routing_table = Table(title="Routing decision (what --profile auto would run)")
        routing_table.add_column("What")
        routing_table.add_column("Value")
        routing_table.add_row("resolved profile", decision.profile)
        routing_table.add_row("graph layer", "on" if decision.include_graph else "off")
        routing_table.add_row("community layer", "on" if decision.include_community else "off")
        routing_table.add_row("hyde layer", "on" if decision.include_hyde else "off")
        routing_table.add_row("matched query class", decision.matched_class or "none")
        for i, reason in enumerate(decision.reasons):
            routing_table.add_row("why" if i == 0 else "", reason)
        console.print(routing_table)
        if profile != "auto":
            console.print(
                f"(this request actually ran with [bold]--profile {profile}[/bold]; "
                "use --profile auto to let the router drive)"
            )

    trace_table = Table(title=f"Retrieval stages ({profile} profile)")
    trace_table.add_column("Stage")
    trace_table.add_column("Status")
    trace_table.add_column("ms", justify="right")
    trace_table.add_column("Candidates", justify="right")
    for trace in result.traces:
        color = {
            "success": "green",
            "empty": "cyan",
            "disabled": "dim",
            "skipped": "yellow",
            "timeout": "red",
            "error": "red",
            "denied": "red",
        }.get(trace.status, "white")
        trace_table.add_row(
            trace.stage,
            f"[{color}]{trace.status}[/{color}]",
            str(trace.duration_ms or ""),
            str(trace.candidate_count or ""),
        )
    console.print(trace_table)

    if not result.items:
        console.print("[yellow]No results within the current scope.[/yellow]")
        raise typer.Exit(0)
    for i, item in enumerate(result.items, start=1):
        header = f"[bold]{i}. {item.title}[/bold]"
        if item.section_path:
            header += f" [dim]({item.section_path})[/dim]"
        console.print(header)
        console.print(
            f"   score={item.score:.4f} layers={'+'.join(item.layers)} "
            f"license={item.license_class} kind={item.kind}"
        )
        preview = item.content.replace("\n", " ")
        console.print(f"   [dim]{preview[:220]}{'...' if len(preview) > 220 else ''}[/dim]")


@app.command(rich_help_panel=PANEL_ASK)
def answer(
    query: str = typer.Argument(..., help="The question to answer."),
    profile: str = typer.Option(
        "deep",
        help=(
            "Which retrieval layers run: interactive (vector and keyword, fast), "
            "deep (all five), or auto (a router picks per question)."
        ),
    ),
    limit: int = typer.Option(8, help="How many sources to give the model."),
    license_classes: str | None = typer.Option(
        None, "--license", help="Comma-separated license allowlist (e.g. public,open_commercial)."
    ),
    sources: str | None = typer.Option(None, "--source", help="Comma-separated source allowlist."),
    year_min: int | None = typer.Option(
        None, "--year-min", help="Earliest publication year to include."
    ),
    year_max: int | None = typer.Option(
        None, "--year-max", help="Latest publication year to include."
    ),
    authors: str | None = typer.Option(
        None, "--author", help="Comma-separated author allowlist (exact strings)."
    ),
    journals: str | None = typer.Option(
        None, "--journal", help="Comma-separated journal allowlist."
    ),
    exclude_dois: str | None = typer.Option(
        None, "--exclude-doi", help="Comma-separated DOIs to drop."
    ),
    include_retracted: bool = typer.Option(
        False,
        "--include-retracted",
        help="Deliberately allow known retracted papers as answer evidence.",
    ),
    include_compression: bool | None = typer.Option(
        None,
        "--compression/--no-compression",
        help=(
            "Summarize each retrieved source before answering, or send the full text. "
            "Omit to use the domain profile's setting."
        ),
    ),
) -> None:
    """Answer a question from your documents, with numbered citations. Needs LLM provider credentials."""
    from sci_rag.answer import AnswerEngine

    async def run() -> None:
        await _check_db()
        engine = AnswerEngine()
        console.print(f"[dim]Retrieving ({profile} profile)...[/dim]")
        async for event in engine.answer_stream(
            query,
            profile=profile,
            limit=limit,
            scope=_scope(
                license_classes,
                sources,
                year_min=year_min,
                year_max=year_max,
                authors=authors,
                journals=journals,
                exclude_dois=exclude_dois,
                exclude_retracted=not include_retracted,
            ),
            include_compression=include_compression,
        ):
            if event.type == "retrieval_done":
                degraded = event.data["degraded_stages"]
                note = f" (degraded: {', '.join(degraded)})" if degraded else ""
                console.print(
                    f"[dim]{event.data['item_count']} sources retrieved{note}. Generating...[/dim]\n"
                )
            elif event.type == "delta":
                console.print(event.data["text"], end="")
            elif event.type == "compression_done" and event.data["enabled"]:
                console.print(
                    "[dim]Compressed sources: "
                    f"{event.data['prompt_tokens_before']} -> "
                    f"{event.data['prompt_tokens_after']} prompt tokens; "
                    f"{event.data['failure_count']} fallback(s).[/dim]"
                )
            elif event.type == "citations":
                cited = [c for c in event.data["citations"] if c["cited"]]
                if cited:
                    console.print("\n\n[bold]Sources[/bold]")
                    for c in cited:
                        console.print(f"  [{c['index']}] {c['citation'] or c['title']}")
            elif event.type == "error":
                console.print(f"\n[red]{event.data['message']}[/red]")
                raise typer.Exit(1)
        console.print()

    run_async(run())


def _run_graph_extract(*, batch_size: int, reprocess_all: bool, max_chunks: int | None):  # type: ignore[no-untyped-def]
    """Run extraction and print its report; shared by `graph extract` and `build`."""
    from sci_rag.config import get_settings
    from sci_rag.db import get_session_factory
    from sci_rag.domain import load_domain
    from sci_rag.graph import extract_graph
    from sci_rag.llm import get_llm

    settings = get_settings()

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await extract_graph(
            session_factory=get_session_factory(),
            llm=get_llm(settings, role="extraction"),
            domain=load_domain(settings.domain_dir),
            batch_size=batch_size,
            reprocess_all=reprocess_all,
            max_chunks=max_chunks,
        )

    stats_result = run_async(run())
    console.print(
        f"Processed [bold]{stats_result.chunks_processed}[/bold] chunk(s): "
        f"[green]{stats_result.entities_created} entities created[/green], "
        f"{stats_result.entities_updated} enriched, "
        f"[green]{stats_result.relationships_created} relationships created[/green], "
        f"[red]{stats_result.batches_failed} batch(es) failed[/red]."
    )
    if stats_result.batches_split:
        console.print(
            f"[dim]{stats_result.batches_split} batch(es) returned unusable output and were "
            "retried at half the size.[/dim]"
        )
    if stats_result.batches_failed:
        console.print(
            "[yellow]Those chunks keep no extraction stamp, so a later run picks them up "
            "again. Each one was already retried down to a single chunk, so an identical "
            "rerun fails the same way: the model could not produce usable output for that "
            "chunk. The log names each failed batch and the size that was attempted.[/yellow]"
        )
    return stats_result


@graph_app.command("extract")
def graph_extract(
    batch_size: int = typer.Option(10, help="Chunks per extraction call."),
    reprocess_all: bool = typer.Option(
        False, "--all", help="Re-read every chunk, including previously processed chunks."
    ),
    max_chunks: int | None = typer.Option(None, help="Stop after this many chunks (for trials)."),
) -> None:
    """Extract concepts and relationships from ingested chunks. Needs LLM provider credentials.

    Only chunks the extractor has not seen are processed, so re-running after
    a new ingest picks up just the new documents.
    """
    stats_result = _run_graph_extract(
        batch_size=batch_size, reprocess_all=reprocess_all, max_chunks=max_chunks
    )
    if stats_result.batches_failed:
        raise typer.Exit(1)


def _run_graph_communities(*, min_size: int):  # type: ignore[no-untyped-def]
    """Rebuild communities and print the result; shared by `graph communities` and `build`."""
    from sci_rag.config import get_settings
    from sci_rag.db import get_session_factory
    from sci_rag.domain import load_domain
    from sci_rag.embed import get_embedder
    from sci_rag.graph import build_communities
    from sci_rag.llm import get_llm

    settings = get_settings()

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await build_communities(
            session_factory=get_session_factory(),
            llm=get_llm(settings),
            embedder=get_embedder(settings),
            domain=load_domain(settings.domain_dir),
            min_size=min_size,
        )

    stats_result = run_async(run())
    console.print(
        f"[green]{stats_result.communities_created} communities[/green] covering "
        f"{stats_result.entities_clustered} entities."
        + (
            f" [yellow]{stats_result.llm_summary_failures} summaries fell back to entity lists.[/yellow]"
            if stats_result.llm_summary_failures
            else ""
        )
    )
    return stats_result


@graph_app.command("communities")
def graph_communities(
    min_size: int = typer.Option(3, help="Smallest cluster worth summarizing."),
) -> None:
    """Group related entities into clusters and write a summary of each (rebuilds all).

    Summaries answer big-picture questions no single passage covers. Needs a
    LLM provider credentials.
    """
    _run_graph_communities(min_size=min_size)


@graph_app.command("citations")
def graph_citations(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--apply",
        help="Preview by default; --apply reconciles cached Crossref references.",
    ),
) -> None:
    """Link corpus documents that cite each other, from the reference lists `corpus enrich` fetched."""
    from sci_rag.citations import build_citation_edges
    from sci_rag.db import get_session_factory

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await build_citation_edges(get_session_factory(), dry_run=dry_run)

    result = run_async(run())
    table = Table(title="Citation graph" + (" (dry run)" if dry_run else ""))
    table.add_column("What")
    table.add_column("Count", justify="right")
    table.add_row("documents with cached references", str(result.documents_scanned))
    table.add_row("unique DOI references", str(result.references_found))
    table.add_row("resolved in corpus", str(result.matched))
    table.add_row("unresolved DOI pointers", str(result.unmatched))
    table.add_row("self-citations skipped", str(result.self_citations_skipped))
    table.add_row("rows written or updated", str(result.rows_written))
    table.add_row("stale rows removed", str(result.rows_removed))
    console.print(table)
    if dry_run:
        console.print("Dry run: nothing changed. Re-run with [bold]--apply[/bold].")


@graph_app.command("resolve-entities")
def graph_resolve_entities(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--apply",
        help="Preview merges by default; --apply merges duplicates and records each merge in an audit table.",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip borderline pairs. Nothing is sent to a model.",
    ),
    threshold: float = typer.Option(
        0.92,
        "--threshold",
        min=0.0,
        max=1.0,
        help="Minimum same-type similarity for an automatic fuzzy merge.",
    ),
    llm_threshold: float = typer.Option(
        0.80,
        "--llm-threshold",
        min=0.0,
        max=1.0,
        help="Minimum similarity for a borderline pair to be reviewed by the LLM.",
    ),
) -> None:
    """Resolve duplicate graph entities conservatively and audit every merge."""
    from sci_rag.config import get_settings
    from sci_rag.db import get_session_factory
    from sci_rag.graph import resolve_entities
    from sci_rag.llm import get_llm

    if llm_threshold > threshold:
        raise typer.BadParameter("--llm-threshold cannot exceed --threshold")
    settings = get_settings()
    llm = None
    if not no_llm and settings.credentials_mode() != "none":
        llm = get_llm(settings)
    try:
        result = run_async(
            resolve_entities(
                get_session_factory(),
                llm=llm,
                dry_run=dry_run,
                no_llm=no_llm,
                fuzzy_threshold=threshold,
                ambiguous_threshold=llm_threshold,
            )
        )
    except ValueError as exc:
        if "llm is required" not in str(exc):
            raise
        console.print(
            "[red]Borderline entity pairs need configured LLM provider credentials.[/red] "
            "Configure Google credentials or rerun with [bold]--no-llm[/bold] "
            "to leave those pairs separate."
        )
        raise typer.Exit(1) from None
    table = Table(title="Entity resolution" + (" (dry run)" if dry_run else ""))
    table.add_column("What")
    table.add_column("Count", justify="right")
    table.add_row("active entities", str(result.entities_considered))
    table.add_row("automatic pairs", str(result.automatic_pairs))
    table.add_row("borderline pairs", str(result.ambiguous_pairs))
    table.add_row("LLM failures", str(result.llm_failures))
    table.add_row("planned merges", str(result.planned_merges))
    table.add_row("entities merged", str(result.merged))
    console.print(table)
    if dry_run and result.planned_merges:
        console.print("Dry run: no rows changed. Re-run with [bold]--apply[/bold] to merge.")
    elif result.merged:
        console.print(
            "[yellow]Stored community summaries were invalidated; rebuild them with "
            "[bold]sci-rag graph communities[/bold].[/yellow]"
        )
    if result.llm_failures:
        console.print("[yellow]Unclear pairs remained separate; rerun to retry them.[/yellow]")


def _load_questions(questions_path: Path | None):  # type: ignore[no-untyped-def]
    from sci_rag.config import get_settings
    from sci_rag.evals import load_seed_questions

    path = questions_path or (get_settings().domain_dir / "eval_seed_questions.jsonl")
    questions = load_seed_questions(path)
    if not questions:
        console.print(f"[red]No questions found in {path}.[/red]")
        raise typer.Exit(1)
    return questions


def _print_retrieval_results(results) -> None:  # type: ignore[no-untyped-def]
    table = Table(title="Retrieval metrics")
    table.add_column("Config")
    table.add_column("hit@5", justify="right")
    table.add_column("hit@10", justify="right")
    table.add_column("MRR", justify="right")
    table.add_column("n", justify="right")
    for result in results:
        m = result.metrics
        table.add_row(
            result.config.name,
            f"{m['hit_at_5']:.2f}",
            f"{m['hit_at_10']:.2f}",
            f"{m['mrr']:.2f}",
            str(int(m["n"])),
        )
    console.print(table)


@eval_app.command("retrieval")
def eval_retrieval(
    questions_path: Path | None = typer.Option(None, "--questions", help="Seed questions JSONL."),
    limit: int = typer.Option(10, help="Results retrieved per question."),
    ablation: bool = typer.Option(
        False,
        "--ablation",
        help="Also score each retrieval layer switched off in turn, to see what each contributes.",
    ),
    condition: str | None = typer.Option(
        None,
        "--condition",
        help="Label an established corpus condition (currently: resolved_entities).",
    ),
    snapshot: str | None = typer.Option(
        None, "--snapshot", help="Record this corpus snapshot name in the report."
    ),
) -> None:
    """Score retrieval against your seed questions: did the right documents come back?"""
    if condition not in (None, "resolved_entities"):
        raise typer.BadParameter(
            "only resolved_entities is currently supported", param_hint="--condition"
        )
    if condition is not None and ablation:
        raise typer.BadParameter("--condition and --ablation are mutually exclusive")
    if condition is not None and not snapshot:
        raise typer.BadParameter("--condition requires --snapshot")

    from sqlalchemy import func, select

    from sci_rag.config import get_settings
    from sci_rag.db import EntityResolutionAudit, get_session_factory
    from sci_rag.evals import (
        DEFAULT_ABLATIONS,
        RESOLVED_ENTITIES_CONFIG,
        run_retrieval_eval,
    )
    from sci_rag.evals.report import (
        corpus_fingerprint,
        provenance_block,
        retrieval_markdown,
        retrieval_payload,
        write_report,
    )
    from sci_rag.retrieve import Retriever

    questions = _load_questions(questions_path)
    configs = (
        [RESOLVED_ENTITIES_CONFIG]
        if condition == "resolved_entities"
        else DEFAULT_ABLATIONS
        if ablation
        else DEFAULT_ABLATIONS[:1]
    )

    if condition == "resolved_entities":

        async def count_resolution_audits() -> int:
            async with get_session_factory()() as session:
                return (await session.scalar(select(func.count(EntityResolutionAudit.id)))) or 0

        if run_async(count_resolution_audits()) == 0:
            raise typer.BadParameter(
                "resolved_entities requires at least one persisted entity-resolution audit row",
                param_hint="--condition",
            )

    async def run():  # type: ignore[no-untyped-def]
        retriever = Retriever()
        results = await run_retrieval_eval(retriever, questions, configs=configs, limit=limit)
        fingerprint = await corpus_fingerprint(get_session_factory())
        return results, fingerprint

    results, fingerprint = run_async(run())
    _print_retrieval_results(results)
    json_path, md_path = write_report(
        kind="retrieval-condition"
        if condition
        else "retrieval-ablation"
        if ablation
        else "retrieval",
        payload=retrieval_payload(
            results,
            fingerprint,
            snapshot=snapshot,
            questions=questions,
            # The ablation runs graph and HyDE, which call a model, so a
            # retrieval number depends on inputs the corpus counts do not name.
            provenance=provenance_block(get_settings()),
        ),
        markdown=retrieval_markdown(results, fingerprint, questions=questions),
    )
    console.print(f"Report written to [bold]{md_path}[/bold] (and {json_path.name}).")


@eval_app.command("answers")
def eval_answers(
    questions_path: Path | None = typer.Option(None, "--questions", help="Seed questions JSONL."),
    profile: str = typer.Option("deep", help="Retrieval profile for answer generation."),
    limit: int = typer.Option(8, help="Sources per answer."),
    judge_model: str | None = typer.Option(
        None,
        help="Judge model spec, 'model' or 'provider:model'. Overrides SCI_RAG_JUDGE_MODEL.",
    ),
    snapshot: str | None = typer.Option(
        None, "--snapshot", help="Record this corpus snapshot name in the report."
    ),
    compressed: bool = typer.Option(
        False,
        "--compressed",
        help="Summarize each retrieved source before answering, as a separate condition to compare.",
    ),
) -> None:
    """Answer every seed question and grade each answer for grounding, citations, and correctness.

    Needs LLM provider credentials. The grader scores grounding without seeing the
    reference answer, then scores correctness against it in a separate pass.
    """
    from sci_rag.answer import AnswerEngine
    from sci_rag.config import get_settings
    from sci_rag.db import get_session_factory
    from sci_rag.evals import run_answer_eval
    from sci_rag.evals.report import (
        answers_markdown,
        answers_payload,
        corpus_fingerprint,
        provenance_block,
        write_report,
    )
    from sci_rag.llm import get_llm

    questions = _load_questions(questions_path)
    settings = get_settings()

    async def run():  # type: ignore[no-untyped-def]
        engine = AnswerEngine(settings=settings)
        judge = get_llm(settings, role="judge", model=judge_model)
        records = await run_answer_eval(
            engine,
            judge,
            questions,
            profile=profile,
            limit=limit,
            include_compression=compressed,
        )
        fingerprint = await corpus_fingerprint(get_session_factory())
        # Stamped into the report: grading answers with the model that wrote
        # them is a known bias, so a reader needs to see both.
        models = {
            "answer": str(settings.model_spec_for("answer")),
            "judge": judge.describe(),
        }
        return records, fingerprint, models

    records, fingerprint, models = run_async(run())
    from sci_rag.evals import summarize_answer_records

    summary = summarize_answer_records(records)
    table = Table(title="Answer evaluation (0 to 2 per dimension)")
    table.add_column("Metric")
    table.add_column("Mean", justify="right")
    for key, value in summary.items():
        table.add_row(key, f"{value:.2f}")
    console.print(table)
    json_path, md_path = write_report(
        kind="answers",
        payload=answers_payload(
            records,
            fingerprint,
            snapshot=snapshot,
            models=models,
            config={"compression": compressed},
            provenance=provenance_block(get_settings()),
        ),
        markdown=answers_markdown(
            records,
            fingerprint,
            models=models,
            config={"compression": compressed},
        ),
    )
    console.print(f"Report written to [bold]{md_path}[/bold] (and {json_path.name}).")


@eval_app.command("diff")
def eval_diff(
    report_a: Path = typer.Argument(..., help="Baseline report.json (or its run directory)."),
    report_b: Path = typer.Argument(..., help="Comparison report.json (or its run directory)."),
    config: str | None = typer.Option(
        None, "--config", help="Diff only this ablation config (default: every common config)."
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Also write the markdown diff to this path."
    ),
) -> None:
    """Compare two eval runs: per-question rank moves and paired metric deltas.

    Deltas are B minus A. Run it after any retrieval-affecting change to
    see whether the improvement is real or inside the noise.
    """
    from sci_rag.evals.diff import DiffError, diff_markdown, diff_reports, load_report

    try:
        payload_a = load_report(report_a)
        payload_b = load_report(report_b)
        diff = diff_reports(payload_a, payload_b, config=config)
    except DiffError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    markdown = diff_markdown(diff)
    console.print(markdown)
    if output is not None:
        output.write_text(markdown, encoding="utf-8")
        console.print(f"Diff written to [bold]{output}[/bold].")


@eval_app.command("html")
def eval_html(
    run: Path = typer.Argument(..., help="Run directory, or the report.json inside one."),
    output: Path | None = typer.Option(
        None, "--output", help="Where to write the page (default: report.html beside the report)."
    ),
) -> None:
    """Render an eval run as one self-contained HTML page.

    For sharing with a collaborator who will never open a terminal. Inline
    styles, nothing fetched when the page is opened, and the small-sample
    and drafted-ground-truth warnings travel with the numbers. Picks up
    `calibration.json` automatically when it sits beside the report.
    """
    from sci_rag.evals.diff import DiffError, load_report
    from sci_rag.evals.html import render_html

    try:
        payload = load_report(run)
    except DiffError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    run_dir = run if run.is_dir() else run.parent
    calibration_path = run_dir / "calibration.json"
    calibration = None
    if calibration_path.exists():
        try:
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            console.print(f"[red]{calibration_path} is not valid JSON: {exc}[/red]")
            raise typer.Exit(1) from exc

    destination = output or run_dir / "report.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_html(payload, calibration=calibration), encoding="utf-8")
    console.print(f"Wrote [bold]{destination}[/bold].")


@eval_app.command("calibrate")
def eval_calibrate(
    labels: Path = typer.Option(..., "--labels", help="Human labels (labels.jsonl)."),
    report: Path | None = typer.Option(
        None,
        "--report",
        help="Answers report.json (or its run directory) to calibrate against. "
        "Defaults to the newest answers run under eval_results/.",
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Also write the calibration markdown to this path."
    ),
) -> None:
    """Compare a person's scores with the grader's, per dimension (reported as Cohen's kappa).

    Appends a calibration section to the report's markdown (report.md) and
    writes calibration.json next to it, so the kappa travels with the eval
    numbers it qualifies.
    """
    from sci_rag.evals.calibration import (
        CalibrationError,
        calibrate,
        calibration_markdown,
        judge_scores_from_report,
        parse_labels,
    )
    from sci_rag.evals.diff import DiffError, load_report

    try:
        if report is None:
            candidates = sorted(Path("eval_results").glob("*-answers/report.json"))
            if not candidates:
                raise CalibrationError(
                    "no --report given and no answers run found under eval_results/"
                )
            report = candidates[-1]
            console.print(f"Using newest answers report: [bold]{report}[/bold]")
        payload = load_report(report)
        result = calibrate(parse_labels(labels), judge_scores_from_report(payload))
    except (CalibrationError, DiffError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    markdown = calibration_markdown(result)
    console.print(markdown)
    report_path = report / "report.json" if report.is_dir() else report
    calibration_json = report_path.parent / "calibration.json"
    calibration_json.write_text(json.dumps(result.as_dict(), indent=2), encoding="utf-8")
    report_md = report_path.parent / "report.md"
    if report_md.exists():
        report_md.write_text(
            report_md.read_text(encoding="utf-8").rstrip() + "\n\n" + markdown + "\n",
            encoding="utf-8",
        )
        console.print(f"Calibration appended to [bold]{report_md}[/bold].")
    console.print(f"Calibration data written to [bold]{calibration_json}[/bold].")
    if output is not None:
        output.write_text(markdown, encoding="utf-8")


@embed_app.command("reindex")
def embed_reindex(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--apply",
        help="--dry-run (default) reports what is stale; --apply re-embeds it.",
    ),
    batch_size: int = typer.Option(32, help="Rows re-embedded per batch (one commit per batch)."),
) -> None:
    """Re-embed chunks and community summaries that an older embedding model produced.

    A dimension change is refused outright: that is a schema migration
    plus a full re-ingest, never a reindex.
    """
    from sci_rag.config import get_settings
    from sci_rag.db import get_session_factory
    from sci_rag.embed import get_embedder
    from sci_rag.embed.planner import ReindexRefused, apply_reindex, plan_reindex

    embedder = get_embedder(get_settings())

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        factory = get_session_factory()
        plan = await plan_reindex(factory, embedder)
        outcome = None
        if not dry_run and not plan.clean:
            outcome = await apply_reindex(
                factory, embedder, batch_size=batch_size, progress=console.print
            )
        return plan, outcome

    try:
        plan, outcome = run_async(run())
    except ReindexRefused as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    table = Table(title=f"Re-embed plan (current embedder: {plan.embedder_version})")
    table.add_column("What")
    table.add_column("Count", justify="right")
    table.add_row("chunks total", str(plan.total_chunks))
    table.add_row("chunks stale", str(plan.stale_chunks))
    for version, count in sorted(plan.chunk_versions.items(), key=lambda kv: str(kv[0])):
        table.add_row(f"  from {version or 'unstamped'}", str(count))
    table.add_row("community summaries stale", str(plan.stale_communities))
    console.print(table)

    if plan.clean:
        console.print("[green]Everything is already on the current embedding version.[/green]")
    elif dry_run:
        console.print("Dry run: nothing written. Re-run with [bold]--apply[/bold] to re-embed.")
    elif outcome is not None:
        console.print(
            f"[green]Re-embedded {outcome.chunks_reembedded} chunk(s) and "
            f"{outcome.communities_reembedded} community summar(ies) "
            f"in {outcome.batches} batch(es).[/green]"
        )


@campaign_app.command("discover")
def campaign_discover(
    topic: str | None = typer.Option(
        None,
        "--topic",
        help="Search topic for OpenAlex discovery.",
    ),
    doi_file: Path | None = typer.Option(
        None,
        "--doi-file",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Text file with one DOI or DOI URL per line.",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Campaign directory name (derived from the input when omitted).",
    ),
    mailto: str = typer.Option(
        ...,
        "--mailto",
        envvar="SCI_RAG_CAMPAIGN_MAILTO",
        help="Contact email sent to OpenAlex and Crossref.",
    ),
    max_results: int = typer.Option(
        100,
        "--max-results",
        min=1,
        help="Maximum total candidates for a topic campaign.",
    ),
    campaign_root: Path = typer.Option(
        Path("data/campaigns"),
        "--campaign-root",
        file_okay=False,
        help="Parent directory for campaign state.",
    ),
) -> None:
    """Discover a deduplicated DOI list and save resumable state."""
    if (topic is None) == (doi_file is None):
        raise typer.BadParameter("Provide exactly one of --topic or --doi-file.")

    derived_name = name or topic or (doi_file.stem if doi_file is not None else "")
    campaign_dir = campaign_root / _campaign_slug(derived_name)

    from sci_rag.campaigns.discovery import discover_by_dois, discover_by_topic
    from sci_rag.campaigns.http import PoliteHttpClient
    from sci_rag.campaigns.state import CampaignState

    state = CampaignState(campaign_dir / "state.jsonl")

    async def run():  # type: ignore[no-untyped-def]
        async with PoliteHttpClient(mailto=mailto) as client:
            if topic is not None:
                return await discover_by_topic(
                    client,
                    topic,
                    max_results=max_results,
                    state=state,
                    api_key=os.environ.get("OPENALEX_API_KEY") or None,
                )
            assert doi_file is not None
            return await discover_by_dois(client, doi_file, state=state)

    report = run_async(run())
    table = Table(title=f"Campaign discovery: {campaign_dir.name}")
    table.add_column("DOI")
    table.add_column("Year", justify="right")
    table.add_column("Title")
    table.add_column("Source")
    for work in report.works:
        table.add_row(work.doi, str(work.year or ""), work.title or "", work.source)
    console.print(table)
    console.print(
        f"[green]{len(report.works)} discovered[/green], "
        f"[yellow]{report.duplicate_records} duplicate[/yellow], "
        f"[red]{report.malformed_records} malformed[/red], "
        f"[cyan]{report.skipped_processed} already processed[/cyan]."
    )
    console.print(f"State: [bold]{state.path}[/bold]")


@campaign_app.command("build")
def campaign_build(
    topic: str | None = typer.Option(
        None,
        "--topic",
        help="Search topic for OpenAlex discovery.",
    ),
    doi_file: Path | None = typer.Option(
        None,
        "--doi-file",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Text file with one DOI or DOI URL per line.",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Campaign directory name (derived from the input when omitted).",
    ),
    mailto: str = typer.Option(
        ...,
        "--mailto",
        envvar="SCI_RAG_CAMPAIGN_MAILTO",
        help="Contact email sent to OpenAlex, Crossref, and Unpaywall.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve and report rights without downloading PDFs or writing a manifest.",
    ),
    max_results: int = typer.Option(
        100,
        "--max-results",
        min=1,
        help="Work on at most this many candidates, including ones already in state.",
    ),
    all_candidates: bool = typer.Option(
        False,
        "--all-candidates",
        help="Ignore --max-results and process every candidate the campaign retains.",
    ),
    max_pdf_mb: int = typer.Option(
        25,
        "--max-pdf-mb",
        min=1,
        help="Reject a PDF larger than this many MiB.",
    ),
    campaign_root: Path = typer.Option(
        Path("data/campaigns"),
        "--campaign-root",
        file_okay=False,
        help="Parent directory for campaign state, PDFs, and manifest.",
    ),
) -> None:
    """Check each candidate's rights, download the open-access PDFs, and write a manifest to ingest."""
    if (topic is None) == (doi_file is None):
        raise typer.BadParameter("Provide exactly one of --topic or --doi-file.")

    derived_name = name or topic or (doi_file.stem if doi_file is not None else "")
    campaign_dir = campaign_root / _campaign_slug(derived_name)

    from sci_rag.campaigns.build import build_campaign, load_discovered_candidates
    from sci_rag.campaigns.discovery import discover_by_dois, discover_by_topic
    from sci_rag.campaigns.http import PoliteHttpClient
    from sci_rag.campaigns.state import CampaignState

    state = CampaignState(campaign_dir / "state.jsonl")

    async def run():  # type: ignore[no-untyped-def]
        async with PoliteHttpClient(mailto=mailto) as client:
            if topic is not None:
                discovery = await discover_by_topic(
                    client,
                    topic,
                    max_results=max_results,
                    state=state,
                    api_key=os.environ.get("OPENALEX_API_KEY") or None,
                )
            else:
                assert doi_file is not None
                discovery = await discover_by_dois(client, doi_file, state=state)
            report = await build_campaign(
                load_discovered_candidates(state),
                campaign_dir=campaign_dir,
                state=state,
                client=client,
                dry_run=dry_run,
                max_pdf_bytes=max_pdf_mb * 1024 * 1024,
                unpaywall_base_url=os.environ.get("SCI_RAG_UNPAYWALL_BASE_URL")
                or "https://api.unpaywall.org/v2",
                # The bound applies to the candidates in state, not only to
                # the ones discovered this run. A resumed campaign has all of
                # them, and a trial has to stay a trial.
                max_results=None if all_candidates else max_results,
            )
            return discovery, report

    discovery, report = run_async(run())
    title = f"Dry run: {campaign_dir.name}" if dry_run else f"Campaign build: {campaign_dir.name}"
    table = Table(title=title)
    table.add_column("Measure")
    table.add_column("Count", justify="right")
    for label, count in (
        ("retained", report.retained),
        ("candidates", report.candidates),
        ("resolved", report.resolved),
        ("direct PDFs", report.direct_pdfs),
        ("downloaded", report.downloaded),
        ("resumed", report.resumed),
        ("unavailable", report.unavailable),
        ("rejected", report.rejected),
        ("failed", report.failed),
    ):
        table.add_row(label, str(count))
    console.print(table)
    if report.retained > report.candidates:
        console.print(
            f"Bounded to {report.candidates} of {report.retained} retained candidate(s) "
            "by --max-results. Pass --all-candidates to process every one."
        )
    console.print(
        f"{report.resolved} resolved, {report.direct_pdfs} direct PDF(s), "
        f"{report.downloaded} downloaded, {report.resumed} resumed, "
        f"{report.unavailable} unavailable, {report.rejected} rejected, "
        f"{report.failed} failed."
    )
    console.print(
        "Licenses: "
        + (
            ", ".join(
                f"{license_class}={count}"
                for license_class, count in sorted(report.license_counts.items())
            )
            or "none"
        )
    )
    console.print(
        f"Discovery this run: {len(discovery.works)} new, "
        f"{discovery.duplicate_records} duplicate, "
        f"{discovery.malformed_records} malformed, "
        f"{discovery.skipped_processed} already processed."
    )
    if report.manifest_path is not None:
        console.print(f"Manifest: [bold]{report.manifest_path}[/bold]")
    console.print(f"State: [bold]{state.path}[/bold]")
    if report.failed:
        raise typer.Exit(1)


@campaign_app.command("screen")
def campaign_screen(
    name: str = typer.Option(..., "--name", help="Campaign directory name to screen."),
    criteria_file: Path = typer.Option(
        ...,
        "--criteria-file",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Plain-text inclusion and exclusion criteria.",
    ),
    confidence_threshold: float = typer.Option(
        0.8,
        "--confidence-threshold",
        min=0.0,
        max=1.0,
        help="Model confidence below this value requires human review.",
    ),
    batch_size: int = typer.Option(
        20,
        "--batch-size",
        min=1,
        help="Maximum abstracts in one model request.",
    ),
    campaign_root: Path = typer.Option(
        Path("data/campaigns"),
        "--campaign-root",
        file_okay=False,
        help="Parent directory containing campaign state.",
    ),
) -> None:
    """Screen discovered abstracts and queue uncertain rows for human review."""
    from sci_rag.campaigns.build import load_discovered_candidates
    from sci_rag.campaigns.screen import screen_campaign
    from sci_rag.campaigns.state import CampaignState
    from sci_rag.config import get_settings
    from sci_rag.domain import load_domain
    from sci_rag.llm import get_llm

    campaign_dir = campaign_root / _campaign_slug(name)
    state = CampaignState(campaign_dir / "state.jsonl")
    works = load_discovered_candidates(state)
    if not works:
        raise typer.BadParameter(
            f"Campaign {campaign_dir.name!r} has no discovered works. Run campaign discover first."
        )
    criteria = criteria_file.read_text(encoding="utf-8").strip()
    if not criteria:
        raise typer.BadParameter("The criteria file must not be empty.")
    settings = get_settings()
    report_path = campaign_dir / "screening-report.json"
    report = run_async(
        screen_campaign(
            works,
            criteria=criteria,
            llm=get_llm(settings),
            domain=load_domain(settings.domain_dir),
            state=state,
            confidence_threshold=confidence_threshold,
            batch_size=batch_size,
            report_path=report_path,
        )
    )
    _print_screening_report(report)
    console.print(f"Report: [bold]{report_path}[/bold]")
    console.print(f"State: [bold]{state.path}[/bold]")


@campaign_app.command("review")
def campaign_review(
    name: str = typer.Option(..., "--name", help="Campaign directory name to review."),
    campaign_root: Path = typer.Option(
        Path("data/campaigns"),
        "--campaign-root",
        file_okay=False,
        help="Parent directory containing campaign state.",
    ),
) -> None:
    """Walk pending screening rows and append explicit human decisions."""
    from sci_rag.campaigns.build import load_discovered_candidates
    from sci_rag.campaigns.screen import (
        apply_human_review,
        load_screening_context,
        screening_report_from_state,
        write_screening_report,
    )
    from sci_rag.campaigns.state import CampaignState

    campaign_dir = campaign_root / _campaign_slug(name)
    state = CampaignState(campaign_dir / "state.jsonl")
    works = load_discovered_candidates(state)
    report_path = campaign_dir / "screening-report.json"
    if not works:
        raise typer.BadParameter(
            f"Campaign {campaign_dir.name!r} has no discovered works. Run campaign discover first."
        )
    if not report_path.exists():
        raise typer.BadParameter(
            f"Campaign {campaign_dir.name!r} has no screening report. Run campaign screen first."
        )
    try:
        context = load_screening_context(report_path)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        before_review = screening_report_from_state(
            works,
            criteria=context.criteria,
            state=state,
            confidence_threshold=context.confidence_threshold,
            duplicates_removed=context.duplicates_removed,
            malformed_responses=context.malformed_responses,
            missing_abstracts=context.missing_abstracts,
        )
    except ValueError as exc:
        raise typer.BadParameter(f"{exc}. Run campaign screen again before review.") from exc
    queue = before_review.review_queue
    works_by_doi = {work.doi: work for work in works}
    if not queue:
        console.print("[green]No screening rows are awaiting review.[/green]")
    for item in queue:
        abstract = works_by_doi[item.doi].abstract or "Abstract unavailable."
        console.print(
            f"\n[bold]{item.title}[/bold]\nDOI: {item.doi}\n"
            f"Abstract: {abstract}\nCurrent reason: {item.reason}"
        )
        while True:
            choice = typer.prompt("Decision (include/exclude/skip)").strip().casefold()
            if choice in {"include", "exclude", "skip"}:
                break
            console.print("Choose include, exclude, or skip.")
        if choice == "skip":
            continue
        reason = typer.prompt("Reason", default=item.reason).strip()
        apply_human_review(
            state,
            doi=item.doi,
            criteria_sha256=context.criteria_sha256,
            confidence_threshold=context.confidence_threshold,
            decision=choice,
            reason=reason,
        )

    report = screening_report_from_state(
        works,
        criteria=context.criteria,
        state=state,
        confidence_threshold=context.confidence_threshold,
        duplicates_removed=context.duplicates_removed,
        malformed_responses=context.malformed_responses,
        missing_abstracts=context.missing_abstracts,
    )
    write_screening_report(report, report_path)
    _print_screening_report(report)
    console.print(f"Report: [bold]{report_path}[/bold]")


@corpus_app.command("enrich")
def corpus_enrich(
    mailto: str = typer.Option(
        ...,
        "--mailto",
        envvar="SCI_RAG_CAMPAIGN_MAILTO",
        help="Contact email sent with each Crossref request; identified callers get faster service.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List eligible DOI records without network calls or writes."
    ),
    limit: int | None = typer.Option(
        None, "--limit", min=1, help="Process at most this many documents."
    ),
) -> None:
    """Add Crossref citation, journal, and retraction metadata to the corpus."""
    from sci_rag.campaigns.http import PoliteHttpClient
    from sci_rag.db import get_session_factory
    from sci_rag.enrich import enrich_documents

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        async with PoliteHttpClient(mailto=mailto) as client:
            return await enrich_documents(
                get_session_factory(), client, dry_run=dry_run, limit=limit
            )

    report = run_async(run())
    table = Table(title="Crossref enrichment plan" if dry_run else "Crossref enrichment report")
    table.add_column("DOI")
    table.add_column("Status")
    table.add_column("Detail")
    for outcome in report.outcomes:
        table.add_row(outcome.doi, outcome.status, outcome.detail)
    console.print(table)
    console.print(
        f"[green]{report.enriched} enriched[/green], "
        f"[cyan]{report.planned} planned[/cyan], "
        f"[yellow]{report.skipped} skipped recent[/yellow], "
        f"[red]{report.failed} failed[/red]."
    )
    if report.failed:
        raise typer.Exit(1)


@corpus_app.command("delete")
def corpus_delete(
    document_ids: list[str] = typer.Argument(..., help="Document id(s) to delete."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Delete documents, their chunks, and every graph entry that relied on them.

    Communities built from that evidence are dropped too; rebuild them with
    `sci-rag graph communities`. Run `sci-rag graph gc` afterwards to remove
    entities left with no evidence at all.
    """
    from sci_rag.corpus import delete_documents
    from sci_rag.db import get_session_factory

    if not yes:
        typer.confirm(
            f"Delete {len(document_ids)} document(s) and scrub their graph evidence?",
            abort=True,
        )

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await delete_documents(get_session_factory(), document_ids)

    outcome = run_async(run())
    if outcome.documents_deleted == 0:
        console.print("[yellow]No matching documents found; nothing deleted.[/yellow]")
        raise typer.Exit(1)
    console.print(
        f"[green]Deleted {outcome.documents_deleted} document(s)[/green]: "
        f"{outcome.chunks_deleted} chunk(s) cascaded, "
        f"{outcome.citations_deleted} citation pointer(s) removed, "
        f"{outcome.entities_scrubbed} entit(ies) scrubbed, "
        f"{outcome.relationships_deleted} relationship(s) removed, "
        f"{outcome.communities_deleted} communit(ies) dropped."
    )
    if outcome.communities_deleted:
        console.print(
            "Rebuild community coverage with [bold]sci-rag graph communities[/bold]; "
            "sweep evidence-less entities with [bold]sci-rag graph gc --apply[/bold]."
        )


@corpus_app.command("snapshot")
def corpus_snapshot(
    name: str | None = typer.Argument(None, help="Snapshot name (default: UTC timestamp)."),
) -> None:
    """Record exactly which documents the corpus holds right now, under data/snapshots/.

    Records counts, per-document content hashes, embedding versions, the
    git commit, and a single corpus digest. Reference it from eval runs
    with --snapshot NAME so reported numbers stay tied to exactly the
    corpus that produced them.
    """
    from sci_rag.db import get_session_factory
    from sci_rag.snapshot import write_snapshot

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await write_snapshot(get_session_factory(), name=name)

    try:
        info = run_async(run())
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Snapshot [bold]{info.name}[/bold] written to {info.path}.[/green]")


#: The undeclared list can be the whole corpus. The table shows a readable
#: slice and says how many it left out; `--json` never elides.
_UNDECLARED_TABLE_LIMIT = 20


@corpus_app.command("license-report")
def corpus_license_report(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit 1 when any document is still 'unknown'. For CI; the report itself never fails.",
    ),
) -> None:
    """Count documents and chunks by license class, and name the ones still `unknown`.

    License classes decide what a scoped request may see, so this is the
    report to read before you share the service.
    """
    import json as _json

    from sci_rag.db import get_session_factory
    from sci_rag.license_report import build_license_report, report_payload
    from sci_rag.licensing import EXTERNAL_SAFE_CLASSES

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await build_license_report(get_session_factory())

    report = run_async(run())

    if as_json:
        print(_json.dumps(report_payload(report), indent=2))
        raise typer.Exit(1 if strict and not report.clean else 0)

    table = Table(title="License posture")
    table.add_column("Class")
    table.add_column("Documents", justify="right")
    table.add_column("%", justify="right")
    table.add_column("Chunks", justify="right")
    table.add_column("%", justify="right")
    table.add_column("External-safe")
    for row in report.by_class:
        colour = "yellow" if row.license_class == "unknown" and row.documents else None
        name = f"[{colour}]{row.license_class}[/{colour}]" if colour else row.license_class
        table.add_row(
            name,
            str(row.documents),
            f"{row.document_share:.1f}",
            str(row.chunks),
            f"{row.chunk_share:.1f}",
            "yes" if row.external_safe else "no",
        )
    console.print(table)

    console.print(
        f"{report.total_documents} document(s), {report.total_chunks} chunk(s). "
        f"[green]{report.external_safe_documents} ({report.external_safe_share:.1f}%)[/green] "
        f"are safe to expose on a service you do not fully control "
        f"({', '.join(EXTERNAL_SAFE_CLASSES)})."
    )

    if report.undeclared:
        shown = report.undeclared[:_UNDECLARED_TABLE_LIMIT]
        undeclared = Table(title="Undeclared rights (license_class: unknown)")
        undeclared.add_column("Source")
        undeclared.add_column("Title")
        for document in shown:
            undeclared.add_row(document.source, document.title)
        console.print(undeclared)
        if len(report.undeclared) > len(shown):
            console.print(
                f"[yellow]... and {len(report.undeclared) - len(shown)} more. "
                "Use --json for the full list.[/yellow]"
            )
        by_source = ", ".join(
            f"{source} ({count})" for source, count in sorted(report.undeclared_by_source.items())
        )
        console.print(f"Undeclared documents come from: {by_source}.")
        console.print(
            "[yellow]`unknown` is excluded, never assumed safe.[/yellow] Whenever a caller "
            "restricts the license scope, these documents are excluded unless the scope "
            "names `unknown` explicitly, so they are invisible to scoped retrieval and to "
            "a scoped export. Record their rights in the corpus manifest and re-ingest, "
            "or leave them out on purpose."
        )
    else:
        console.print("[green]Every document has a recorded license class.[/green]")

    # A report is not a gate. `--strict` is the opt-in that makes it one.
    if strict and not report.clean:
        raise typer.Exit(1)


@corpus_app.command("export")
def corpus_export(
    outdir: Path = typer.Argument(..., help="Directory to write the export files into."),
    fmt: str = typer.Option(
        "jsonl", "--format", help="jsonl (no extra dependency) or parquet (needs --extra export)."
    ),
    license_classes: list[str] = typer.Option(
        [],
        "--license",
        help="Export only these license classes (repeatable). Omit for everything. "
        "An export is a redistribution, so a scope excludes 'unknown' unless you name it.",
    ),
    include_embeddings: bool = typer.Option(
        False, "--include-embeddings", help="Include chunk vectors (large, rarely wanted)."
    ),
) -> None:
    """Export documents, chunks, entities, and relationships to files.

    A scope leaves out anything it cannot vouch for, and applies to the graph too: an entity is
    exported only when every document it was extracted from is in scope,
    because its description is written from all of them. Communities are
    never exported; they aggregate with no per-document attribution to check.
    """
    from sci_rag.db import get_session_factory
    from sci_rag.export import FORMATS, ParquetUnavailableError, export_corpus
    from sci_rag.retrieve.types import RetrievalScope

    if fmt not in FORMATS:
        console.print(f"[red]Unknown format {fmt!r}.[/red] Known: {', '.join(FORMATS)}")
        raise typer.Exit(1)

    scope = RetrievalScope(license_classes=tuple(license_classes)) if license_classes else None

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await export_corpus(
            get_session_factory(),
            directory=outdir,
            fmt=fmt,  # type: ignore[arg-type]
            scope=scope,
            include_embeddings=include_embeddings,
        )

    try:
        result = run_async(run())
    except ParquetUnavailableError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    table = Table(title=f"Exported to {result.directory}")
    table.add_column("Table")
    table.add_column("Rows", justify="right")
    table.add_column("File")
    for name, path in zip(result.counts, result.files, strict=True):
        table.add_row(name, str(result.counts[name]), path.name)
    console.print(table)
    if result.scoped:
        console.print(
            "[yellow]Scoped export.[/yellow] Documents and chunks outside the license "
            "allowlist were excluded, along with every entity whose evidence touched one "
            "of them."
        )
    if not include_embeddings:
        console.print("Chunk embeddings were omitted; pass --include-embeddings to keep them.")


@graph_app.command("gc")
def graph_gc_command(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--apply",
        help="--dry-run (default) reports what would go; --apply removes it.",
    ),
) -> None:
    """Remove graph leftovers: entities with no evidence, relationships with a missing end,
    and communities whose members are gone."""
    from sci_rag.corpus import graph_gc
    from sci_rag.db import get_session_factory

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await graph_gc(get_session_factory(), dry_run=dry_run)

    outcome = run_async(run())
    table = Table(title="Graph GC" + (" (dry run)" if dry_run else ""))
    table.add_column("What")
    table.add_column("Count", justify="right")
    table.add_row("evidence-less entities", str(outcome.entities_deleted))
    table.add_row("dangling relationships", str(outcome.relationships_deleted))
    table.add_row("dangling citations", str(outcome.citations_deleted))
    table.add_row("communities dropped", str(outcome.communities_deleted))
    table.add_row("communities pruned", str(outcome.communities_pruned))
    console.print(table)
    if outcome.clean:
        console.print("[green]Graph is clean; nothing to collect.[/green]")
    elif dry_run:
        console.print("Dry run: nothing removed. Re-run with [bold]--apply[/bold].")
    else:
        console.print(
            "[green]Swept.[/green] Rebuild community coverage with "
            "[bold]sci-rag graph communities[/bold] if communities were dropped."
        )


@app.command(rich_help_panel=PANEL_MEASURE)
def profile(
    questions_path: Path | None = typer.Option(
        None, "--questions", help="Seed questions JSONL. Defaults to the domain's."
    ),
    runs: int = typer.Option(3, "--runs", help="Replays per question, per profile."),
    limit: int = typer.Option(8, "--limit", help="Results per request."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Time each retrieval stage (median and 95th percentile) under each profile.

    Replays the seed questions against interactive, deep, and auto, and
    aggregates the per-stage timings every request already records. Stages run
    concurrently, so their durations do not sum to the request; wall-clock is
    measured separately and reported beside them.
    """
    import json as _json

    from sci_rag.retrieve import Retriever
    from sci_rag.retrieve.profiler import profile_retrieval, report_payload, verdict

    if runs < 1:
        raise typer.BadParameter("--runs must be at least 1")

    questions = _load_questions(questions_path)

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        return await profile_retrieval(Retriever(), questions, runs=runs, limit=limit)

    report = run_async(run())

    if as_json:
        print(_json.dumps(report_payload(report), indent=2))
        return

    for timing in report.profiles:
        table = Table(
            title=(
                f"{timing.profile}: {timing.p50:.0f} ms p50, {timing.p95:.0f} ms p95 "
                f"per request ({timing.runs} runs)"
            )
        )
        table.add_column("Stage")
        table.add_column("p50 ms", justify="right")
        table.add_column("p95 ms", justify="right")
        table.add_column("Runs", justify="right")
        table.add_column("Status")
        for stage in timing.ordered_stages():
            statuses = ", ".join(
                f"{status} {count}" for status, count in sorted(stage.statuses.items())
            )
            colour = "red" if stage.degraded else None
            table.add_row(
                f"[{colour}]{stage.stage}[/{colour}]" if colour else stage.stage,
                f"{stage.p50:.0f}" if stage.samples else "-",
                f"{stage.p95:.0f}" if stage.samples else "-",
                str(stage.runs),
                statuses,
            )
        console.print(table)

    console.print(
        f"\n{report.questions} question(s) x {report.runs_per_question} run(s) per profile. "
        "Stages run concurrently, so the stage column does not sum to the request time."
    )
    console.print(
        "The query-embedding cache is off while profiling, so every run is cold and the "
        "profiles are comparable; a warm interactive path is faster than this says."
    )
    for line in verdict(report):
        console.print(
            f"  {'[yellow]' if line.startswith('Warning') else ''}{line}"
            f"{'[/yellow]' if line.startswith('Warning') else ''}"
        )


@app.command(rich_help_panel=PANEL_ASK)
def stats() -> None:
    """Show what is in the knowledge base: documents, chunks, graph size, licenses."""
    from sqlalchemy import func, select

    from sci_rag.db import (
        Chunk,
        Document,
        KgCommunity,
        KgEntity,
        KgRelationship,
        get_session_factory,
    )

    async def run():  # type: ignore[no-untyped-def]
        await _check_db()
        async with get_session_factory()() as session:
            counts = {}
            for label, model in (
                ("documents", Document),
                ("chunks", Chunk),
                ("entities", KgEntity),
                ("relationships", KgRelationship),
                ("communities", KgCommunity),
            ):
                counts[label] = await session.scalar(select(func.count(model.id)))
            by_license = (
                await session.execute(
                    select(Document.license_class, func.count(Document.id)).group_by(
                        Document.license_class
                    )
                )
            ).all()
            versions = (
                await session.execute(
                    select(Chunk.embedding_version, func.count(Chunk.id)).group_by(
                        Chunk.embedding_version
                    )
                )
            ).all()
            confidence = {
                "direct": await session.scalar(
                    select(func.count(KgRelationship.id)).where(KgRelationship.confidence >= 0.85)
                ),
                "strong": await session.scalar(
                    select(func.count(KgRelationship.id)).where(
                        KgRelationship.confidence >= 0.55,
                        KgRelationship.confidence < 0.85,
                    )
                ),
                "inferred": await session.scalar(
                    select(func.count(KgRelationship.id)).where(KgRelationship.confidence < 0.55)
                ),
            }
        return counts, by_license, versions, confidence

    counts, by_license, versions, confidence = run_async(run())
    table = Table(title="Knowledge base")
    table.add_column("Thing")
    table.add_column("Count", justify="right")
    for label, count in counts.items():
        table.add_row(label, str(count))
    console.print(table)
    if by_license:
        console.print("Licenses: " + ", ".join(f"{lc}={n}" for lc, n in by_license))
    if versions:
        console.print("Embedding versions: " + ", ".join(f"{v}={n}" for v, n in versions))
    if counts["relationships"]:
        console.print(
            "Relationship confidence: "
            + ", ".join(f"{band}={count}" for band, count in confidence.items())
        )


@app.command(rich_help_panel=PANEL_SERVE)
def serve(
    host: str | None = typer.Option(None, help="Bind address (default from settings)."),
    port: int | None = typer.Option(
        None, help="Port (default from settings; Cloud Run sets PORT)."
    ),
) -> None:
    """Start the web service: REST API under /v1 (docs at /docs) and MCP tools at /mcp."""
    import os

    import uvicorn

    from sci_rag.config import get_settings
    from sci_rag.server import create_app

    settings = get_settings()
    resolved_port = port or int(os.environ.get("PORT", settings.server_port))
    resolved_host = host or settings.server_host
    console.print(
        f"Serving on [bold]http://{resolved_host}:{resolved_port}[/bold] "
        f"(docs at /docs, MCP at /mcp)."
    )
    uvicorn.run(create_app(settings=settings), host=resolved_host, port=resolved_port)


@app.command("mcp", rich_help_panel=PANEL_SERVE)
def mcp_stdio() -> None:
    """Let a local agent such as Claude Code use the corpus as tools (MCP over stdio).

    Add it to an agent with, for example:
    claude mcp add sci-rag -- uv run --directory /path/to/your/repo sci-rag mcp
    """
    import logging
    import sys

    import structlog

    # stdout carries the MCP protocol; every log line must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
    )

    from sci_rag.server import RagService, build_mcp_server

    service = RagService()
    mcp_server, _tools = build_mcp_server(service)
    mcp_server.run()


from sci_rag.cli.doctor import doctor as _doctor  # noqa: E402 - registered after app exists
from sci_rag.cli.draft import draft_app as _draft_app  # noqa: E402 - registered after app exists
from sci_rag.cli.init import init as _init  # noqa: E402 - registered after app exists
from sci_rag.cli.new import new as _new  # noqa: E402 - registered after app exists

app.command("new", rich_help_panel=PANEL_START)(_new)
app.command("init", rich_help_panel=PANEL_START)(_init)
app.command("doctor", rich_help_panel=PANEL_START)(_doctor)
app.add_typer(_draft_app, name="draft", rich_help_panel=PANEL_BUILD)


def _panel_rank(info) -> int:  # type: ignore[no-untyped-def]
    panel = getattr(info, "rich_help_panel", None)
    return PANEL_ORDER.index(panel) if panel in PANEL_ORDER else len(PANEL_ORDER)


# `--help` lists panels in the order commands were registered. Registration
# order follows the source file, so sort once here to present the panels in
# the order a new project meets them. The sort is stable, which keeps the
# in-panel order the source chose.
app.registered_commands.sort(key=_panel_rank)
app.registered_groups.sort(key=_panel_rank)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
