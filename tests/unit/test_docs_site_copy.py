"""Guards for the documentation site's front-door copy and presentation.

The site description is written in three places that a reader compares directly:
the MkDocs metadata, the landing page heading, and the README lead. They drift
apart easily because nothing else links them. The next two tests widen that to
every surface the product ships a description through, because the site is not
where most people meet it: the PyPI page, `sci-rag --help`, the served OpenAPI
document, and the BibTeX a paper would carry all say what this is, and until
they were tied together only the MkDocs field was guarded. The rest keep the
retired marketing components from being reintroduced by copy-paste, keep the
suggested citation pinned to a version that exists, and keep the product's
display name spelled the way the logo spells it.
"""

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MKDOCS = ROOT / "mkdocs.yml"
INDEX = ROOT / "docs" / "index.md"
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
CITATION = ROOT / "docs" / "project.md"

RETIRED_CLASSES = (
    "srag-card",
    "srag-kicker",
    "srag-badge",
    "srag-button",
    "srag-capability",
    "srag-pathway-grid",
    "srag-principle-grid",
    "srag-home-cta",
)


def _normalize(text: str) -> str:
    """Collapse wrapping and punctuation so prose can be compared as one line."""
    return re.sub(r"\s+", " ", text).strip().rstrip(".").casefold()


def _site_description() -> str:
    # MkDocs config uses Python-specific YAML tags, so load it as plain strings.
    config = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return str(config["site_description"])


def _bibtex_field(name: str) -> str | None:
    """Read one field out of the suggested citation, which wraps across lines."""
    match = re.search(
        rf"\b{name}\s*=\s*\{{(.*?)\}}",
        CITATION.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    return None if match is None else match.group(1)


# The phrase the project retired. `site_description` has been guarded against it
# since the description was rewritten, but the guard stopped at that one field.
# "for a scientific domain" is the same framing without the noun, so the pattern
# stops at "DIY GraphRAG" rather than at the full tagline.
RETIRED_TAGLINE = re.compile(r"DIY\s+GraphRAG", re.IGNORECASE)


def _described_surfaces() -> list[Path]:
    """Every tracked file that describes the product to somebody.

    `docs/planning/` is excluded: `exclude_docs` keeps it off the site, it is a
    historical record of how the project got here, and rewriting history is a
    different thing from retiring a tagline.
    """
    return [
        PYPROJECT,
        MKDOCS,
        *sorted(ROOT.joinpath("src").rglob("*.py")),
        *sorted(
            path
            for path in ROOT.joinpath("docs").rglob("*.md")
            if "planning" not in path.relative_to(ROOT).parts
        ),
        *sorted(ROOT.glob("*.md")),
    ]


def test_site_description_is_the_same_sentence_in_all_three_entry_points() -> None:
    description = _normalize(_site_description())

    assert "graphrag factory" not in description, "the description should be plain and technical"

    index_h1 = re.search(
        r"^#\s+(.+?)\s*(\{.*\})?$", INDEX.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert index_h1 is not None, "docs/index.md needs a level-one heading"
    assert _normalize(index_h1.group(1)) == description

    assert description in _normalize(README.read_text(encoding="utf-8"))


def test_the_retired_tagline_is_gone_from_every_surface_a_reader_meets() -> None:
    """One guarded field is not the same as a retired phrase."""
    surfaces = _described_surfaces()
    assert len(surfaces) > 100, f"expected the tracked tree, scanned {len(surfaces)}"

    offenders = sorted(
        f"{path.relative_to(ROOT)}: {match.group(0)!r}"
        for path in surfaces
        for match in [RETIRED_TAGLINE.search(path.read_text(encoding="utf-8"))]
        if match is not None
    )

    assert not offenders, f"the retired tagline is still published in: {offenders}"


def test_the_product_description_is_the_same_sentence_wherever_it_ships() -> None:
    """The site is not where most people meet the product; these places are."""
    import sci_rag
    from sci_rag.cli.main import app as cli_app
    from sci_rag.server.app import API_DESCRIPTION

    description = _normalize(_site_description())
    bibtex_title = _bibtex_field("title")
    assert bibtex_title is not None, "the About page should suggest a BibTeX title"

    surfaces = {
        "pyproject.toml, which PyPI renders": tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))[
            "project"
        ]["description"],
        "the sci_rag module docstring": sci_rag.__doc__ or "",
        "sci-rag --help": cli_app.info.help or "",
        "the served OpenAPI description": API_DESCRIPTION,
        "the suggested BibTeX title": bibtex_title,
    }

    offenders = sorted(
        name for name, text in surfaces.items() if description not in _normalize(text)
    )

    assert not offenders, f"these describe the product differently: {offenders}"


def test_the_suggested_citation_pins_a_version_that_exists() -> None:
    """v0.2.0's BibTeX outlived v0.2.0.

    A citation pinned to a version that is not the current one is worse than no
    version at all, because a reader has no way to tell it is stale. Tying it to
    `pyproject.toml` makes the release that changes one change the other.
    """
    cited = _bibtex_field("version")
    if cited is None:
        return  # The page may drop the field and rely on its commit-pinning advice.

    released = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]

    assert cited.strip() == released, (
        f"the About page suggests version {cited.strip()}; pyproject.toml is {released}"
    )


def test_retired_marketing_components_are_not_reintroduced() -> None:
    pages = sorted(ROOT.joinpath("docs").rglob("*.md"))
    stylesheets = sorted(ROOT.joinpath("docs", "stylesheets").glob("*.css"))
    assert pages and stylesheets, "documentation sources should be discoverable"

    offenders = {
        f"{path.relative_to(ROOT)}: {name}"
        for path in pages + stylesheets
        for name in RETIRED_CLASSES
        if name in path.read_text(encoding="utf-8")
    }

    assert not offenders, f"retired components still referenced: {sorted(offenders)}"


# Python-Markdown's attr_list only binds `{ .class }` when it sits on the same
# line as the construct. An 80-column wrap that splits `](page.md){ .srag-row }`
# prints the marker as prose, which is what leaked onto the homepage.
_SPLIT_ATTR_LIST = re.compile(r"\)\{\s*$")
_ORPHAN_ATTR_LIST = re.compile(r"^\{?\s*\.[A-Za-z][\w-]*\s*\}$")


def test_attr_list_markers_stay_on_the_same_line_as_the_link() -> None:
    """A wrapped `{ .srag-row }` is not a class. It is visible junk."""
    offenders: list[str] = []
    for page in sorted(ROOT.joinpath("docs").rglob("*.md")):
        if "planning" in page.relative_to(ROOT).parts:
            continue
        in_fence = False
        previous = ""
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                previous = line
                continue
            if in_fence:
                previous = line
                continue
            if _SPLIT_ATTR_LIST.search(line.rstrip()) or (
                _ORPHAN_ATTR_LIST.match(stripped) and previous.rstrip().endswith("{")
            ):
                offenders.append(f"{page.relative_to(ROOT)}:{number}")
            previous = line

    assert not offenders, (
        "keep `{{ .class }}` on the same line as the link; wrapping it prints "
        f"the marker as text: {offenders}"
    )


def test_homepage_rows_never_link_through_a_raw_html_href() -> None:
    """A raw `<a href>` is not rewritten, and it is not checked either.

    Writing the rows as HTML to dodge a wrapped attr_list marker traded one
    silent defect for two. MkDocs rewrites `.md` only inside a Markdown link,
    so `href="quickstart.md"` ships a 404; and the offline link check reads the
    Markdown source, so `href="quickstart/"` is a path that does not exist
    there. Only a Markdown link satisfies both, which is how the other five hub
    pages have always written them. The wrap that started this is caught by
    `test_attr_list_markers_stay_on_the_same_line_as_the_link` above, site-wide.
    """
    offenders = re.findall(r'<a[^>]*class="srag-row"[^>]*>', INDEX.read_text(encoding="utf-8"))

    assert offenders == [], (
        f"write homepage rows as one-line Markdown links, not raw HTML: {offenders}"
    )


# The display name has no hyphen, because the logo wordmark has none. The slug
# keeps its hyphens everywhere it is an identifier: the repository, the package,
# the CLI, image tags, and URLs. Only the human-readable name is spelled this way.
HYPHENATED_DISPLAY_NAME = re.compile(r"Sci-RAG\s+Kit")


def test_display_name_is_unhyphenated_in_every_reader_facing_surface() -> None:
    surfaces = [
        *sorted(ROOT.joinpath("docs").rglob("*.md")),
        *sorted(ROOT.glob("*.md")),
        MKDOCS,
    ]
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in surfaces
        if HYPHENATED_DISPLAY_NAME.search(path.read_text(encoding="utf-8"))
    )

    assert not offenders, (
        f"the display name is 'Sci RAG Kit', without a hyphen; still hyphenated in: {offenders}"
    )


def test_reader_facing_docs_name_the_actual_extension_point() -> None:
    """The word "seam" hides whether text means an interface, boundary, or extension point."""
    offenders = []
    surfaces = [
        *sorted(
            path
            for path in (ROOT / "docs").rglob("*.md")
            if "planning" not in path.relative_to(ROOT).parts
        ),
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "CHANGELOG.md",
    ]
    for path in surfaces:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"\bseams?\b", line, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")

    assert offenders == [], f"replace 'seam' with the concrete technical term: {offenders}"


def test_about_replaces_the_project_section_and_keeps_internal_pages_unlisted() -> None:
    config = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    navigation = str(config["nav"])
    unlisted = str(config["not_in_nav"])
    project = (ROOT / "docs" / "project.md").read_text(encoding="utf-8")

    assert "{'Home': ['index.md']}" in navigation
    assert "Getting started" in navigation
    assert "Get started" not in navigation
    assert "Project" not in navigation
    assert "About" in navigation
    assert "Decision records" not in navigation
    assert "adr/*.md" in unlisted, "ADRs should remain linkable without occupying public navigation"
    for page in (
        "ROADMAP.md",
        "VERSIONING.md",
        "GOVERNANCE.md",
        "adopters.md",
        "contributing.md",
        "STYLE.md",
        "changelog.md",
    ):
        assert page in unlisted, f"{page} should remain available without appearing in navigation"

    assert "# About" in project
    assert "Lawrence Berkeley National Laboratory" in project
    assert "## How to cite" in project
    for removed_section in ("Design principles", "Roadmap", "Governance", "Decision records"):
        assert removed_section not in project


def test_reference_hub_does_not_label_prose_as_generated() -> None:
    reference = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")

    assert "Generated.</span>" not in reference
