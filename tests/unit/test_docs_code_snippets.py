"""Guards for how the documentation presents code snippets.

Readers copy these blocks into their own project, so a snippet that quotes a
project file has to say which file it came from. The header bar is the only
place that can say it, and a header naming a path that does not exist is worse
than no header at all. These tests keep both halves honest: every header that
is not one of the two environment labels resolves to a real repository path,
and every snippet written in a language this repository only ever uses to quote
a project file carries such a header.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

# Headers that name where a command runs rather than a file it came from.
ENVIRONMENT_TITLES = frozenset({"Terminal", "Repository root"})

# Files the documentation tells the reader to create, so they are absent from a
# clean checkout. A header may name them; the guard cannot check them on disk.
READER_CREATED_PATHS = frozenset(
    {
        ".env",
        ".conductor/archive-cloud-workspace.sh",
        ".conductor/run-cloud-tests.sh",
        ".conductor/settings.local.toml",
        ".conductor/setup-cloud-workspace.sh",
        # Written by `terraform output`, or by hand, when a reader configures
        # the Cloud SQL helper. Ignored, so never present in a checkout.
        ".cloudsql/config.env",
        "data/corpus.jsonl",
        "generated/typescript/status.ts",
        "openapi-python-client.yaml",
        "python-status.py",
    }
)

# Languages this repository only uses when quoting a file from the project.
FILE_QUOTING_LANGUAGES = frozenset({"dotenv", "yaml", "jsonl"})

# Planning notes are excluded from the built site, so the site conventions do
# not apply to them.
EXCLUDED_DIRS = ("planning",)

FENCE = re.compile(r"^(?P<marker>```+|~~~+)(?P<info>.*)$")
TITLE = re.compile(r'title="(?P<title>[^"]*)"')


def _site_pages() -> list[Path]:
    return sorted(
        path
        for path in DOCS.rglob("*.md")
        if not any(part in EXCLUDED_DIRS for part in path.relative_to(DOCS).parts)
    )


def _fences(page: Path) -> list[tuple[int, str, str | None]]:
    """Return (line number, language, title) for every opening fence on a page."""
    opened: list[tuple[int, str, str | None]] = []
    marker: str | None = None
    for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), start=1):
        match = FENCE.match(line)
        if match is None:
            continue
        if marker is None:
            marker = match.group("marker")
            info = match.group("info")
            title = TITLE.search(info)
            opened.append(
                (number, info.split()[0] if info.split() else "", title["title"] if title else None)
            )
        elif match.group("marker").startswith(marker) and not match.group("info").strip():
            marker = None
    return opened


def test_documentation_pages_are_discoverable() -> None:
    # A silently empty scan would make both guards below pass for free.
    pages = _site_pages()
    assert len(pages) > 20, f"expected the full documentation set, found {len(pages)}"
    assert any(_fences(page) for page in pages), "expected fenced code blocks in the docs"


def test_snippet_headers_name_a_real_repository_path() -> None:
    offenders = []
    for page in _site_pages():
        for number, _language, title in _fences(page):
            if title is None or title in ENVIRONMENT_TITLES:
                continue
            # "~/" marks a file at the project root, the way a shell prompt does.
            relative = title[2:] if title.startswith("~/") else title
            if relative not in READER_CREATED_PATHS and not (ROOT / relative).exists():
                offenders.append(
                    f"{page.relative_to(ROOT)}:{number}: {title!r} is not a repository path"
                )
            elif "/" not in relative and not title.startswith("~/"):
                offenders.append(
                    f"{page.relative_to(ROOT)}:{number}: {title!r} should be '~/{relative}'"
                )

    assert not offenders, (
        f"a snippet header must be an environment label or a full repository path: {offenders}"
    )


def test_snippets_that_quote_a_project_file_carry_its_path() -> None:
    offenders = [
        f"{page.relative_to(ROOT)}:{number}: {language} block has no title"
        for page in _site_pages()
        for number, language, title in _fences(page)
        if language in FILE_QUOTING_LANGUAGES and title is None
    ]

    assert not offenders, f"these snippets quote a project file without naming it: {offenders}"


# --- paired drafter commands select the same passages ------------------------
#
# F-021 in the 2026-08-29 documentation route audit. The no-credential drafting
# route is two commands: `--print-prompt` renders a corpus-grounded prompt, and
# `--from-file` validates the reply against the same passages. `--count` and
# `--folder` decide which passages those are, so the page says to pass the same
# values to both. Its own example passed `--count 10` only to the first, and
# worked anyway because ten is also the default. The stated invariant and the
# copy-paste commands only agreed by coincidence.

SELECTORS = ("--count", "--folder")


def _drafter_commands(block: str) -> list[list[str]]:
    """Every `sci-rag draft ...` invocation in one code block, tokenised."""
    commands = []
    for line in block.splitlines():
        stripped = line.strip().removeprefix("$ ")
        if "sci-rag draft " not in stripped:
            continue
        commands.append(stripped.split())
    return commands


def _selector_values(tokens: list[str]) -> dict[str, str]:
    found = {}
    for selector in SELECTORS:
        if selector in tokens:
            index = tokens.index(selector)
            if index + 1 < len(tokens):
                found[selector] = tokens[index + 1]
    return found


def _paired_blocks() -> list[tuple[Path, str]]:
    """Code blocks that show both halves of the no-credential route."""
    blocks = []
    for page in _site_pages():
        text = page.read_text(encoding="utf-8")
        for block in re.findall(
            r"^\s*(?:```|~~~)[^\n]*\n(.*?)^\s*(?:```|~~~)", text, re.DOTALL | re.MULTILINE
        ):
            if "--print-prompt" in block and "--from-file" in block:
                blocks.append((page, block))
    return blocks


def test_the_documentation_still_shows_the_paired_route() -> None:
    """If nothing pairs them, the test below is asserting nothing."""
    assert _paired_blocks(), "no page shows --print-prompt and --from-file together"


def test_paired_drafter_commands_repeat_their_selectors() -> None:
    """Changing a selector between the halves validates a reply against
    passages the assistant never saw, which surfaces as evidence phrases
    dropped for being ungrounded."""
    offenders = []
    for page, block in _paired_blocks():
        printing = [c for c in _drafter_commands(block) if "--print-prompt" in c]
        reading = [c for c in _drafter_commands(block) if "--from-file" in c]
        for first, second in zip(printing, reading, strict=False):
            printed = _selector_values(first)
            read = _selector_values(second)
            if printed != read:
                offenders.append(
                    f"{page.relative_to(DOCS.parent)}: --print-prompt passes {printed}, "
                    f"--from-file passes {read}"
                )

    assert offenders == [], "paired drafter commands must select the same passages: " + "; ".join(
        offenders
    )
