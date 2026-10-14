"""Render the homepage's Quick and Advanced ``sci-rag new`` sessions.

The session on the documentation homepage is not typed by hand. It is produced
by driving the real wizard with a scripted set of answers and capturing exactly
what it printed, so a question added to ``sci_rag.scaffold.questions`` shows up
here or ``--check`` fails. A hand-recorded cast goes stale the first time
someone edits the question list, silently, on the page a new user reads first.

Two artifacts come out of two runs:

* ``docs/assets/casts/sci-rag-new.cast``, the recommended Quick session.
* both static transcripts in ``docs/index.md``, with Advanced collapsed beneath the Quick session.

The two model calls are stubbed: credential preflight returns a fixed success,
and ontology drafting uses the same mock LLM client as the tests. Their output
still passes through the real rendering code. Everything else, including the
change log and closing next steps, is the program's own output for these
answers.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import shutil
from pathlib import Path

from rich.console import Console

from sci_rag.cli.new import _preflight_credentials
from sci_rag.config import DEFAULT_LLM_MODEL
from sci_rag.llm import MockLLM
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.apply import apply_all
from sci_rag.scaffold.preflight import CredentialProbe
from sci_rag.scaffold.prompt import PlainPrompter
from sci_rag.scaffold.report import print_scaffold_report
from sci_rag.scaffold.wizard import collect_answers, confirm_ontology_draft

REPO_ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- BEGIN GENERATED TRANSCRIPT: scripts/render_cast.py -->"
END = "<!-- END GENERATED TRANSCRIPT -->"

# The Advanced session exercises every gated branch. Blank values still press
# Enter, so questions added later appear without a positional reply list.
ADVANCED_ANSWERS = {
    "project_name": "Membrane Materials KB",
    "description": "Membrane chemistry and performance for water treatment",
    "author_name": "Berkeley Lab",
    "contact_email": "you@lbl.gov",
    "environment_manager": "2",
    "credentials": "1",
    "google_api_key": "cast-example-key",
    "ontology": "1",
    "corpus_source": "2",
    "openalex_topic": "polyamide membrane fouling",
    "max_results": "250",
    "pdf_parser": "2",
    "include_terraform": "2",
    "include_demo_corpus": "2",
}

QUICK_ANSWERS = {
    "project_name": "Membrane Materials KB",
    "description": "Membrane chemistry and performance for water treatment",
    "contact_email": "you@lbl.gov",
    "environment_manager": "1",
    "credentials": "1",
    "google_api_key": "cast-example-key",
    "corpus_source": "1",
}

# The response the mock model gives for the ontology draft. Kept here rather
# than generated so the page is byte-stable between runs.
DRAFTED_ONTOLOGY = json.dumps(
    {
        "entity_types": [
            {"name": "Membrane", "description": "A separation layer"},
            {"name": "Material", "description": "What a membrane is made of"},
            {"name": "Contaminant", "description": "Something removed from water"},
            {"name": "Process", "description": "A treatment or fabrication step"},
            {"name": "Property", "description": "A measured characteristic"},
            {"name": "Application", "description": "Where the membrane is used"},
            {"name": "Organization", "description": "A lab, agency, or vendor"},
            {"name": "Standard", "description": "A test method or specification"},
        ],
        "relation_types": [
            {"name": "MADE_OF"},
            {"name": "REMOVES"},
            {"name": "HAS_PROPERTY"},
            {"name": "USED_IN"},
            {"name": "REQUIRES"},
            {"name": "COMPARED_WITH"},
        ],
        "query_classes": [
            {"name": "performance", "keywords": ["flux", "rejection"]},
            {"name": "fabrication", "keywords": ["casting", "coating"]},
            {"name": "fouling", "keywords": ["fouling", "cleaning"]},
            {"name": "application", "keywords": ["desalination", "reuse"]},
        ],
    }
)

# Files an applier reads or rewrites, copied into a scratch tree so rendering
# the page never touches the working directory.
_TEMPLATE_FILES = ("pyproject.toml", "Makefile", "Dockerfile", ".env.example", "README.md")
_TEMPLATE_TREES = ("domain", ".github", ".devcontainer")


def _input_stream(*, quick: bool) -> io.StringIO:
    """One line per visible question, following the same gates as the wizard."""
    from sci_rag.scaffold.questions import QUESTIONS, default_for, is_asked

    scripted = QUICK_ANSWERS if quick else ADVANCED_ANSWERS
    replies = ["1" if quick else "2"]
    gathered: dict[str, str] = {}
    for question in QUESTIONS:
        if not is_asked(question, gathered):
            continue
        default = default_for(question, gathered)
        reply = scripted.get(question.name, "")
        if quick and not question.quick:
            gathered[question.name] = default
            continue
        replies.append(reply)
        if not reply:
            gathered[question.name] = default
        elif question.choices and reply.isdigit():
            gathered[question.name] = question.choices[int(reply) - 1]
        else:
            gathered[question.name] = reply
    return io.StringIO("\n".join(replies) + "\n")


def _scratch_template(root: Path) -> Path:
    target = root / "template"
    target.mkdir(parents=True)
    for name in _TEMPLATE_FILES:
        shutil.copy(REPO_ROOT / name, target / name)
    for tree in _TEMPLATE_TREES:
        shutil.copytree(
            REPO_ROOT / tree, target / tree, ignore=shutil.ignore_patterns("__pycache__")
        )
    for extra in ("infra/terraform", "data/demo", "examples", "docs/planning"):
        (target / extra).mkdir(parents=True, exist_ok=True)
        (target / extra / ".keep").write_text("", encoding="utf-8")
    return target


def render_transcript(*, quick: bool = True) -> str:
    """One complete Quick or Advanced session, as the program prints it."""
    import tempfile

    output = io.StringIO()
    output.write("$ pipx install sci-rag-kit\n$ sci-rag new\n")

    raw = collect_answers(input_stream=_input_stream(quick=quick), output_stream=output)
    _preflight_credentials(
        raw,
        PlainPrompter(io.StringIO(), output),
        probe=lambda **_kwargs: CredentialProbe(
            True,
            f"{DEFAULT_LLM_MODEL} check simulated for this recording; no model request sent.",
        ),
    )

    drafted = confirm_ontology_draft(
        REPO_ROOT / "domain",
        project_name=raw["project_name"],
        description=raw["description"],
        llm=MockLLM(responses=[DRAFTED_ONTOLOGY]),
        input_stream=io.StringIO("\n"),
        output_stream=output,
    )
    answers = ProjectAnswers.from_raw(raw, drafted_ontology=drafted)  # type: ignore[arg-type]

    with tempfile.TemporaryDirectory() as scratch:
        template = _scratch_template(Path(scratch))
        output.write(f"\nFetching sci-rag-kit for {answers.repo_name}...\n")
        changes = apply_all(answers, template, year=2026)

    print_scaffold_report(
        answers,
        changes,
        console=Console(file=output, color_system=None, force_terminal=False, width=300),
        created_directory=True,
    )
    # Pressing Enter leaves the prompt with a trailing space. The
    # trailing-whitespace pre-commit hook would strip it from the committed
    # page and make --check fail forever, so strip it at the source.
    return "".join(f"{line.rstrip()}\n" for line in output.getvalue().splitlines())


_PROMPT_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*) \(([^)]*)\):(.*)$")
_CHOICE_LINE = re.compile(r"^(\d+) - (.+)$")
_CHOOSE_LINE = re.compile(r"^(Choose from \S+ \([^)]+\):)(.*)$")
_ACCEPT_LINE = re.compile(r"^(Accept this ontology\? \[[^\]]+\] \([^)]+\):)(.*)$")


_ROLE_CLASS = {
    "prompt": "srag-term__prompt",
    "cmd": "srag-term__cmd",
    "key": "srag-term__key",
    "default": "srag-term__default",
    "value": "srag-term__value",
    "heading": "srag-term__heading",
    "choice-n": "srag-term__choice-n",
    "choice": "srag-term__choice",
    "status": "srag-term__status",
    "done": "srag-term__heading",
}

# SGR 1 is bold (commands, answers); SGR 2 is faint (prompts, menus).
_ROLE_SGR = {
    "prompt": "2",
    "default": "2",
    "choice-n": "2",
    "key": "2",
    "choice": "2",
    "status": "2",
    "cmd": "1",
    "value": "1",
    "heading": "1",
    "done": "1;32",
}


def _span(class_name: str, text: str) -> str:
    return f'<span class="{class_name}">{html.escape(text)}</span>'


def _parse_line(line: str, *, in_next: bool) -> tuple[str, list[tuple[str, str]]]:
    """Split one transcript line into ``(kind, [(role, text), ...])``."""
    if line.startswith("$ "):
        return "cmd", [("prompt", "$ "), ("cmd", line[2:])]
    if line.startswith("Select "):
        return "select", [("heading", line)]
    choice = _CHOICE_LINE.match(line)
    if choice:
        return "choice", [("choice-n", f"{choice.group(1)} - "), ("choice", choice.group(2))]
    choose = _CHOOSE_LINE.match(line)
    if choose:
        return "choose", [("key", choose.group(1)), ("value", choose.group(2))]
    accept = _ACCEPT_LINE.match(line)
    if accept:
        return "prompt", [("key", accept.group(1)), ("value", accept.group(2))]
    prompt = _PROMPT_LINE.match(line)
    if prompt:
        return (
            "prompt",
            [
                ("key", prompt.group(1)),
                ("default", f" ({prompt.group(2)}):"),
                ("value", prompt.group(3)),
            ],
        )
    if line.startswith("Done."):
        return "done", [("done", line)]
    if line.startswith("Fetching ") or line.startswith("Writing "):
        return "section", [("heading", line)]
    if in_next and line.startswith("  "):
        return "next", [("cmd", line)]
    if line.startswith("  "):
        return "status", [("status", line)]
    return "output", [("raw", line)]


Parsed = tuple[str, str, list[tuple[str, str]]]


def _parse_transcript(transcript: str) -> list[Parsed]:
    """Every line as ``(line, kind, parts)``, with question wording recognised.

    The plain prompter writes a question in words on the line above its
    ``field (default):`` line or its ``Select field`` menu. That line is only
    recognisable by what follows it, so classification needs one line of
    lookahead, which is why this runs over the whole transcript at once.
    """
    parsed: list[Parsed] = []
    in_next = False
    for line in transcript.splitlines():
        if not line:
            parsed.append((line, "empty", []))
            continue
        kind, parts = _parse_line(line, in_next=in_next)
        if kind == "done":
            in_next = True
        parsed.append((line, kind, parts))
    for index, (line, kind, _parts) in enumerate(parsed):
        if kind != "output":
            continue
        following = next((k for _l, k, _p in parsed[index + 1 :] if k != "empty"), None)
        if following in {"prompt", "select"}:
            parsed[index] = (line, "label", [("status", line)])
    return parsed


def _inner_html(parts: list[tuple[str, str]]) -> str:
    inner: list[str] = []
    for role, text in parts:
        class_name = _ROLE_CLASS.get(role)
        inner.append(_span(class_name, text) if class_name else html.escape(text))
    return "".join(inner)


def _ansi_line(parts: list[tuple[str, str]]) -> str:
    chunks: list[str] = []
    for role, text in parts:
        code = _ROLE_SGR.get(role)
        chunks.append(f"\x1b[{code}m{text}\x1b[0m" if code else text)
    return "".join(chunks)


def _split_typed_value(parts: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], str]:
    """Peel the typed answer off a prompt so it can be keyed in separately."""
    if not parts or parts[-1][0] != "value":
        return parts, ""
    prefix, value = parts[:-1], parts[-1][1]
    if value.startswith(" "):
        return [*prefix, ("raw", " ")], value[1:]
    return prefix, value


def _keystroke_delay(char: str, index: int, previous: str) -> float:
    """A stable, slightly uneven cadence. Must be deterministic for ``--check``."""
    if char == " ":
        return 0.11
    if char in "-_/.@":
        return 0.075
    beat = (0.048, 0.062, 0.052, 0.078, 0.05)[index % 5]
    if previous in {"", " "} and char.isupper():
        return beat + 0.045
    return beat


def _delay_after(kind: str, line: str) -> float:
    """Seconds to hold after a line so a command or choice can be read."""
    answered = kind in {"prompt", "choose"} and not line.rstrip().endswith("):")
    delays = {
        "empty": 0.22,
        "cmd": 1.2,
        "select": 0.32,
        "choice": 0.09,
        "choose": 1.45 if answered else 1.15,
        "prompt": 1.15 if answered else 0.9,
        "status": 0.18,
        "section": 0.7,
        "done": 1.6,
        "next": 0.75,
        "output": 0.25,
        "label": 0.45,
    }
    return delays.get(kind, 0.2)


def _needs_break(kind: str, previous: str | None) -> bool:
    if previous in {None, "empty"}:
        return False
    if kind == "label":
        return True
    if kind == "select":
        return previous != "label"
    if kind in {"section", "done"}:
        return True
    if kind == "status" and previous not in {"status", "empty"}:
        return True
    if kind == "prompt" and previous == "cmd":
        return True
    if kind == "cmd" and previous != "cmd":
        return True
    return kind == "next" and previous != "next"


def format_transcript_html(transcript: str) -> str:
    """Wrap the session in a Terminal block whose lines can be styled.

    A ``console`` fence only distinguishes ``$`` prompts from everything else,
    so the wizard's questions, answers, and menus all render as one weight.
    The plain text inside the ``<code>`` element is still the transcript, so
    copy stays honest.
    """
    rendered: list[str] = []
    previous: str | None = None
    for _line, kind, parts in _parse_transcript(transcript):
        if kind == "empty":
            rendered.append('<span class="srag-term__line srag-term__line--empty"></span>')
            previous = "empty"
            continue
        classes = f"srag-term__line srag-term__line--{kind}"
        if _needs_break(kind, previous):
            classes += " srag-term__break"
        rendered.append(f'<span class="{classes}">{_inner_html(parts)}</span>')
        previous = kind
    body = "\n".join(rendered) + "\n"
    return (
        '<div class="highlight srag-term">\n'
        '<span class="filename">Terminal</span>\n'
        f"<pre><code>{body}</code></pre>\n"
        "</div>\n"
    )


def render_cast(transcript: str) -> str:
    """An asciicast v2 file of the session, paced to be watched.

    Menu rows land at once. Freeform answers are keyed in character by
    character after a short pause, so the cursor blinks on the prompt the way
    a real wizard wait does. Timings are synthesized and deterministic.
    """
    width = max((len(line) for line in transcript.splitlines()), default=80) + 2
    header = {
        "version": 2,
        "width": max(width, 80),
        "height": 24,
        "title": "sci-rag new (generated by scripts/render_cast.py)",
        "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
    }
    events: list[tuple[float, str]] = []
    clock = 0.4

    def emit(payload: str) -> None:
        nonlocal clock
        stamp = round(clock, 3)
        if events and stamp <= events[-1][0]:
            stamp = round(events[-1][0] + 0.001, 3)
            clock = stamp
        events.append((stamp, payload))

    for line, kind, parts in _parse_transcript(transcript):
        if kind == "empty":
            emit("\r\n")
            clock += _delay_after("empty", line)
            continue
        if kind == "prompt":
            prefix, typed = _split_typed_value(parts)
            emit(_ansi_line(prefix))
            # Long enough for one cursor blink before the first key lands.
            clock += 1.12 if not typed else 0.92
            previous = ""
            for index, char in enumerate(typed):
                clock += _keystroke_delay(char, index, previous)
                emit(f"\x1b[1m{char}" if index == 0 else char)
                previous = char
            if typed:
                clock += 0.24
                emit("\x1b[0m\r\n")
            else:
                emit("\r\n")
            clock += 0.5 if typed else 0.62
            continue
        emit(_ansi_line(parts) + "\r\n")
        clock += _delay_after(kind, line)
    clock += 2.4
    emit("")
    lines = [json.dumps(header, separators=(",", ":"))]
    lines.extend(
        json.dumps([stamp, "o", payload], separators=(",", ":")) for stamp, payload in events
    )
    return "\n".join(lines) + "\n"


def render_index(index_text: str, quick: str, advanced: str) -> str:
    """Replace the generated block in docs/index.md, leaving the rest alone."""
    if BEGIN not in index_text or END not in index_text:
        raise SystemExit(
            f"docs/index.md is missing the generated-transcript markers ({BEGIN}). "
            "Add them around the example session block."
        )
    head, _, rest = index_text.partition(BEGIN)
    _, _, tail = rest.partition(END)
    block = (
        f"{BEGIN}\n\n{format_transcript_html(quick)}\n"
        "<details markdown>\n<summary>Show the Advanced setup</summary>\n\n"
        f"{format_transcript_html(advanced)}\n</details>\n\n{END}"
    )
    return head + block + tail


def _write_or_check(path: Path, content: str, *, check: bool) -> int:
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            print(f"stale generated artifact: {path}; run make cast")
            return 1
        print(f"up to date: {path}")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cast", type=Path, default=Path("docs/assets/casts/sci-rag-new.cast"))
    parser.add_argument("--index", type=Path, default=Path("docs/index.md"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    quick = render_transcript(quick=True)
    advanced = render_transcript(quick=False)
    status = _write_or_check(args.cast, render_cast(quick), check=args.check)
    status |= _write_or_check(
        args.index,
        render_index(args.index.read_text(encoding="utf-8"), quick, advanced),
        check=args.check,
    )
    raise SystemExit(status)


if __name__ == "__main__":
    main()
