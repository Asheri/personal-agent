"""Read DOCX and PPTX files into the shared heading, text, and table blocks."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sci_rag.ingest.html_parser import render_pipe_table
from sci_rag.ingest.parsers import Block, ParsedDocument

if TYPE_CHECKING:
    from docx.text.paragraph import Paragraph
    from pptx.shapes.autoshape import Shape
    from pptx.shapes.base import BaseShape
    from pptx.slide import Slide

_HEADING_STYLE = re.compile(r"(?:heading|标题)\s*([1-9])", re.IGNORECASE)


def _heading_level(paragraph: Paragraph) -> int:
    style = paragraph.style
    seen: set[str] = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        for name in (style.style_id, style.name or ""):
            match = _HEADING_STYLE.fullmatch(name)
            if match:
                return int(match.group(1))
            if name.lower() == "title":
                return 1
        style = style.base_style
    return 0


def _metadata(properties: Any, *, parser: str) -> dict[str, Any]:
    """Keep embedded properties as reported, without inferring file dates."""
    metadata: dict[str, Any] = {"parser": parser}
    for name in ("author", "subject", "keywords"):
        value = getattr(properties, name).strip()
        if value:
            metadata[name] = value
    for name in ("created", "modified"):
        value = getattr(properties, name)
        if value is not None:
            metadata[name] = value.isoformat()
    return metadata


def _table_block(rows: list[list[str]]) -> Block | None:
    if not any(cell.strip() for row in rows for cell in row):
        return None
    # Escape source backslashes before pipes so Markdown preserves both.
    cleaned = [
        [" ".join(cell.split()).replace("\\", "\\\\").replace("|", "\\|") for cell in row]
        for row in rows
    ]
    rendered = render_pipe_table(cleaned, header=True, preserve_empty_rows=True)
    if len(cleaned) == 1:
        rendered += "\n| " + " | ".join("---" for _ in cleaned[0]) + " |"
    return Block(kind="table", text=rendered)


def parse_docx(path: Path) -> ParsedDocument:
    """Read body paragraphs and tables in their stored document order."""
    try:
        from docx import Document
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise ImportError("DOCX parsing requires: uv sync --extra office") from exc

    with path.open("rb") as source:
        try:
            document = Document(source)
        except Exception as exc:
            raise ValueError(f"Invalid DOCX file: {exc}") from exc

    blocks: list[Block] = []
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            level = _heading_level(item)
            blocks.append(Block(kind="heading" if level else "text", text=text, level=level))
        else:
            rows = [
                [""] * row.grid_cols_before
                + [cell.text for cell in row.cells]
                + [""] * row.grid_cols_after
                for row in item.rows
            ]
            table = _table_block(rows)
            if table is not None:
                blocks.append(table)

    return ParsedDocument(
        title=document.core_properties.title.strip() or path.stem,
        blocks=blocks,
        page_count=None,
        metadata=_metadata(document.core_properties, parser="docx"),
    )


def _shape_blocks(shape: BaseShape) -> Iterator[Block]:
    from pptx.shapes.autoshape import Shape
    from pptx.shapes.graphfrm import GraphicFrame
    from pptx.shapes.group import GroupShape

    if isinstance(shape, GroupShape):
        for child in shape.shapes:
            yield from _shape_blocks(child)
    elif shape.has_table:
        table = cast(GraphicFrame, shape).table
        block = _table_block([[cell.text for cell in row.cells] for row in table.rows])
        if block is not None:
            yield block
    elif shape.has_text_frame:
        for paragraph in cast(Shape, shape).text_frame.paragraphs:
            text = paragraph.text.replace("\v", "\n").strip()
            if text:
                yield Block(kind="text", text=text)


def _explicit_font_sizes(shape: Shape) -> tuple[float, float] | None:
    """Use recorded run or paragraph sizes; do not guess theme defaults."""
    sizes: list[float] = []
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            if not run.text.strip():
                continue
            size = run.font.size if run.font.size is not None else paragraph.font.size
            if size is None:
                return None
            sizes.append(size.pt)
    return (min(sizes), max(sizes)) if sizes else None


def _slide_title_shape(slide: Slide, *, width: int | None, height: int | None) -> Shape | None:
    """Prefer a semantic title, then a clear top textbox above smaller body text."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    standard = slide.shapes.title
    if standard is not None and standard.text.strip():
        return standard
    if not width or not height:
        return None

    text_shapes = [
        cast("Shape", shape)
        for shape in slide.shapes
        if shape.has_text_frame and cast("Shape", shape).text.strip()
    ]
    if len(text_shapes) < 2:
        return None
    if any(
        value is None
        for shape in text_shapes
        for value in (shape.left, shape.top, shape.width, shape.height)
    ) or any(shape.width <= 0 or shape.height <= 0 for shape in text_shapes):
        return None
    other_content = [
        shape for shape in slide.shapes if not shape.has_text_frame and any(_shape_blocks(shape))
    ]

    candidates: list[Shape] = []
    for shape in text_shapes:
        if shape.shape_type != MSO_SHAPE_TYPE.TEXT_BOX or shape.rotation != 0:
            continue
        paragraphs = [p for p in shape.text_frame.paragraphs if p.text.strip()]
        if len(paragraphs) != 1 or len(shape.text.strip()) > 60:
            continue
        if any(char in shape.text for char in "\n\r\v"):
            continue
        bottom = shape.top + shape.height
        if not (
            0 <= shape.top <= 0.25 * height
            and bottom <= 0.35 * height
            and shape.height <= 0.20 * height
            and shape.width >= 0.40 * width
            and 0 <= shape.left <= width - shape.width
        ):
            continue
        sizes = _explicit_font_sizes(shape)
        if sizes is None or sizes[0] < 28:
            continue

        others = [other for other in text_shapes if other.shape_id != shape.shape_id]
        # Competing upper text and unresolved body styles make the evidence ambiguous.
        if any(other.top < bottom + 0.02 * height for other in others):
            continue
        if any(other.top is None or other.top < bottom + 0.02 * height for other in other_content):
            continue
        body_sizes = [_explicit_font_sizes(other) for other in others]
        if any(size is None for size in body_sizes):
            continue
        largest_body = max(size[1] for size in body_sizes if size is not None)
        if sizes[0] < 1.3 * largest_body:
            continue
        if not any(
            min(shape.left + shape.width, other.left + other.width) - max(shape.left, other.left)
            >= 0.5 * min(shape.width, other.width)
            for other in others
        ):
            continue
        candidates.append(shape)
    return candidates[0] if len(candidates) == 1 else None


def parse_pptx(path: Path) -> ParsedDocument:
    """Give each slide a heading and read its shapes in stored order."""
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise ImportError("PPTX parsing requires: uv sync --extra office") from exc

    with path.open("rb") as source:
        try:
            presentation = Presentation(source)
        except Exception as exc:
            raise ValueError(f"Invalid PPTX file: {exc}") from exc

    blocks: list[Block] = []
    for number, slide in enumerate(presentation.slides, start=1):
        title_shape = _slide_title_shape(
            slide, width=presentation.slide_width, height=presentation.slide_height
        )
        title = " ".join(title_shape.text.split()) if title_shape is not None else ""
        # Even untitled slides reset the chunker's section and overlap state.
        blocks.append(Block(kind="heading", text=title or f"Slide {number}", level=1))
        for shape in slide.shapes:
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            blocks.extend(_shape_blocks(shape))

    return ParsedDocument(
        title=presentation.core_properties.title.strip() or path.stem,
        blocks=blocks,
        page_count=len(presentation.slides),
        metadata=_metadata(presentation.core_properties, parser="pptx"),
    )
