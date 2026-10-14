"""`sci-rag draft`: the assisted path to the files you would otherwise type.

Every command here offers the same three lanes, and the flags are the whole
interface to them:

* nothing extra, and the configured model drafts it (Lane A);
* ``--print-prompt``, and the rendered, corpus-grounded prompt goes to stdout
  for local use or an approved assistant, then ``--from-file reply.json``
  feeds the reply back through identical validation (Lane B);
* neither, and you write the file yourself exactly as before (Lane C).

Nothing here overwrites a file a human vouched for. A run proposes
``<file>.proposed`` and prints a summary; ``--apply`` is the separate,
deliberate step.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

draft_app = typer.Typer(
    help=(
        "Draft the domain files you would otherwise hand-write. Every drafter can also "
        "print its corpus-bearing prompt for local use or an approved assistant "
        "(--print-prompt), then read the reply back (--from-file)."
    ),
    no_args_is_help=True,
)

#: Every human-facing line these commands write is a diagnostic, and stdout
#: belongs to `--print-prompt` alone. The documented copy-paste lane is
#: `--print-prompt > prompt.txt`, so a status line on stdout would end up
#: pasted into the assistant along with the prompt.
console = Console(stderr=True)


def _fail(message: str) -> None:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(1)


def _gather_passages(folder: Path | None, *, count: int):  # type: ignore[no-untyped-def]
    """Passages from the ingested corpus, or from files when nothing is ingested.

    The fallback is what makes the drafters usable before ``make setup``: a
    new user has documents in a folder long before they have a database, and
    a command that refuses to run until then is a command they never reach.
    Which source ran is printed and recorded, because it changes what the
    draft could possibly have seen.
    """
    import asyncio

    from sci_rag.config import get_settings
    from sci_rag.draft import DraftError
    from sci_rag.draft.sampling import sample_corpus, sample_files

    # Enough passages to spread across a corpus without burying the
    # instructions, scaled to how many questions were asked for.
    limit = max(8, min(40, count * 3))

    if folder is not None:
        try:
            return sample_files(folder, limit=limit, per_document=3)
        except DraftError as exc:
            _fail(str(exc))

    async def from_corpus():  # type: ignore[no-untyped-def]
        from sci_rag.db import dispose_engine, get_session_factory

        try:
            return await sample_corpus(get_session_factory(), limit=limit, per_document=3)
        finally:
            # Disposed inside the loop that opened them: a pooled asyncpg
            # connection outliving asyncio.run() belongs to a loop that is gone.
            await dispose_engine()

    try:
        return asyncio.run(from_corpus())
    except Exception as corpus_exc:
        raw = get_settings().data_dir / "raw"
        try:
            displayed_raw = raw.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            displayed_raw = raw.resolve().as_posix()
        console.print(
            f"[yellow]No usable ingested corpus ({type(corpus_exc).__name__}), so "
            f"drafting from {displayed_raw} instead.[/yellow]"
        )
        try:
            return sample_files(raw, limit=limit, per_document=3)
        except DraftError as file_exc:
            _fail(
                f"{file_exc}\nThe ingested corpus could not be read either: "
                f"{type(corpus_exc).__name__}: {corpus_exc}"
            )


@draft_app.command("questions")
def draft_questions_command(
    count: int = typer.Option(10, "--count", help="How many questions to ask for."),
    folder: Path | None = typer.Option(
        None,
        "--folder",
        help="Draft from documents in this folder, before anything is ingested.",
    ),
    print_prompt: bool = typer.Option(
        False,
        "--print-prompt",
        help=(
            "Print the rendered prompt and exit. It may contain corpus text; "
            "send it only to an approved destination."
        ),
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Read the model's reply from this file, with no model call.",
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Where to write the proposal. Defaults to <seed file>.proposed."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Append the verified questions to the seed file."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be drafted without writing anything."
    ),
    repair: bool = typer.Option(
        True,
        "--repair/--no-repair",
        help="Ask the model once more to replace rows that failed grounding verification.",
    ),
) -> None:
    """Draft seed questions grounded in your own documents, and verify them."""
    from sci_rag.cli.main import run_async
    from sci_rag.config import get_settings
    from sci_rag.domain import load_domain
    from sci_rag.draft import DraftError, proposed_path, read_reply
    from sci_rag.draft.questions import (
        DRAFTED_HEADER,
        draft_questions,
        render_jsonl,
        render_prompt,
    )

    if apply and dry_run:
        raise typer.BadParameter("--apply and --dry-run ask for opposite things")
    if count < 1:
        raise typer.BadParameter("--count must be at least 1")

    settings = get_settings()
    try:
        domain = load_domain(settings.domain_dir)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
        return

    sample = _gather_passages(folder, count=count)

    if print_prompt:
        # Deliberately bare on stdout: this output is meant to be piped to a
        # file or a clipboard, so Rich markup and panels would be damage.
        print(render_prompt(domain, sample=sample, count=count))
        return

    try:
        result = run_async(
            draft_questions(
                domain,
                sample=sample,
                count=count,
                raw_reply=read_reply(from_file) if from_file is not None else None,
                repair=repair and from_file is None,
            )
        )
    except DraftError as exc:
        _fail(str(exc))
        return

    console.print(f"Grounded in {sample.describe()}.")
    for question in result.questions:
        console.print(f"  [green]kept[/green]    {question.id}: {question.question}")
    for question_id, reason in result.dropped:
        console.print(f"  [red]dropped[/red] {question_id}: {reason}")
    for note in result.notes:
        console.print(f"  [yellow]note[/yellow]    {note}")

    if not result.questions:
        _fail("Nothing survived verification, so there is nothing to write.")
        return

    console.print(
        f"\n{len(result.questions)} verified, {len(result.dropped)} dropped. "
        "These are model-drafted and awaiting your review."
    )

    if dry_run:
        console.print("[yellow]Dry run. Nothing was written.[/yellow]")
        return

    seed_file = domain.seed_questions_path()
    if apply:
        _append_to_seed_file(seed_file, result.questions, header=DRAFTED_HEADER)
        console.print(f"Appended to [bold]{seed_file}[/bold].")
        console.print(
            "Review each one, then delete its `drafted` tag. Until you do, every "
            "evaluation report will say its ground truth is unreviewed."
        )
        return

    target = output or proposed_path(seed_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_jsonl(result.questions), encoding="utf-8")
    console.print(f"Proposal written to [bold]{target}[/bold].")
    console.print(
        f"Review it, then move it over {seed_file.name} yourself, or re-run with --apply."
    )


@draft_app.command("seed-from-answers")
def seed_from_answers_command(
    questions_file: Path = typer.Argument(
        ..., help="Plain text file of questions, one per line. # comments are skipped."
    ),
    profile: str = typer.Option("deep", "--profile", help="Retrieval profile to answer with."),
    limit: int = typer.Option(8, "--limit", help="Sources per answer."),
    output: Path | None = typer.Option(
        None, "--output", help="Where to write the proposal. Defaults to <seed file>.proposed."
    ),
    apply: bool = typer.Option(False, "--apply", help="Append the proposed rows to the seed file."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be proposed without writing anything."
    ),
) -> None:
    """Draft seed rows for questions you already have, from the kit's own answers.

    `draft questions` invents the questions. This takes yours, answers each one,
    and proposes ground truth from the evidence that answer cited. Nothing is
    taken on the model's word: evidence phrases are extracted from the retrieved
    chunk text and every row is checked against the same relevance predicate the
    evaluation uses, so a row that would score zero against its own evidence is
    dropped and never proposed.
    """
    from sci_rag.answer import AnswerEngine
    from sci_rag.cli.main import run_async
    from sci_rag.config import get_settings
    from sci_rag.domain import load_domain
    from sci_rag.draft import DraftError, proposed_path
    from sci_rag.draft.from_answers import HEADER, read_questions, render_jsonl, seeds_from_answers
    from sci_rag.evals.seeds import load_seed_questions

    if apply and dry_run:
        raise typer.BadParameter("--apply and --dry-run ask for opposite things")

    settings = get_settings()
    try:
        domain = load_domain(settings.domain_dir)
        questions = read_questions(questions_file)
    except (DraftError, FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
        return

    seed_file = domain.seed_questions_path()
    taken = {q.id for q in load_seed_questions(seed_file)} if seed_file.exists() else set()

    async def run():  # type: ignore[no-untyped-def]
        from sci_rag.db import dispose_engine

        engine = AnswerEngine(settings=settings)
        try:
            return await seeds_from_answers(
                engine, questions, profile=profile, limit=limit, taken_ids=taken
            )
        finally:
            # Same rule as the passage sampler: pooled asyncpg connections are
            # disposed inside the loop that opened them.
            await dispose_engine()

    result = run_async(run())

    console.print(f"Answered {len(questions)} question(s) with the {profile} profile.")
    for question in result.questions:
        phrases = ", ".join(question.evidence_phrases) or "title match only"
        console.print(f"  [green]kept[/green]    {question.id}: {phrases}")
    for reason in result.dropped:
        console.print(f"  [red]dropped[/red] {reason}")
    for note in result.notes:
        console.print(f"  [yellow]note[/yellow]    {note}")

    if not result.questions:
        _fail("No question produced a usable row, so there is nothing to write.")
        return

    console.print(
        f"\n{len(result.questions)} proposed, {len(result.dropped)} dropped. "
        "The answers are the kit's own, so treat every reference answer as a "
        "hypothesis until you have checked it."
    )

    if dry_run:
        console.print("[yellow]Dry run. Nothing was written.[/yellow]")
        return

    if apply:
        _append_to_seed_file(seed_file, result.questions, header=HEADER)
        console.print(f"Appended to [bold]{seed_file}[/bold].")
        console.print(
            "Review each one, then delete its `drafted` tag. Until you do, every "
            "evaluation report will say its ground truth is unreviewed."
        )
        return

    target = output or proposed_path(seed_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_jsonl(result.questions), encoding="utf-8")
    console.print(f"Proposal written to [bold]{target}[/bold].")
    console.print(
        f"Review it, then move it over {seed_file.name} yourself, or re-run with --apply."
    )


def _append_to_seed_file(seed_file: Path, questions, *, header: str) -> None:  # type: ignore[no-untyped-def]
    """Add verified rows to the seed file without disturbing what is there.

    Ids already in the file are skipped rather than replaced. The seed file is
    the expert's record, and a drafted row is never allowed to overwrite one a
    human wrote.
    """
    import json

    from sci_rag.evals.seeds import load_seed_questions

    existing = {q.id for q in load_seed_questions(seed_file)} if seed_file.exists() else set()
    fresh = [q for q in questions if q.id not in existing]
    skipped = [q.id for q in questions if q.id in existing]
    for question_id in skipped:
        console.print(
            f"  [yellow]skipped[/yellow] {question_id}: that id is already in the seed file."
        )
    if not fresh:
        console.print("[yellow]Every drafted id was already taken; nothing appended.[/yellow]")
        return

    body = "\n".join(json.dumps(question.model_dump(), ensure_ascii=False) for question in fresh)
    current = seed_file.read_text(encoding="utf-8") if seed_file.exists() else ""
    if current and not current.endswith("\n"):
        current += "\n"
    seed_file.write_text(f"{current}{header}{body}\n", encoding="utf-8")


__all__ = ["draft_app"]


@draft_app.command("manifest")
def draft_manifest_command(
    folder: Path | None = typer.Option(
        None, "--folder", help="Documents to describe. Defaults to <data_dir>/raw."
    ),
    print_prompt: bool = typer.Option(
        False,
        "--print-prompt",
        help=(
            "Print the rendered prompt and exit. It may contain corpus text; "
            "send it only to an approved destination."
        ),
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Read the model's reply from this file, with no model call.",
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Where to write the proposal. Defaults to <manifest>.proposed."
    ),
    manifest: Path | None = typer.Option(
        None, "--manifest", help="The manifest being drafted. Defaults to <data_dir>/corpus.jsonl."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write the manifest directly, with no .proposed file to review."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be drafted without writing anything."
    ),
    batch_size: int = typer.Option(
        None, "--batch-size", help="Documents per model call. Defaults to 12."
    ),
) -> None:
    """Read title, authors, year, and source off your documents. Rights stay yours."""
    from sci_rag.cli.main import run_async
    from sci_rag.config import get_settings
    from sci_rag.draft import DraftError, proposed_path, read_reply
    from sci_rag.draft.manifest import (
        BATCH_SIZE,
        draft_manifest,
        read_heads,
        render_jsonl,
        render_prompt,
    )

    if apply and dry_run:
        raise typer.BadParameter("--apply and --dry-run ask for opposite things")

    settings = get_settings()
    source_folder = folder or (settings.data_dir / "raw")
    target_manifest = manifest or (settings.data_dir / "corpus.jsonl")

    try:
        heads = read_heads(source_folder)
    except DraftError as exc:
        _fail(str(exc))
        return

    if print_prompt:
        print(render_prompt(settings.domain_dir, heads=heads, source_buckets=[]))
        if len(heads) > (batch_size or BATCH_SIZE):
            console.print(
                f"[yellow]{len(heads)} documents were found and this prompt covers all of "
                "them. If your assistant truncates it, narrow --folder and run again per "
                "subfolder.[/yellow]"
            )
        return

    try:
        result = run_async(
            draft_manifest(
                settings.domain_dir,
                heads=heads,
                raw_reply=read_reply(from_file) if from_file is not None else None,
                batch_size=batch_size or BATCH_SIZE,
            )
        )
    except DraftError as exc:
        _fail(str(exc))
        return

    console.print(f"Read {len(heads)} documents from {source_folder}.")
    for entry in result.entries:
        year = entry.year or "----"
        console.print(f"  [green]row[/green]     {entry.path.name}: {entry.title} ({year})")
    for filename, reason in result.dropped:
        console.print(f"  [red]dropped[/red] {filename}: {reason}")
    for note in result.notes:
        console.print(f"  [yellow]note[/yellow]    {note}")

    if not result.entries:
        _fail("No row survived validation, so there is nothing to write.")
        return

    console.print(f"\nSource buckets: {', '.join(result.source_buckets) or 'none'}.")
    console.print(
        f"[yellow]{result.needs_rights_decision} documents need a rights decision.[/yellow] "
        'Every row says license_class "unknown", which excludes it from scoped '
        'retrieval until you say otherwise. See "Scope precedes ranking" in '
        "docs/methodology.md."
    )

    if dry_run:
        console.print("[yellow]Dry run. Nothing was written.[/yellow]")
        return

    target = output or (target_manifest if apply else proposed_path(target_manifest))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_jsonl(result.entries, manifest_path=target), encoding="utf-8")
    console.print(f"Written to [bold]{target}[/bold].")
    if not apply:
        console.print(
            f"Review it, set the license classes, then move it over "
            f"{target_manifest.name}, or re-run with --apply."
        )


@draft_app.command("ontology")
def draft_ontology_command(
    from_corpus: bool = typer.Option(
        False,
        "--from-corpus",
        help=(
            "Draft from passages in your ingested corpus (or data/raw before ingestion). "
            "This is the default; the flag names it explicitly."
        ),
    ),
    refine: bool = typer.Option(
        False,
        "--refine",
        help="Show the model your ontology and ask only what it would add and remove.",
    ),
    cold: bool = typer.Option(
        False,
        "--cold",
        help="Draft from the description alone, without reading any document.",
    ),
    folder: Path | None = typer.Option(
        None,
        "--folder",
        help="Draft from documents in this folder, before anything is ingested.",
    ),
    print_prompt: bool = typer.Option(
        False,
        "--print-prompt",
        help=(
            "Print the rendered prompt and exit. It may contain corpus text; "
            "send it only to an approved destination."
        ),
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Read the model's reply from this file, with no model call.",
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Where to write the proposal. Defaults to <domain.yaml>.proposed."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write domain.yaml directly, with no .proposed file to review."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without writing anything."
    ),
) -> None:
    """Redraft or refine the ontology against what your documents actually say."""
    from sci_rag.cli.main import run_async
    from sci_rag.config import get_settings
    from sci_rag.domain import load_domain
    from sci_rag.draft import DraftError, proposed_path, read_reply
    from sci_rag.draft.ontology import (
        apply_refinement,
        draft_from_corpus,
        render_prompt,
        render_yaml,
        summarize_change,
    )

    if apply and dry_run:
        raise typer.BadParameter("--apply and --dry-run ask for opposite things")
    if sum(1 for flag in (from_corpus, refine, cold) if flag) > 1:
        raise typer.BadParameter("choose one of --from-corpus, --refine, or --cold")

    settings = get_settings()
    try:
        domain = load_domain(settings.domain_dir)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
        return
    current = domain.config

    if cold:
        drafted = _cold_draft(domain, from_file=from_file, print_prompt=print_prompt)
        if drafted is None:
            return
    else:
        # Passage count is fixed here rather than exposed: the ontology is
        # judged against the breadth of the corpus, not against a budget.
        sample = _gather_passages(folder, count=8)
        existing = current if refine else None
        if print_prompt:
            print(render_prompt(domain, sample=sample, existing=existing))
            return
        try:
            drafted = run_async(
                draft_from_corpus(
                    domain,
                    sample=sample,
                    existing=existing,
                    raw_reply=read_reply(from_file) if from_file is not None else None,
                )
            )
        except DraftError as exc:
            _fail(str(exc))
            return
        console.print(f"Grounded in {sample.describe()}.")

    if refine and not drafted.is_refinement:
        console.print(
            "[yellow]--refine asked for additions and removals; the model returned a whole "
            "ontology. Treating it as a redraft.[/yellow]"
        )

    try:
        proposed = apply_refinement(
            current, drafted, replace=not (refine and drafted.is_refinement)
        )
    except DraftError as exc:
        _fail(str(exc))
        return

    for kind, name, reason in drafted.removals:
        console.print(f"  [yellow]removing[/yellow] {kind} {name}: {reason}")
    console.print("\nProposed change:")
    for line in summarize_change(current, proposed):
        console.print(line)
    # The diff alone hides the shape of the result: a redraft that changes
    # nothing and a redraft that keeps eight of nine types read the same.
    console.print(
        "\nResulting ontology: " + ", ".join(entity.name for entity in proposed.entity_types)
    )
    console.print(
        "The retrieval: and compression: blocks are carried over untouched; "
        "they are tuned numbers, not domain semantics."
    )

    if dry_run:
        console.print("[yellow]Dry run. Nothing was written.[/yellow]")
        return

    domain_yaml = settings.domain_dir / "domain.yaml"
    target = output or (domain_yaml if apply else proposed_path(domain_yaml))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_yaml(proposed), encoding="utf-8")
    console.print(f"Written to [bold]{target}[/bold].")
    if not apply:
        console.print(
            "Review it against your current domain.yaml, then move it over, or re-run "
            "with --apply. Redrafting the ontology changes what the graph extractor "
            "looks for, so re-run `sci-rag graph extract` afterwards."
        )


def _cold_draft(domain, *, from_file: Path | None, print_prompt: bool):  # type: ignore[no-untyped-def]
    """The wizard's draft: a description, no documents, today's behaviour.

    Goes through :mod:`sci_rag.scaffold.ontology` rather than reimplementing
    it, so `sci-rag init` and `sci-rag draft ontology --cold` cannot drift.
    """
    from sci_rag.cli.main import run_async
    from sci_rag.draft import DraftError, read_reply
    from sci_rag.draft.ontology import DraftedOntology, parse_reply
    from sci_rag.scaffold.ontology import OntologyDraftError, draft_ontology
    from sci_rag.scaffold.ontology import render_prompt as render_cold_prompt

    project_name = domain.name
    description = domain.config.description or project_name

    if print_prompt:
        try:
            print(
                render_cold_prompt(
                    domain.directory, project_name=project_name, description=description
                )
            )
        except OntologyDraftError as exc:
            _fail(str(exc))
        return None

    if from_file is not None:
        try:
            return parse_reply(read_reply(from_file))
        except DraftError as exc:
            _fail(str(exc))
            return None

    try:
        config = run_async(
            draft_ontology(domain.directory, project_name=project_name, description=description)
        )
    except OntologyDraftError as exc:
        _fail(str(exc))
        return None
    return DraftedOntology(
        entity_types=list(config.entity_types),
        relation_types=list(config.relation_types),
        query_classes=list(config.query_classes),
    )


@draft_app.command("prompts")
def draft_prompts_command(
    name: str = typer.Argument(..., help="Which prompt to reword: entity_extraction or answer."),
    print_prompt: bool = typer.Option(
        False,
        "--print-prompt",
        help=(
            "Print the rendered prompt and exit. It may contain corpus text; "
            "send it only to an approved destination."
        ),
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Read the model's reply from this file, with no model call.",
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Where to write the proposal. Defaults to <prompt>.md.proposed."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write the prompt file directly, with no .proposed file to review."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show the rewrite without writing anything."
    ),
) -> None:
    """Reword a prompt for your field. Judge prompts are refused by name."""
    from sci_rag.cli.main import run_async
    from sci_rag.config import get_settings
    from sci_rag.domain import load_domain
    from sci_rag.draft import DraftError, proposed_path, read_reply
    from sci_rag.draft.prompts import draft_prompt, render_prompt

    if apply and dry_run:
        raise typer.BadParameter("--apply and --dry-run ask for opposite things")

    settings = get_settings()
    try:
        domain = load_domain(settings.domain_dir)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
        return

    if print_prompt:
        try:
            print(render_prompt(domain, name=name))
        except DraftError as exc:
            _fail(str(exc))
        return

    try:
        rewritten = run_async(
            draft_prompt(
                domain,
                name=name,
                raw_reply=read_reply(from_file) if from_file is not None else None,
            )
        )
    except DraftError as exc:
        _fail(str(exc))
        return

    target_prompt = settings.domain_dir / "prompts" / f"{name}.md"
    original = target_prompt.read_text(encoding="utf-8")
    console.print(
        f"Rewrote {name}: {len(original.splitlines())} lines in, "
        f"{len(rewritten.splitlines())} out. Every required slot survived and the "
        "template still renders."
    )
    console.print(
        "[yellow]Read the diff before applying.[/yellow] Prompt wording moves every "
        "downstream number, so re-run `sci-rag eval retrieval --ablation` and compare "
        "before and after."
    )

    if dry_run:
        console.print("[yellow]Dry run. Nothing was written.[/yellow]")
        return

    target = output or (target_prompt if apply else proposed_path(target_prompt))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rewritten, encoding="utf-8")
    console.print(f"Written to [bold]{target}[/bold].")
    if not apply:
        console.print(f"  diff {target_prompt} {target}")
