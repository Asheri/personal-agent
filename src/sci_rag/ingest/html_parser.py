"""HTML into the same block model the markdown route produces.

Scientific material arrives as HTML at least as often as PDF: documentation
pages, preprint landing pages, lab protocols, agency web reports. This makes
`.html` and `.htm` first-class inputs without adding a dependency, using the
standard library's `html.parser`.

The output is deliberately the same `Block` list `parse_markdown` produces, and
tables are rendered as pipe tables rather than kept as HTML. That is not
cosmetic: the chunker's table handling, the `is_table` flag, and everything
downstream already understand that shape, so an HTML table becomes an intact
table chunk with no second code path to keep in step.

Three things a web page has that a document does not, and what happens to them:

* **Chrome.** `nav`, `header`, `footer`, `aside`, `script`, `style`, and
  friends are dropped entirely. Retrieval over a corpus of pages that all share
  a sidebar would otherwise rank the sidebar.
* **A title in two places.** `<h1>` is the document's own title and `<title>`
  is usually the page title plus the site name. The first `<h1>` wins, with
  `<title>` as the fallback, and like the markdown route that first heading
  does not also become a heading block: it is already in every chunk's
  breadcrumb.
* **Whitespace that matters, sometimes.** Text is collapsed to single spaces,
  except inside `<pre>`, where the line structure is the content.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from sci_rag.ingest.parsers import Block, ParsedDocument

#: Dropped with their contents. Page furniture, not the document.
SKIPPED_TAGS: frozenset[str] = frozenset(
    {
        "script",
        "style",
        "noscript",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "svg",
        "template",
        "iframe",
    }
)

#: End a paragraph. Anything that renders as its own block in a browser.
BLOCK_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "li",
        "dd",
        "dt",
        "blockquote",
        "figcaption",
        "br",
        "hr",
    }
)

HEADING_TAGS: frozenset[str] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


class _BlockExtractor(HTMLParser):
    """Walk the document once, emitting blocks in reading order."""

    def __init__(self) -> None:
        # convert_charrefs is on by default, so `&amp;` arrives as `&`.
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.title: str | None = None
        self.page_title: str | None = None

        self._skip_depth = 0
        self._pre_depth = 0
        self._heading: int | None = None
        self._in_title = False

        self._text: list[str] = []
        self._heading_text: list[str] = []

        # Tables are collected whole so they stay one block. A nested table is
        # folded into its parent rather than emitted separately, because
        # splitting it would produce two half-tables neither of which reads.
        self._table_depth = 0
        self._rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] | None = None
        self._header_row = False
        self._first_row_is_header = False

    # -- text collection ---------------------------------------------------

    def _flush_text(self) -> None:
        text = "".join(self._text)
        self._text.clear()
        text = text.strip() if self._pre_depth else " ".join(text.split())
        if text:
            self.blocks.append(Block(kind="text", text=text))

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.page_title = (self.page_title or "") + data
            return
        if self._cell is not None:
            self._cell.append(data)
            return
        if self._heading is not None:
            self._heading_text.append(data)
            return
        self._text.append(data)

    # -- structure ---------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            if tag in SKIPPED_TAGS:
                self._skip_depth += 1
            return
        if tag in SKIPPED_TAGS:
            self._flush_text()
            self._skip_depth = 1
            return

        if tag == "title":
            self._in_title = True
            return
        if tag == "pre":
            self._flush_text()
            self._pre_depth += 1
            return
        if tag == "table":
            self._flush_text()
            self._table_depth += 1
            return
        if self._table_depth:
            self._start_table_tag(tag)
            return
        if tag in HEADING_TAGS:
            self._flush_text()
            self._heading = int(tag[1])
            self._heading_text.clear()
            return
        if tag in BLOCK_TAGS:
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag in SKIPPED_TAGS:
                self._skip_depth -= 1
            return

        if tag == "title":
            self._in_title = False
            return
        if tag == "pre":
            self._flush_text()
            self._pre_depth = max(0, self._pre_depth - 1)
            return
        if tag == "table":
            self._end_table()
            return
        if self._table_depth:
            self._end_table_tag(tag)
            return
        if tag in HEADING_TAGS and self._heading is not None:
            self._end_heading()
            return
        if tag in BLOCK_TAGS:
            self._flush_text()

    def _end_heading(self) -> None:
        text = " ".join("".join(self._heading_text).split())
        level = self._heading or 1
        self._heading = None
        self._heading_text.clear()
        if not text:
            return
        if self.title is None and level == 1:
            # The document's own title. Same rule as the markdown route: it is
            # already in every chunk's breadcrumb, so emitting it as a heading
            # too would double it in the section path.
            self.title = text
            return
        self.blocks.append(Block(kind="heading", text=text, level=level))

    # -- tables ------------------------------------------------------------

    def _start_table_tag(self, tag: str) -> None:
        if tag == "tr":
            self._row = []
            self._header_row = False
        elif tag in ("td", "th"):
            self._cell = []
            if tag == "th":
                self._header_row = True

    def _end_table_tag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            # A pipe inside a cell would forge a column boundary.
            self._row.append(" ".join("".join(self._cell).split()).replace("|", "\\|"))
            self._cell = None
        elif tag == "tr":
            if self._row:
                if not self._rows and self._header_row:
                    self._first_row_is_header = True
                self._rows.append(self._row)
            self._row = []

    def _end_table(self) -> None:
        self._table_depth = max(0, self._table_depth - 1)
        if self._table_depth:
            # Still inside an outer table; its cells keep collecting.
            return
        rendered = render_pipe_table(self._rows, header=self._first_row_is_header)
        if rendered:
            self.blocks.append(Block(kind="table", text=rendered))
        self._rows = []
        self._row = []
        self._cell = None
        self._first_row_is_header = False

    def close(self) -> None:
        super().close()
        self._flush_text()


def render_pipe_table(rows: list[list[str]], *, header: bool) -> str:
    """Render collected cells as a Markdown pipe table.

    The chunker already keeps pipe tables intact and flags them `is_table`, so
    matching that shape means an HTML table travels the same path a Markdown
    one does instead of needing its own handling.
    """
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(row) + " |" for row in padded]
    if header and len(lines) > 1:
        lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def parse_html(text: str, *, fallback_title: str) -> ParsedDocument:
    """Segment an HTML document into heading, table, and text blocks."""
    extractor = _BlockExtractor()
    extractor.feed(text)
    extractor.close()

    title = extractor.title or _clean_page_title(extractor.page_title) or fallback_title
    blocks = [block for block in extractor.blocks if block.text]
    return ParsedDocument(title=title, blocks=blocks, metadata={"parser": "html"})


def _clean_page_title(raw: str | None) -> str | None:
    """`<title>` is usually "Document name | Site name"; keep the document part."""
    if not raw:
        return None
    title = " ".join(raw.split())
    # \u2013 is an en dash, a common separator on the web. Written escaped
    # because ruff's ambiguous-character rule rejects the literal.
    for separator in (" | ", " - ", " \u2013 ", " :: "):
        if separator in title:
            title = title.split(separator)[0].strip()
            break
    return title or None


def parse_html_file(path: Path) -> ParsedDocument:
    return parse_html(path.read_text(encoding="utf-8", errors="replace"), fallback_title=path.stem)


__all__ = [
    "BLOCK_TAGS",
    "HEADING_TAGS",
    "SKIPPED_TAGS",
    "parse_html",
    "parse_html_file",
    "render_pipe_table",
]
