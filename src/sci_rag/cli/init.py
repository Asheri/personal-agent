"""`sci-rag init`: run the setup wizard inside a checkout you already have.

This is the in-repository half of the project factory. `sci-rag-new` fetches
the template first and then runs exactly this logic; here the template is the
directory you are standing in, which is why nothing in this command touches
git history.

A dry run applies the change to a scratch copy of the checkout and reports
what came out, so the preview is produced by the same appliers as the real
run rather than by a second description of them that could drift.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import typer
from rich.console import Console

# Copies for a dry run skip anything large or regenerable. None of it is read
# by an applier, and data/raw can hold a whole corpus.
_SCRATCH_IGNORE = shutil.ignore_patterns(
    ".git",
    ".venv",
    "__pycache__",
    "*.pyc",
    "site",
    "eval_results",
    "raw",
    "interim",
    "processed",
    "snapshots",
    "node_modules",
)

console = Console()


def init(
    target: Path = typer.Option(
        Path("."), "--target", help="The checkout to configure. Defaults to the current directory."
    ),
    defaults: bool = typer.Option(
        False, "--defaults", help="Take every default without asking. Useful in CI."
    ),
    answers_file: Path | None = typer.Option(
        None,
        "--answers-file",
        help="A YAML file of answers, for reproducible generation. Unanswered questions "
        "take their default. Answers that need a person, such as accepting a drafted "
        "ontology, must be supplied explicitly.",
    ),
    quick: bool | None = typer.Option(
        None,
        "--quick/--advanced",
        help="Ask six setup questions, or expose every option.",
    ),
    no_tty: bool = typer.Option(
        False,
        "--no-tty",
        help="Use plain numbered prompts even in a supported terminal.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without writing anything."
    ),
) -> None:
    """Configure an existing Sci RAG Kit checkout in place.

    The setup wizard asks about your project, LLM provider credentials, domain,
    corpus, and stack, then updates the target checkout's configuration files.
    It writes editable configuration files.
    """
    from sci_rag.scaffold.answers import ProjectAnswers
    from sci_rag.scaffold.apply import apply_all
    from sci_rag.scaffold.prompt import PromptAborted
    from sci_rag.scaffold.report import print_scaffold_report
    from sci_rag.scaffold.wizard import (
        AnswerFileError,
        answer_file_fields,
        collect_answers,
        confirm_ontology_draft,
    )

    root = target.expanduser().resolve()
    if not (root / "pyproject.toml").exists() or not (root / "domain").is_dir():
        console.print(
            f"[red]{root} does not look like a sci-rag-kit checkout[/red] "
            "(no pyproject.toml and domain/ directory). Run this from inside the "
            "repository, or pass --target."
        )
        raise typer.Exit(1)

    preset: dict[str, str] = {}
    explicit_fields: set[str] = set()
    try:
        if answers_file is not None:
            explicit_fields.update(answer_file_fields(answers_file, preset=preset))
        raw = collect_answers(
            defaults=defaults,
            answers_file=answers_file,
            quick=quick,
            plain=no_tty,
            preset=preset,
            explicit_fields_out=explicit_fields,
        )
    except AnswerFileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    except PromptAborted as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(1) from exc

    resolved = ProjectAnswers.from_raw(raw, explicit_fields=explicit_fields)

    drafted = None
    if raw.get("ontology") == "draft_with_llm" and raw.get("credentials") != "offline":
        if defaults or answers_file is not None:
            console.print(
                "[yellow]Skipping the LLM ontology draft: accepting or redrafting one "
                "needs an interactive session. Keeping the worked example.[/yellow]"
            )
        else:
            model = resolved.llm_model
            if resolved.credentials == "deepseek":
                from sci_rag.scaffold.preflight import build_explicit_deepseek_llm

                api_key = raw.get("deepseek_api_key", "")
                llm = build_explicit_deepseek_llm(api_key=api_key, model=model) if api_key else None
            else:
                from sci_rag.scaffold.preflight import build_explicit_google_llm

                api_key = raw.get("google_api_key", "")
                gcp_project = raw.get("gcp_project", "")
                llm = (
                    build_explicit_google_llm(
                        api_key=api_key,
                        gcp_project=gcp_project,
                        model=model,
                    )
                    if api_key or gcp_project
                    else None
                )
            drafted = confirm_ontology_draft(
                root / "domain",
                project_name=raw["project_name"],
                description=raw.get("description", ""),
                llm=llm,
            )
    answers = ProjectAnswers.from_raw(
        raw,
        drafted_ontology=drafted,  # type: ignore[arg-type]
        explicit_fields=explicit_fields,
    )

    if dry_run:
        with tempfile.TemporaryDirectory() as scratch:
            preview = Path(scratch) / root.name
            shutil.copytree(root, preview, ignore=_SCRATCH_IGNORE, symlinks=True)
            changes = apply_all(answers, preview, allow_git=False)
        print_scaffold_report(answers, changes, console=console, dry_run=True)
        return

    changes = apply_all(answers, root, allow_git=False)
    print_scaffold_report(answers, changes, console=console)
