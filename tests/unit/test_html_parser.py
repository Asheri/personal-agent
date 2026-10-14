"""HTML into blocks, offline and with no network.

Most of these are about what a web page has that a document does not. Page
chrome is the one that matters most: ingest a corpus of pages that all share a
sidebar and, without stripping it, the sidebar becomes the most repeated text
in the corpus and retrieval starts ranking it. The table tests are the other
half, because a table that arrives as separate cells is a table nobody can
read back out of a chunk.
"""

from __future__ import annotations

from pathlib import Path

from sci_rag.ingest.html_parser import parse_html, parse_html_file, render_pipe_table
from sci_rag.ingest.parsers import SUPPORTED_SUFFIXES, parse_file

PAGE = """<!DOCTYPE html>
<html><head>
<title>Rice Straw Handling | Demo Region Bioenergy Lab</title>
<style>body { color: red; }</style>
<script>var tracking = 1;</script>
</head>
<body>
<nav><ul><li><a href="/">Home</a></li></ul></nav>
<header><span>Site banner</span></header>
<main>
<h1>Rice Straw Handling</h1>
<p>Rice straw availability is near 310,000 tons per year.</p>
<h2>Composition</h2>
<p>Ash content is near 18 percent.</p>
<table>
  <tr><th>Property</th><th>Value</th></tr>
  <tr><td>Ash content</td><td>18 percent</td></tr>
</table>
<h3>Pretreatment</h3>
<p>A mild alkali soak raises the yield &amp; lowers the lignin.</p>
</main>
<aside>Related pages</aside>
<footer>Copyright 2026</footer>
</body></html>
"""


def _parsed():  # type: ignore[no-untyped-def]
    return parse_html(PAGE, fallback_title="fallback")


def _texts(document) -> list[str]:  # type: ignore[no-untyped-def]
    return [block.text for block in document.blocks]


# --- registration ------------------------------------------------------------


def test_html_extensions_are_supported_inputs() -> None:
    """`discover_folder` and the manifest linter both read this set."""
    assert {".html", ".htm"} <= SUPPORTED_SUFFIXES


def test_parse_file_routes_html_to_this_parser(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(PAGE, encoding="utf-8")

    document = parse_file(path)

    assert document.metadata["parser"] == "html"
    assert document.title == "Rice Straw Handling"


def test_the_htm_spelling_works_too(tmp_path: Path) -> None:
    path = tmp_path / "page.htm"
    path.write_text("<h1>Old School</h1><p>Body.</p>", encoding="utf-8")

    assert parse_file(path).title == "Old School"


# --- chrome ------------------------------------------------------------------


def test_page_chrome_is_dropped_entirely() -> None:
    """A shared sidebar would otherwise be the most repeated text in a corpus."""
    body = " ".join(_texts(_parsed()))

    for chrome in ("Home", "Site banner", "Related pages", "Copyright 2026"):
        assert chrome not in body, f"{chrome!r} is page furniture, not document text"


def test_script_and_style_contents_never_reach_the_text() -> None:
    body = " ".join(_texts(_parsed()))

    assert "tracking" not in body
    assert "color: red" not in body


def test_nesting_inside_a_skipped_element_does_not_end_the_skip_early() -> None:
    """A `<nav>` containing a `<header>` must not resume on the inner close tag."""
    document = parse_html(
        "<nav><header>chrome</header>more chrome</nav><p>real body</p>",
        fallback_title="t",
    )

    assert _texts(document) == ["real body"]


# --- titles ------------------------------------------------------------------


def test_the_first_h1_is_the_title_and_not_also_a_heading_block() -> None:
    """Same rule as markdown: it is already in every chunk's breadcrumb."""
    document = _parsed()

    assert document.title == "Rice Straw Handling"
    assert "Rice Straw Handling" not in _texts(document)


def test_a_second_h1_stays_a_heading() -> None:
    document = parse_html("<h1>First</h1><h1>Second</h1>", fallback_title="t")

    assert document.title == "First"
    assert [(b.kind, b.text, b.level) for b in document.blocks] == [("heading", "Second", 1)]


def test_the_page_title_is_the_fallback_with_the_site_name_stripped() -> None:
    document = parse_html(
        "<title>Protocol A | Some Lab</title><p>Body.</p>", fallback_title="unused"
    )

    assert document.title == "Protocol A"


def test_the_filename_is_the_last_resort(tmp_path: Path) -> None:
    path = tmp_path / "orphan.html"
    path.write_text("<p>No title anywhere.</p>", encoding="utf-8")

    assert parse_html_file(path).title == "orphan"


# --- headings ----------------------------------------------------------------


def test_headings_keep_their_level_for_the_section_path() -> None:
    levels = [(b.text, b.level) for b in _parsed().blocks if b.kind == "heading"]

    assert levels == [("Composition", 2), ("Pretreatment", 3)]


def test_markup_inside_a_heading_is_flattened() -> None:
    document = parse_html("<h2>Ash <em>content</em> matters</h2>", fallback_title="t")

    assert [b.text for b in document.blocks] == ["Ash content matters"]


def test_an_empty_heading_is_not_emitted() -> None:
    document = parse_html("<h2></h2><h2>  </h2><p>Body.</p>", fallback_title="t")

    assert [b.kind for b in document.blocks] == ["text"]


# --- tables ------------------------------------------------------------------


def test_a_table_becomes_one_intact_block() -> None:
    """Split into cells it would be unreadable; the chunker keeps a table whole."""
    tables = [b for b in _parsed().blocks if b.kind == "table"]

    assert len(tables) == 1
    assert tables[0].text == "| Property | Value |\n| --- | --- |\n| Ash content | 18 percent |"


def test_a_header_row_gets_a_separator_and_a_body_only_table_does_not() -> None:
    with_header = parse_html(
        "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>", fallback_title="t"
    )
    without = parse_html(
        "<table><tr><td>1</td></tr><tr><td>2</td></tr></table>", fallback_title="t"
    )

    assert with_header.blocks[0].text == "| A |\n| --- |\n| 1 |"
    assert without.blocks[0].text == "| 1 |\n| 2 |"


def test_ragged_rows_are_padded_so_the_table_stays_rectangular() -> None:
    document = parse_html(
        "<table><tr><td>a</td><td>b</td><td>c</td></tr><tr><td>1</td></tr></table>",
        fallback_title="t",
    )

    assert document.blocks[0].text == "| a | b | c |\n| 1 |  |  |"


def test_a_pipe_inside_a_cell_is_escaped_rather_than_forging_a_column() -> None:
    document = parse_html("<table><tr><td>a|b</td><td>c</td></tr></table>", fallback_title="t")

    assert document.blocks[0].text == r"| a\|b | c |"


def test_a_nested_table_folds_into_its_parent_rather_than_splitting_it() -> None:
    """Two half-tables would be worse than one merged one."""
    document = parse_html(
        "<table><tr><td>outer</td><td><table><tr><td>inner</td></tr></table></td></tr></table>",
        fallback_title="t",
    )

    tables = [b for b in document.blocks if b.kind == "table"]
    assert len(tables) == 1


def test_an_empty_table_produces_no_block() -> None:
    document = parse_html("<table></table><p>Body.</p>", fallback_title="t")

    assert [b.kind for b in document.blocks] == ["text"]


def test_render_pipe_table_drops_rows_that_are_entirely_blank() -> None:
    assert render_pipe_table([["a"], ["", " "], ["b"]], header=False) == "| a |\n| b |"


def test_render_pipe_table_on_nothing_is_empty_rather_than_a_stub() -> None:
    assert render_pipe_table([], header=True) == ""


# --- text --------------------------------------------------------------------


def test_entities_are_decoded() -> None:
    body = " ".join(_texts(_parsed()))

    assert "yield & lowers" in body
    assert "&amp;" not in body


def test_block_elements_separate_paragraphs() -> None:
    document = parse_html("<p>One.</p><p>Two.</p><li>Three.</li>", fallback_title="t")

    assert _texts(document) == ["One.", "Two.", "Three."]


def test_inline_markup_does_not_split_a_sentence() -> None:
    document = parse_html("<p>Ash is <strong>18</strong> percent.</p>", fallback_title="t")

    assert _texts(document) == ["Ash is 18 percent."]


def test_whitespace_is_collapsed_outside_pre() -> None:
    document = parse_html("<p>a\n\n   b\t\tc</p>", fallback_title="t")

    assert _texts(document) == ["a b c"]


def test_pre_keeps_its_line_structure() -> None:
    """Inside `<pre>` the line breaks are the content."""
    document = parse_html("<pre>step 1: soak\nstep 2: rinse</pre>", fallback_title="t")

    assert _texts(document) == ["step 1: soak\nstep 2: rinse"]


def test_a_document_with_no_body_text_produces_no_blocks() -> None:
    document = parse_html(
        "<html><head><title>T</title></head><body></body></html>", fallback_title="t"
    )

    assert document.blocks == []
    assert document.title == "T"


def test_unclosed_tags_do_not_lose_the_text_after_them() -> None:
    """Real pages are not well-formed, and losing content silently is the worst outcome."""
    document = parse_html("<p>First<p>Second<div>Third", fallback_title="t")

    assert _texts(document) == ["First", "Second", "Third"]
