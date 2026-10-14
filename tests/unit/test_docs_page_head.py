"""Guards for the block at the top of every documentation page.

Every page opens with the same three things in the same order: a clickable
breadcrumb trail, the page title, and a one-line grey lede. The trail and the
title start at the same height on every page, which is what these tests hold.
The lede sits wherever the title leaves it: a two-line title pushes it down,
and reserving the space to prevent that cost more in dead air under the short
titles than the alignment was worth.

The trail says where the page sits. It names every level of nesting the left
sidebar shows and ends on the page you are reading, so `campaigns.md` reads
`Guides > Discover a corpus` rather than the bare `Guides` the theme stops at.
Section hub pages are the exception: `project.md` is the page the `About`
crumb already points at, so its only crumb would repeat the title directly
below it. Those pages keep the empty row, which is what holds the height, and
carry no crumbs.

The source-level tests pin the inputs (the theme feature, the template
override, the stylesheet, and the Markdown shape of each page). The build tests
at the end pin the output, by rendering the real site and reading the trail
MkDocs actually emitted.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MKDOCS = ROOT / "mkdocs.yml"
DOCS = ROOT / "docs"
PATH_PARTIAL = DOCS / "overrides" / "partials" / "path.html"
COMPONENTS_CSS = DOCS / "stylesheets" / "components.css"

# The landing page draws its own masthead and deliberately has no breadcrumb.
HOME = "index.md"
INTERNAL_WORKSPACES = ("aegis/", "full-stack-development/", "superpowers/")

# The theme error page has no place in the nav, and the override templates are
# copied into the build verbatim because custom_dir sits inside docs_dir.
NOT_PAGES = ("404.html", "overrides/")


def _config() -> dict:
    # MkDocs config uses Python-specific YAML tags, so load it as plain strings.
    return yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _nav_pages(nav: object, ancestors: tuple[str, ...] = ()) -> list[tuple[str, tuple[str, ...]]]:
    """Flatten the configured nav into (page path, section titles above it)."""
    return [(path, ancestors_) for path, ancestors_, _, _ in _nav_entries(nav, ancestors)]


def _nav_entries(
    nav: object,
    ancestors: tuple[str, ...] = (),
    position: int | None = None,
) -> list[tuple[str, tuple[str, ...], str | None, bool]]:
    """Flatten the nav into (path, section titles, configured title, is first here).

    "Is first here" marks the opening entry of a section, which is the page its
    section link resolves to and therefore the hub-page candidate.
    """
    found: list[tuple[str, tuple[str, ...], str | None, bool]] = []
    if isinstance(nav, str):
        found.append((nav, ancestors, None, position == 0))
    elif isinstance(nav, list):
        for index, entry in enumerate(nav):
            found.extend(_nav_entries(entry, ancestors, index))
    elif isinstance(nav, dict):
        for title, child in nav.items():
            if isinstance(child, str):
                found.append((child, ancestors, title, position == 0))
            else:
                found.extend(_nav_entries(child, (*ancestors, title)))
    return found


def _title(path: str, configured: str | None) -> str:
    """Resolve a page's title the way MkDocs does: nav, then meta, then heading."""
    if configured:
        return configured
    text = (DOCS / path).read_text(encoding="utf-8")
    front_matter = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if front_matter:
        meta = yaml.safe_load(front_matter.group(1)) or {}
        if meta.get("title"):
            return str(meta["title"])
    heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    assert heading is not None, f"{path} has no title to put in its breadcrumb"
    return heading.group(1).strip()


def _expected_trail(ancestors: tuple[str, ...], title: str, first: bool) -> list[str]:
    """The crumbs a page should carry, outermost section first.

    A hub page opens its section and carries its section's name, so the section
    crumb and the page crumb would say the same word twice and link to the same
    place. Drop both and leave the row empty.
    """
    if first and ancestors and title == ancestors[-1]:
        return list(ancestors[:-1])
    return [*ancestors, title]


def _body(page: Path) -> str:
    """Return the page's Markdown with any YAML front matter stripped."""
    text = page.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        _, _, rest = text.partition("---\n")
        _, _, body = rest.partition("---\n")
        return body
    return text


def _resolve_snippets(body: str) -> str:
    """Inline pymdownx snippet includes so the shared root files are checked too."""
    lines = []
    for line in body.splitlines():
        include = re.fullmatch(r'\s*--8<--\s*"(.+)"\s*', line)
        lines.append(_body(ROOT / include.group(1)) if include else line)
    return "\n".join(lines)


def test_breadcrumbs_are_enabled_in_the_theme() -> None:
    features = _config()["theme"]["features"]

    assert "navigation.path" in features, "breadcrumbs are the navigation.path feature"


def test_internal_workspace_exclusions_match_mkdocs() -> None:
    configured = set(_config()["exclude_docs"].splitlines())
    expected = {"planning/", *INTERNAL_WORKSPACES}

    assert configured & expected == expected


def test_the_breadcrumb_override_replaces_the_stock_trail() -> None:
    """The stock partial hides the trail unless a page is two sections deep."""
    assert PATH_PARTIAL.is_file(), "docs/overrides/partials/path.html should override the theme"
    partial = PATH_PARTIAL.read_text(encoding="utf-8")

    assert "depth > 1" not in partial, "the stock depth gate leaves most pages without a trail"
    assert "md-path__list" in partial, "the override should keep the theme's markup contract"
    assert 'aria-current="page"' in partial, "the trail should mark the page you are on"


def test_every_navigable_page_has_a_section_above_it() -> None:
    """A page with no ancestor section has nothing to put in its breadcrumb."""
    pages = _nav_pages(_config()["nav"])
    assert pages, "the nav should be discoverable"

    orphans = sorted(page for page, ancestors in pages if not ancestors)

    assert orphans == [], f"these nav pages would render an empty breadcrumb: {orphans}"


# Anything that opens a block other than a paragraph: a heading, an admonition
# or collapsible, a list, a table, a fence, a quote, a tab, or raw HTML. Bold
# lead-ins such as the decision records' "**Status:**" are paragraphs, so the
# list markers have to be the spaced form rather than a bare asterisk.
NOT_A_PARAGRAPH = re.compile(r"(#|!!!|\?\?\?|[-*+]\s|\d+\.\s|\||```|>|<|===\s)")


def test_every_page_opens_with_a_title_and_a_lede_paragraph() -> None:
    """The grey lede is styled as p:first-of-type, so it has to come first."""
    pages = sorted(DOCS.rglob("*.md"))
    assert pages, "documentation sources should be discoverable"

    offenders = []
    for page in pages:
        relative = page.relative_to(DOCS).as_posix()
        if relative == HOME or relative.startswith(("planning/", "assets/", *INTERNAL_WORKSPACES)):
            continue
        blocks = [
            block.strip()
            for block in re.split(r"\n\s*\n", _resolve_snippets(_body(page)))
            # Comments render to nothing, so they do not move the visible lede.
            if block.strip() and not block.strip().startswith("<!--")
        ]
        opening = blocks[:2]
        if len(opening) < 2 or not opening[0].startswith("# ") or NOT_A_PARAGRAPH.match(opening[1]):
            offenders.append(relative)

    assert offenders == [], f"these pages do not open with a title then a lede: {offenders}"


def test_the_breadcrumb_row_is_pinned_to_the_content_column() -> None:
    """Without a fixed height the title below the trail drifts between pages."""
    rules = COMPONENTS_CSS.read_text(encoding="utf-8")
    block = re.search(r"^\.md-path\s*\{(.+?)\}", rules, re.DOTALL | re.MULTILINE)

    assert block is not None, "components.css should style .md-path"
    declarations = block.group(1)
    assert "height:" in declarations, "the row needs a fixed height so the title cannot drift"
    assert "max-width:" in declarations, "the row should share the article column's measure"
    assert "margin-inline:" in declarations, "the row should be centred like the article is"
    # Below this breakpoint the theme centres the article; above it the article
    # is anchored beside the docked sidebar, and the trail has to follow or it
    # ends up centred over a left-anchored title.
    assert re.search(
        r"@media[^{]*76\.25em[^{]*\{[^}]*md-sidebar--primary[^}]*\.md-path\s*\{[^}]*"
        r"margin-inline-start:",
        rules,
        re.DOTALL,
    ), "the row needs the theme's docked-sidebar inset too"


# The row is either the trail itself or, on a hub page, the bare spacer that
# keeps the title from riding up. Both carry the class the stylesheet sizes.
ROW = re.compile(r'<(nav|div) class="md-path"[^>]*>(?P<body>.*?)</\1>', re.DOTALL)
CRUMB = re.compile(r'<li class="md-path__item">(?P<body>.*?)</li>', re.DOTALL)
LINK = re.compile(
    r'<a\s+href="(?P<href>[^"]*)"(?P<attrs>[^>]*)>\s*<span class="md-ellipsis">\s*'
    r"(?P<text>.*?)\s*</span>",
    re.DOTALL,
)


@pytest.fixture(scope="module")
def built_site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Render the real site once, so the assertions below read the same build."""
    pytest.importorskip("mkdocs", reason="the docs dependency group is not installed")
    from mkdocs.commands.build import build
    from mkdocs.config import load_config

    out = tmp_path_factory.mktemp("site")
    build(load_config(str(MKDOCS), site_dir=str(out), site_url=""))
    assert sorted(out.rglob("*.html")), "the build should emit pages"
    yield out


def _row(site: Path, page: str) -> str:
    """The rendered breadcrumb row for a built page, or the empty string."""
    html = (site / page).read_text(encoding="utf-8")
    found = ROW.search(html)
    return found.group("body") if found else ""


def _crumbs(site: Path, page: str) -> list[dict[str, Any]]:
    """The rendered crumbs for a built page, outermost first."""
    crumbs = []
    for item in CRUMB.finditer(_row(site, page)):
        link = LINK.search(item.group("body"))
        assert link is not None, f"{page} has a crumb that is not a link: {item.group('body')!r}"
        crumbs.append(
            {
                "text": link.group("text").strip(),
                "href": link.group("href"),
                "current": 'aria-current="page"' in link.group("attrs"),
            }
        )
    return crumbs


def _built_path(source: str) -> str:
    """The built page for a nav source path, under directory URLs."""
    return re.sub(r"\.md$", "/index.html", source)


def test_every_built_page_keeps_the_breadcrumb_row(built_site: Path) -> None:
    """The row holds the title at one height, so it is on the page even when empty."""
    missing = []
    for page in sorted(built_site.rglob("*.html")):
        relative = page.relative_to(built_site).as_posix()
        if relative == "index.html" or relative.startswith(NOT_PAGES):
            continue
        if relative.startswith(INTERNAL_WORKSPACES):
            continue
        html = page.read_text(encoding="utf-8")
        if 'http-equiv="refresh"' in html:
            # A retired address forwarding to its new home; see
            # scripts/docs_redirects.py. Not a documentation page.
            continue
        if 'class="md-path"' not in html:
            missing.append(relative)

    assert missing == [], f"these built pages have no breadcrumb row: {missing}"


def test_the_trail_names_every_level_of_nesting_down_to_the_page(built_site: Path) -> None:
    """The trail should read like the sidebar path to the page, not stop above it."""
    entries = _nav_entries(_config()["nav"])
    assert entries, "the nav should be discoverable"

    wrong = {}
    for source, ancestors, configured, first in entries:
        if source == HOME:
            continue
        expected = _expected_trail(ancestors, _title(source, configured), first)
        rendered = [crumb["text"] for crumb in _crumbs(built_site, _built_path(source))]
        if rendered != expected:
            wrong[source] = f"rendered {rendered}, expected {expected}"

    assert wrong == {}, f"these breadcrumb trails do not match the nav: {wrong}"


def test_a_section_hub_page_carries_no_crumbs(built_site: Path) -> None:
    """Its one crumb would be its own title, linking to the page you are on."""
    entries = _nav_entries(_config()["nav"])
    hubs = [
        source
        for source, ancestors, configured, first in entries
        if first and ancestors and _title(source, configured) == ancestors[-1]
    ]
    assert len(hubs) == 5, f"expected one hub page per top-level tab, found {hubs}"

    populated = {
        source: [crumb["text"] for crumb in _crumbs(built_site, _built_path(source))]
        for source in hubs
        if _crumbs(built_site, _built_path(source))
    }

    assert populated == {}, f"these hub pages repeat their own title in the trail: {populated}"


def test_every_crumb_is_a_link_and_only_the_last_is_the_page_you_are_on(
    built_site: Path,
) -> None:
    """Ancestors navigate; the final crumb is where you already are."""
    entries = _nav_entries(_config()["nav"])
    trails = {
        source: _crumbs(built_site, _built_path(source))
        for source, _, _, _ in entries
        if source != HOME and _crumbs(built_site, _built_path(source))
    }
    expected = {
        source
        for source, ancestors, configured, first in entries
        if source != HOME and _expected_trail(ancestors, _title(source, configured), first)
    }
    assert set(trails) == expected, "every page below a hub should carry a breadcrumb trail"

    offenders = {}
    for source, crumbs in trails.items():
        marked = [index for index, crumb in enumerate(crumbs) if crumb["current"]]
        if marked != [len(crumbs) - 1]:
            offenders[source] = f"aria-current is on crumbs {marked} of {len(crumbs)}"
        elif not all(crumb["href"] for crumb in crumbs):
            offenders[source] = "a crumb has no href"

    assert offenders == {}, f"these trails are not marked correctly: {offenders}"
