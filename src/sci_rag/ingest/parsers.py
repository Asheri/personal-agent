"""Turn source files into a common shape the chunker understands.

Three routes, one output type:

* PDFs go through Docling when it is installed (best table extraction; it
  is the ``docling`` extra because it pulls a large ML stack) and fall back
  to pypdf otherwise, with a clear log line saying which route ran.
* Markdown is parsed directly: headings and pipe tables become structured
  blocks.
* HTML goes through the standard library's parser (no new dependency) and
  produces the same blocks, with page chrome dropped and tables rendered as
  pipe tables so they travel the Markdown route's path. See
  :mod:`sci_rag.ingest.html_parser`.
* Plain text is passed through raw; the chunker applies its own heuristics.

Docling output is exported to Markdown and re-parsed, so both structured
routes share one battle-tested block segmentation instead of tracking two
document models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

BlockKind = Literal["text", "heading", "table"]


@dataclass
class Block:
    kind: BlockKind
    text: str
    level: int = 0  # heading depth; 0 for non-headings


@dataclass
class ParsedDocument:
    title: str
    # Exactly one of these is set: structured blocks, or raw text for the
    # chunker's heuristic segmentation.
    blocks: list[Block] | None = None
    raw_text: str | None = None
    page_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt", ".html", ".htm"}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def docling_available() -> bool:
    return find_spec("docling") is not None


def parse_file(path: Path, *, prefer_docling: bool = True) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        if prefer_docling and docling_available():
            return _parse_pdf_docling(path)
        log.info("pdf_parser_fallback", path=str(path), parser="pypdf")
        return _parse_pdf_pypdf(path)
    if suffix in (".md", ".markdown"):
        return parse_markdown(path.read_text(encoding="utf-8"), fallback_title=path.stem)
    if suffix in (".html", ".htm"):
        from sci_rag.ingest.html_parser import parse_html_file

        return parse_html_file(path)
    if suffix == ".txt":
        return ParsedDocument(title=path.stem, raw_text=path.read_text(encoding="utf-8"))
    raise ValueError(
        f"Unsupported file type {suffix!r} for {path.name}. "
        f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
    )


def parse_markdown(text: str, *, fallback_title: str) -> ParsedDocument:
    """Segment markdown into heading, table, and text blocks."""
    blocks: list[Block] = []
    paragraph: list[str] = []
    table: list[str] = []
    title: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(Block(kind="text", text="\n".join(paragraph).strip()))
            paragraph.clear()

    def flush_table() -> None:
        if table:
            blocks.append(Block(kind="table", text="\n".join(table).strip()))
            table.clear()

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        stripped = line.strip()
        if heading:
            flush_paragraph()
            flush_table()
            level = len(heading.group(1))
            heading_text = heading.group(2).strip()
            if title is None and level == 1:
                # The first H1 is the document title, not a section: it goes
                # into every chunk's breadcrumb already, so emitting it as a
                # heading too would double it in the section path.
                title = heading_text
            else:
                blocks.append(Block(kind="heading", text=heading_text, level=level))
        elif stripped.startswith("|"):
            flush_paragraph()
            table.append(stripped)
        elif not stripped:
            flush_paragraph()
            flush_table()
        else:
            flush_table()
            paragraph.append(stripped)
    flush_paragraph()
    flush_table()

    blocks = [b for b in blocks if b.text]
    return ParsedDocument(title=title or fallback_title, blocks=blocks)


def _parse_pdf_pypdf(path: Path) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    meta_title = None
    if reader.metadata is not None:
        meta_title = (reader.metadata.title or "").strip() or None
    return ParsedDocument(
        title=meta_title or path.stem,
        raw_text="\f".join(pages),
        page_count=len(pages),
        metadata={"parser": "pypdf"},
    )


def _parse_pdf_docling(path: Path) -> ParsedDocument:
    from docling.document_converter import DocumentConverter

    log.info("pdf_parser", path=str(path), parser="docling")
    result = DocumentConverter().convert(str(path))
    document = result.document
    markdown = document.export_to_markdown()
    parsed = parse_markdown(markdown, fallback_title=path.stem)
    try:
        parsed.page_count = document.num_pages()
    except Exception:
        parsed.page_count = None
    parsed.metadata["parser"] = "docling"
    return parsed
