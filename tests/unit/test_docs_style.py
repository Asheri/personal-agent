"""Guards for the house style, so the standard in `docs/STYLE.md` holds.

A style guide nobody checks is a document, not a standard. These tests are the
checkable half of `docs/STYLE.md`: every rule here has a sentence there that
explains it to a person, and every rule here is one a machine can decide. The
judgment calls, which are most of the guide, stay a review responsibility.

They exist because this documentation has already drifted twice in the same
direction. Retiring the obvious AI vocabulary left one mannerism behind, the
X-not-Y contrast, running at four times the density of ordinary prose; and one
verb, "specialize", spread to twenty-six places including a generated CLI page
where the word a reader wanted was "configure". Neither is a defect any test
could see, because both were locally correct every single time.

Each test's docstring names the reason it exists, so a contributor who trips
one can tell whether they found a violation or an exception worth adding.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
MKDOCS = ROOT / "mkdocs.yml"
STYLE = DOCS / "STYLE.md"

# Reader-facing prose held to the guide. `docs/planning/` is excluded from the
# built site and is a historical record of how the project got here, and
# `CHANGELOG.md` is a log of what happened; editing either for voice would be
# rewriting history. `AGENTS.md` is an operating contract for a different
# reader and keeps its own register, so only the terminology rules reach it.
EXCLUDED_DIRS = ("planning", "assets")
ROOT_PAGES = ("README.md", "CONTRIBUTING.md")

# Local and generated state is not repository source. Some of these directories
# can also contain private corpora, so the style test must not read them.
REPOSITORY_SCAN_EXCLUDED_DIRS = frozenset(
    {
        ".context",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "eval_results",
        "interim",
        "node_modules",
        "processed",
        "raw",
        "site",
    }
)

# The landing page is a template with its own masthead, so the page-shape
# rules that assume a title and a lede do not apply to it.
HOME = "index.md"

# Nav label on the left, page heading on the right, for the pages where the two
# deliberately differ. Keep this map short: every entry is a place a reader is
# told one name and shown another, and it should have to earn that.
TITLE_EXCEPTIONS = {
    # "FAQ" is what a reader scans a sidebar for; "Frequently asked questions"
    # is what the page is. The abbreviation would read oddly as a heading.
    "faq.md": "Frequently asked questions",
}

# Filler that says nothing, and the vocabulary that marks generated prose.
# The docs are clean of all of it today, so this is a ratchet rather than a
# repair: it keeps the next contributor, human or otherwise, from reopening
# the door. Each pattern is a whole phrase, because the individual words are
# often fine ("a robust argument" is not "robust retrieval").
BANNED_PHRASES = (
    r"it (?:is|'s) important to note",
    r"it should be noted",
    r"it (?:is|'s) worth noting",
    r"needless to say",
    r"as (?:we|you) can see",
    r"at the end of the day",
    r"in order to\b",
    r"the fact that",
    r"a wide (?:range|variety) of",
    r"in today's\b",
    r"in the (?:world|realm|landscape) of",
    r"when it comes to",
    r"first and foremost",
    r"last but not least",
    r"that being said",
    r"delve into",
    r"deep dive",
    r"\bleverag(?:e|es|ed|ing)\b",
    r"\bseamless(?:ly)?\b",
    r"\bstreamlin(?:e|es|ed|ing)\b",
    r"\bunlock(?:s|ed|ing)?\b",
    r"\btailored\b",
    r"\butiliz(?:e|es|ed|ing|ation)\b",
    r"\bcutting[- ]edge\b",
    r"\bbest[- ]in[- ]class\b",
    r"game[- ]chang(?:er|ing)",
    r"\beffortless(?:ly)?\b",
    r"\bplethora\b",
    r"\bmyriad\b",
)

# American spelling, one per word. An explicit list rather than an "-ise" or
# "-our" pattern, because those catch "precise", "concise", and "four".
BRITISH_SPELLINGS = (
    r"behaviour",
    r"labell(?:ed|ing)",
    r"judgement",
    r"colour",
    r"licence",
    r"defence",
    r"programme",
    r"favour",
    r"honour",
    r"modell(?:ed|ing)",
    r"cancelled",
    r"fulfil\b",
    r"whilst",
    r"amongst",
    # Not "analyses": that is the American plural of "analysis" as often as it
    # is the British verb, and the noun is the one this project writes.
    r"analys(?:e|ed|ing)\b",
    r"organis(?:e|es|ed|ing|ation)",
    r"recognis(?:e|es|ed|ing)",
    r"normalis(?:e|es|ed|ing|ation)",
    r"initialis(?:e|es|ed|ing|ation)",
    r"optimis(?:e|es|ed|ing|ation)",
    r"customis(?:e|es|ed|ing|ation)",
    r"summaris(?:e|es|ed|ing)",
    r"prioritis(?:e|es|ed|ing)",
    r"categoris(?:e|es|ed|ing)",
    r"visualis(?:e|es|ed|ing)",
)

# The verb this project retired. The action is configuring a project for a
# field, and "specialize" made a reader guess at which of four things it meant.
RETIRED_VERB = re.compile(r"specializ|specialis", re.IGNORECASE)

# The X-not-Y contrast. It is a good construction, and it was the whole voice:
# ninety-two uses across the site, thirty-two on one page, so nearly every
# paragraph landed the same way. The cap is on density rather than on the
# phrase, because the phrase is not the problem.
CONTRAST = re.compile(r"\brather than\b|\binstead of\b|\bas opposed to\b", re.IGNORECASE)
WORDS_PER_CONTRAST = 400

# Page types, in the Diataxis sense. `docs/STYLE.md` assigns every page one.
PAGE_TYPES = frozenset({"tutorial", "how-to", "reference", "explanation"})

# The contract a page that teaches a task owes its reader, from the same guide.
INSTRUCTIONAL_TYPES = frozenset({"tutorial", "how-to"})
PREREQUISITE_HEADING = re.compile(r"^##\s+Before you start\s*$", re.MULTILINE)
NEXT_STEPS_HEADING = re.compile(r"^##\s+Next steps\s*$", re.MULTILINE)

FENCE = re.compile(r"^(?P<marker>```+|~~~+)(?P<info>.*)$")


def _body(page: Path) -> str:
    """The page's Markdown with any YAML front matter removed."""
    text = page.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        _, _, rest = text.partition("---\n")
        _, _, body = rest.partition("---\n")
        return body
    return text


def _resolved(page: Path) -> str:
    """The page's body with any `--8<--` include inlined.

    Some repository-level pages are one include line apiece, so the heading a reader
    sees comes from a file at the repository root.
    """
    lines = []
    for line in _body(page).splitlines():
        include = re.fullmatch(r'\s*--8<--\s*"(.+)"\s*', line)
        lines.append(_body(ROOT / include.group(1)) if include else line)
    return "\n".join(lines)


def _front_matter(page: Path) -> dict:
    text = page.read_text(encoding="utf-8")
    found = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    return {} if found is None else (yaml.safe_load(found.group(1)) or {})


def _prose(page: Path) -> str:
    """The page's prose: no front matter, no code, no comments, no URLs.

    A command is not prose. Neither is a link target, which is why the href
    half of a Markdown link is dropped and the text half is kept.
    """
    kept: list[str] = []
    marker: str | None = None
    for line in _body(page).splitlines():
        found = FENCE.match(line)
        if marker is None:
            if found:
                marker = found.group("marker")
                continue
            kept.append(line)
        elif found and found.group("marker").startswith(marker) and not found.group("info").strip():
            marker = None
    text = "\n".join(kept)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "] ", text)
    text = re.sub(r"\b(?:https?|mailto):\S+", " ", text)
    return text


def _site_pages() -> list[Path]:
    return sorted(
        path
        for path in DOCS.rglob("*.md")
        if not any(part in EXCLUDED_DIRS for part in path.relative_to(DOCS).parts)
    )


def _reader_facing() -> list[Path]:
    return [*_site_pages(), *(ROOT / name for name in ROOT_PAGES), ROOT / "domain" / "README.md"]


def _repository_text_files(root: Path = ROOT) -> list[Path]:
    """Every UTF-8 source file, without generated state or private corpora."""
    files = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not path.is_file() or any(
            part in REPOSITORY_SCAN_EXCLUDED_DIRS for part in relative.parts
        ):
            continue
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files.append(path)
    return sorted(files)


def _where(page: Path) -> str:
    return str(page.relative_to(ROOT))


def _nav_labels() -> dict[str, str | None]:
    """Every page in the nav, mapped to the label the sidebar shows for it.

    `None` marks an entry written as a bare path, where MkDocs takes the label
    from the page's own front matter and there is nothing to disagree with.
    """
    # MkDocs config uses Python-specific YAML tags, so load it as plain strings.
    config = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    found: dict[str, str | None] = {}

    def walk(node: object) -> None:
        if isinstance(node, str):
            found.setdefault(node, None)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for label, child in node.items():
                if isinstance(child, str):
                    found[child] = label
                else:
                    walk(child)

    walk(config["nav"])
    return found


def _declared_page_types() -> dict[str, str]:
    """The page-type table out of `docs/STYLE.md`, which is its source of truth.

    Reading the guide rather than repeating it means a page classified there is
    classified here, and the two cannot drift.
    """
    assert STYLE.is_file(), "docs/STYLE.md is the published house style and should exist"
    section = re.search(
        r"^## Every page has one type\s*$(?P<table>.*?)(?=^## )",
        STYLE.read_text(encoding="utf-8"),
        re.DOTALL | re.MULTILINE,
    )
    assert section is not None, "docs/STYLE.md should keep its 'Every page has one type' table"

    rows = re.findall(
        r"^\|\s*`(?P<page>[^`]+)`\s*\|\s*(?P<type>[\w-]+)\s*\|",
        section.group("table"),
        re.MULTILINE,
    )
    assert rows, "the page-type table should assign a type to each page"
    return {page.strip(): kind.strip().casefold() for page, kind in rows}


def _offenders(pattern: re.Pattern[str], pages: list[Path]) -> list[str]:
    return sorted(
        f"{_where(page)}: {found.group(0)!r}"
        for page in pages
        for found in [pattern.search(_prose(page))]
        if found is not None
    )


def test_the_reader_facing_pages_are_discoverable() -> None:
    # Every assertion below passes for free against an empty scan.
    pages = _reader_facing()
    assert len(pages) > 30, f"expected the documentation set, found {len(pages)}"
    assert all(page.is_file() for page in pages), "every listed page should exist"


def test_no_page_uses_a_banned_filler_phrase() -> None:
    """Filler survives review because each instance looks harmless alone."""
    pattern = re.compile("|".join(BANNED_PHRASES), re.IGNORECASE)

    offenders = _offenders(pattern, _reader_facing())

    assert offenders == [], f"docs/STYLE.md bans these phrases: {offenders}"


def test_the_em_dash_guard_reaches_python_source(tmp_path: Path) -> None:
    """The repository rule covers code, comments, and docstrings too."""
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_text('message = "\N{EM DASH}"\n', encoding="utf-8")

    assert source in _repository_text_files(tmp_path)


def test_no_page_uses_an_em_dash() -> None:
    """The repository-wide house rule must cover more than rendered prose."""
    punctuation = "\N{EM DASH}"
    offenders = sorted(
        _where(path)
        for path in _repository_text_files()
        if punctuation in path.read_text(encoding="utf-8")
    )

    assert offenders == [], f"no em dashes anywhere in repository source: {offenders}"


def test_spelling_is_american_throughout() -> None:
    """One spelling per word, so search finds every instance of a term."""
    pattern = re.compile("|".join(BRITISH_SPELLINGS), re.IGNORECASE)
    pages = [*_reader_facing(), ROOT / "AGENTS.md"]

    offenders = _offenders(pattern, pages)

    assert offenders == [], f"American spelling, per docs/STYLE.md: {offenders}"


def test_the_retired_verb_is_gone_from_reader_facing_prose() -> None:
    """ "Specialize" meant configure, adapt, customize, or narrow, and a reader
    had to guess which. It reached `docs/cli.md` through a Typer help string,
    so the fix belongs in `src/` for the generated pages."""
    pages = [*_reader_facing(), ROOT / "AGENTS.md"]

    offenders = _offenders(RETIRED_VERB, pages)

    assert offenders == [], (
        "say what the reader is doing: configure, adapt, customize, or point it "
        f"at your field. Still using the retired verb: {offenders}"
    )


def test_the_contrast_construction_stays_under_its_density_cap() -> None:
    """One mannerism at four times normal density is its own kind of tell.

    The cap is roughly one contrast per 400 words, which is about what
    unremarkable technical prose runs at. Hitting it means the page needs
    variety, not that any single sentence is wrong.
    """
    offenders = []
    for page in _reader_facing():
        prose = _prose(page)
        words = len(prose.split())
        used = len(CONTRAST.findall(prose))
        allowed = max(1, round(words / WORDS_PER_CONTRAST))
        if used > allowed:
            offenders.append(f"{_where(page)}: {used} in {words} words, cap is {allowed}")

    assert offenders == [], (
        "vary the construction, or cut the sentence that exists only to perform "
        f"a contrast: {offenders}"
    )


def test_every_nav_page_is_assigned_a_page_type() -> None:
    """A page that cannot pick one type is a page doing two jobs at once."""
    declared = _declared_page_types()

    unknown = sorted(f"{page}: {kind}" for page, kind in declared.items() if kind not in PAGE_TYPES)
    assert unknown == [], f"a page type should be one of {sorted(PAGE_TYPES)}: {unknown}"

    navigable = {page for page in _nav_labels() if page != HOME}
    missing = sorted(navigable - set(declared))
    stale = sorted(set(declared) - navigable)

    assert missing == [], f"docs/STYLE.md does not classify these nav pages: {missing}"
    assert stale == [], f"docs/STYLE.md classifies pages that are not in the nav: {stale}"


def test_every_nav_page_carries_a_title_and_a_description() -> None:
    """Without `description` the page ships no meta description and no snippet."""
    missing = []
    for page in _nav_labels():
        meta = _front_matter(DOCS / page)
        absent = [field for field in ("title", "description") if not meta.get(field)]
        if absent:
            missing.append(f"{page}: no {' or '.join(absent)}")

    assert missing == [], f"every page needs front matter a search result can use: {missing}"


def test_a_page_has_one_name_in_the_nav_and_in_its_front_matter() -> None:
    """`campaigns.md` was "Discover a corpus", "Run an open-access campaign",
    and "Corpus campaigns" on three surfaces a reader crosses in one session."""
    disagreements = []
    for page, label in _nav_labels().items():
        title = _front_matter(DOCS / page).get("title")
        if label is not None and title != label:
            disagreements.append(f"{page}: nav says {label!r}, front matter says {title!r}")

    assert disagreements == [], f"the nav label is the page's name: {disagreements}"


def test_a_page_heading_matches_its_title() -> None:
    """The heading is the same promise the sidebar made, one click later."""
    disagreements = []
    for page in _nav_labels():
        if page == HOME:
            continue
        title = _front_matter(DOCS / page).get("title")
        heading = re.search(r"^#\s+(.+?)\s*$", _resolved(DOCS / page), re.MULTILINE)
        if heading is None:
            disagreements.append(f"{page}: no level-one heading")
            continue
        expected = TITLE_EXCEPTIONS.get(page, title)
        if heading.group(1) != expected:
            disagreements.append(f"{page}: heading {heading.group(1)!r}, expected {expected!r}")

    assert disagreements == [], (
        f"add a documented entry to TITLE_EXCEPTIONS if the difference is deliberate: {disagreements}"
    )


def test_adr_0012_follows_the_decision_record_contract() -> None:
    """A decision record must explain the choice, its effects, and how to leave it."""
    path = DOCS / "adr" / "0012-modelscope-deepseek-providers.md"
    assert path.is_file(), f"{path.relative_to(ROOT)} should record the provider decision"

    text = path.read_text(encoding="utf-8")
    assert "**Status:** accepted" in text

    headings = [
        heading
        for heading in ("## Context", "## Decision", "## Consequences", "## Reversal conditions")
        if heading in text
    ]
    positions = [text.index(heading) for heading in headings]
    assert headings == [
        "## Context",
        "## Decision",
        "## Consequences",
        "## Reversal conditions",
    ], f"ADR 0012 must use the fixed explanation shape: {headings}"
    assert positions == sorted(positions), "ADR 0012 sections must stay in the documented order"


def test_methodology_headings_use_names_instead_of_outline_numbers() -> None:
    """Visible outline numbers made the retrieval section look like it had seven layers."""
    methodology = (DOCS / "methodology.md").read_text(encoding="utf-8")
    headings = re.findall(r"^#{2,4}\s+(.+?)\s*$", methodology, re.MULTILINE)
    labels = [heading.partition(" {#")[0] for heading in headings]
    numbered = [label for label in labels if re.match(r"\d+(?:\.\d+)*\s", label)]

    assert numbered == [], f"Methodology headings should not expose outline numbers: {numbered}"

    for legacy_fragment in (
        "1-why-this-shape",
        "6-the-five-retrieval-layers",
        "6-3-knowledge-graph-traversal",
        "7-scope-precedes-ranking",
        "9-evaluation-design",
    ):
        assert f"{{#{legacy_fragment}}}" in methodology, (
            f"removing visible numbers must preserve the old #{legacy_fragment} link"
        )


@pytest.mark.parametrize("heading", ["Before you start", "Next steps"])
def test_a_page_that_teaches_a_task_carries_the_tutorial_contract(heading: str) -> None:
    """Say what is needed before the first command, and where to go after the
    last one. Seventeen of nineteen guides did neither."""
    pattern = PREREQUISITE_HEADING if heading == "Before you start" else NEXT_STEPS_HEADING
    instructional = sorted(
        page
        for page, kind in _declared_page_types().items()
        if kind in INSTRUCTIONAL_TYPES and page != HOME
    )
    assert instructional, "docs/STYLE.md should classify some pages as tutorial or how-to"

    missing = [page for page in instructional if not pattern.search(_body(DOCS / page))]

    assert missing == [], f"these pages need a `## {heading}` section: {missing}"
