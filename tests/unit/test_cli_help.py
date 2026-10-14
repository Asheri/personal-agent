"""CLI wiring smokes: every command parses, help renders, bad input is caught.

These run with no database and no credentials; they protect the command
surface the docs promise.
"""

import re
from pathlib import Path

from typer.testing import CliRunner

from sci_rag.cli.main import app

# Rich adapts help output to the terminal (colors on CI, 80-column
# wrapping); pin a wide, colorless rendering and strip any ANSI that
# slips through so these asserts are environment-independent.
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "300"})
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(output: str) -> str:
    return _ANSI.sub("", output)


def test_root_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    for command in ("ingest", "retrieve", "answer", "stats", "serve", "mcp", "doctor"):
        assert command in output
    for group in ("db", "graph", "eval", "campaign", "draft"):
        assert group in output


def test_subcommand_help_screens() -> None:
    for args in (
        ["db", "--help"],
        ["db", "upgrade", "--help"],
        ["ingest", "--help"],
        ["corpus", "--help"],
        ["corpus", "enrich", "--help"],
        ["campaign", "--help"],
        ["campaign", "discover", "--help"],
        ["campaign", "build", "--help"],
        ["graph", "--help"],
        ["graph", "extract", "--help"],
        ["graph", "communities", "--help"],
        ["graph", "resolve-entities", "--help"],
        ["draft", "--help"],
        ["draft", "questions", "--help"],
        ["draft", "manifest", "--help"],
        ["draft", "ontology", "--help"],
        ["draft", "prompts", "--help"],
        ["eval", "--help"],
        ["eval", "retrieval", "--help"],
        ["eval", "answers", "--help"],
        ["retrieve", "--help"],
        ["answer", "--help"],
        ["serve", "--help"],
        ["doctor", "--help"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, f"{args}: {result.output}"


def test_documented_flags_exist() -> None:
    ingest_help = _plain(runner.invoke(app, ["ingest", "--help"]).output)
    for flag in ("--manifest", "--source", "--no-docling", "--chunk-tokens", "--overlap-tokens"):
        assert flag in ingest_help
    extract_help = _plain(runner.invoke(app, ["graph", "extract", "--help"]).output)
    for flag in ("--all", "--batch-size", "--max-chunks"):
        assert flag in extract_help
    resolve_help = _plain(runner.invoke(app, ["graph", "resolve-entities", "--help"]).output)
    for flag in ("--dry-run", "--apply", "--no-llm", "--threshold", "--llm-threshold"):
        assert flag in resolve_help
    eval_help = _plain(runner.invoke(app, ["eval", "retrieval", "--help"]).output)
    for flag in ("--ablation", "--condition", "--questions", "--limit", "--snapshot"):
        assert flag in eval_help
    answer_help = _plain(runner.invoke(app, ["answer", "--help"]).output)
    assert "--include-retracted" in answer_help
    enrich_help = _plain(runner.invoke(app, ["corpus", "enrich", "--help"]).output)
    for flag in ("--dry-run", "--limit", "--mailto"):
        assert flag in enrich_help
    campaign_help = _plain(runner.invoke(app, ["campaign", "discover", "--help"]).output)
    for flag in ("--topic", "--doi-file", "--name", "--mailto", "--max-results"):
        assert flag in campaign_help
    build_help = _plain(runner.invoke(app, ["campaign", "build", "--help"]).output)
    for flag in (
        "--topic",
        "--doi-file",
        "--name",
        "--mailto",
        "--dry-run",
        "--max-results",
        "--max-pdf-mb",
    ):
        assert flag in build_help
    doctor_help = _plain(runner.invoke(app, ["doctor", "--help"]).output)
    assert "--probe" in doctor_help


def test_ingest_rejects_ambiguous_input() -> None:
    # Neither a folder nor a manifest.
    neither = runner.invoke(app, ["ingest"])
    assert neither.exit_code != 0
    assert "exactly one" in _plain(neither.output)
    # Both at once.
    both = runner.invoke(app, ["ingest", "data/raw", "--manifest", "x.jsonl"])
    assert both.exit_code != 0
    assert "exactly one" in _plain(both.output)


def test_resolved_entity_eval_requires_a_named_snapshot() -> None:
    result = runner.invoke(app, ["eval", "retrieval", "--condition", "resolved_entities"])

    assert result.exit_code != 0
    assert "--snapshot" in _plain(result.output)


# --- the commands the documentation promises exist ---------------------------
#
# F-007 in the 2026-08-29 documentation route audit: two published pages told
# readers to run `sci-rag embed plan`, which has never existed. `sci-rag embed`
# lists only `reindex`, so the reader got exit code 2 and `No such command`.
#
# The guard walks the real command tree rather than help text. Note the shape
# of the check: `isinstance(node, click.Group)` looks right and is silently
# always false here, because `typer.main.get_command` returns a
# `typer._click.core.Command` rather than a `click.core.Group`. A guard written
# that way passes on everything, including the defect it was added for.

DOC_ROOTS = ("README.md", "AGENTS.md", "CONTRIBUTING.md")
EXCLUDED_DOC_DIRS = ("planning",)

# A mention only counts when it is formatted as a command. `docs/api.md` says
# "several sci-rag deployments", which is prose about deployments.
CODE_MENTION = re.compile(r"(?<![\w-])sci-rag((?:\s+[A-Za-z0-9_./-]+)*)")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^(?:```|~~~)[^\n]*\n(.*?)^(?:```|~~~)", re.DOTALL | re.MULTILINE)
COMMAND_TOKEN = re.compile(r"^[a-z][a-z0-9-]*$")

# Stale commands that belong to another open finding. Each entry names the
# issue that owns it, and `test_every_pending_exception_still_describes_a_real
# _mention` fails once the documentation no longer says it, so an exception
# cannot outlive its fix. Empty is the intended steady state: the last entry,
# `campaign report`, retired with #157.
PENDING_FINDINGS: dict[tuple[str, ...], str] = {}


def _documented_pages() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    pages = [root / name for name in DOC_ROOTS]
    pages += [
        path
        for path in sorted((root / "docs").rglob("*.md"))
        if not any(part in EXCLUDED_DOC_DIRS for part in path.parts)
    ]
    return [path for path in pages if path.is_file()]


def _code_spans(text: str) -> list[str]:
    spans = [block for block in FENCE.findall(text)]
    spans += INLINE_CODE.findall(text)
    return spans


def _mentioned_command_paths() -> dict[tuple[str, ...], set[str]]:
    """Every `sci-rag ...` path the documentation formats as a command."""
    found: dict[tuple[str, ...], set[str]] = {}
    for page in _documented_pages():
        text = page.read_text(encoding="utf-8")
        for span in _code_spans(text):
            for mention in CODE_MENTION.finditer(span):
                tokens: list[str] = []
                for raw in mention.group(1).split():
                    if not COMMAND_TOKEN.match(raw):
                        break
                    tokens.append(raw)
                if tokens:
                    found.setdefault(tuple(tokens), set()).add(page.name)
    return found


def _resolve(tokens: tuple[str, ...]) -> tuple[str, ...] | None:
    """The first path prefix that names nothing, or None when all of it resolves.

    Duck-typed on ``commands`` rather than on ``click.Group``. Once a leaf
    command is reached the remaining tokens are arguments, not subcommands.
    """
    from typer.main import get_command

    node = get_command(app)
    for index, token in enumerate(tokens):
        if not hasattr(node, "commands"):
            return None
        child = node.commands.get(token)
        if child is None:
            return tokens[: index + 1]
        node = child
    return None


def test_the_guard_can_see_a_command_that_does_not_exist() -> None:
    """A resolver that never fails would make every test below vacuous."""
    assert _resolve(("embed", "reindex")) is None
    assert _resolve(("embed", "plan")) == ("embed", "plan")
    assert _resolve(("doctor",)) is None
    # Arguments after a leaf command are not subcommands.
    assert _resolve(("doctor", "anything")) is None


def test_every_documented_command_exists() -> None:
    offenders = []
    for tokens, pages in sorted(_mentioned_command_paths().items()):
        missing = _resolve(tokens)
        if missing is None or missing in PENDING_FINDINGS:
            continue
        offenders.append(f"sci-rag {' '.join(missing)} in {sorted(pages)}")
    assert offenders == [], f"documented commands that do not exist: {offenders}"


def test_every_pending_exception_still_describes_a_real_mention() -> None:
    """An exception that outlives its fix is a guard with a hole in it."""
    mentioned = _mentioned_command_paths()
    stale = [
        f"sci-rag {' '.join(tokens)} ({owner})"
        for tokens, owner in PENDING_FINDINGS.items()
        if not any(path[: len(tokens)] == tokens for path in mentioned)
    ]
    assert stale == [], f"remove these exceptions, the documentation no longer says them: {stale}"
