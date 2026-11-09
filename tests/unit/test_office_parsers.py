"""Office parsing with generated files and the existing chunking pipeline."""

from __future__ import annotations

import builtins
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from markdown_it import MarkdownIt
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfWriter

from sci_rag.draft.manifest import read_heads
from sci_rag.draft.sampling import sample_files
from sci_rag.ingest.chunker import chunk_document
from sci_rag.ingest.manifest import discover_folder, lint_manifest
from sci_rag.ingest.parsers import SUPPORTED_SUFFIXES, Block, parse_file

TABLE_ROWS = [
    ["任务 Task", "负责人 Owner"],
    ["文件解析", "测试同学"],
    ["状态", "开发中"],
]


@pytest.fixture
def docx_path(tmp_path: Path) -> Path:
    word = Document()
    word.core_properties.title = "PC-Mem 课程记录"
    word.core_properties.author = "Synthetic Author"
    word.add_paragraph("开头正文 before the first heading.")
    word.add_heading("项目介绍", level=1)
    word.add_paragraph("  ")
    word.add_paragraph("正文含中文与 English, 保留原始内容。")
    table = word.add_table(rows=len(TABLE_ROWS), cols=2)
    for row_index, values in enumerate(TABLE_ROWS):
        for column_index, value in enumerate(values):
            table.cell(row_index, column_index).text = value
    word.add_heading("解析细节", level=2)
    word.add_paragraph("DOCX 与 PPTX 使用现有 chunker 处理。")
    path = tmp_path / "课程 记录.docx"
    word.save(path)
    return path


@pytest.fixture
def pptx_path(tmp_path: Path) -> Path:
    deck = Presentation()
    deck.core_properties.title = "PC-Mem 汇报"
    deck.core_properties.author = "Synthetic Author"
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "第一页 项目介绍"
    slide.placeholders[1].text = "第一段中文说明。\nEnglish paragraph from a placeholder."
    textbox = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(6), Inches(1))
    textbox.text = "文本框 Text box content."
    table = slide.shapes.add_table(
        len(TABLE_ROWS), 2, Inches(1), Inches(4), Inches(6), Inches(2)
    ).table
    for row_index, values in enumerate(TABLE_ROWS):
        for column_index, value in enumerate(values):
            table.cell(row_index, column_index).text = value
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Second 第二页"
    slide.placeholders[1].text = "只属于第二页的正文, 中文和 English 都应保留。"
    path = tmp_path / "课程 汇报.pptx"
    deck.save(path)
    return path


def test_docx_preserves_paragraph_heading_and_table_order(docx_path: Path) -> None:
    document = parse_file(docx_path)

    assert document.blocks is not None
    assert [(block.kind, block.level) for block in document.blocks] == [
        ("text", 0),
        ("heading", 1),
        ("text", 0),
        ("table", 0),
        ("heading", 2),
        ("text", 0),
    ]
    assert [block.text for block in document.blocks if block.kind != "table"] == [
        "开头正文 before the first heading.",
        "项目介绍",
        "正文含中文与 English, 保留原始内容。",
        "解析细节",
        "DOCX 与 PPTX 使用现有 chunker 处理。",
    ]
    assert document.blocks[3].text == (
        "| 任务 Task | 负责人 Owner |\n| --- | --- |\n| 文件解析 | 测试同学 |\n| 状态 | 开发中 |"
    )


def test_docx_uses_core_title_without_inventing_page_count(docx_path: Path) -> None:
    document = parse_file(docx_path)

    assert document.title == "PC-Mem 课程记录"
    assert document.page_count is None
    assert document.raw_text is None
    assert document.metadata["parser"] == "docx"


def test_docx_heading_style_ids_work_with_localized_display_names(tmp_path: Path) -> None:
    word = Document()
    word.add_heading("一级标题", level=1)
    word.add_heading("二级标题", level=2)
    word.add_paragraph("标题样式的显示名称可以变化。")
    word.styles["Heading 1"].name = "标题 1"
    word.styles["Heading 2"].name = "标题 2"
    path = tmp_path / "localized.docx"
    word.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert [(block.text, block.level) for block in document.blocks if block.kind == "heading"] == [
        ("一级标题", 1),
        ("二级标题", 2),
    ]


def test_docx_title_style_is_a_heading_without_losing_preamble(tmp_path: Path) -> None:
    word = Document()
    word.add_paragraph("Preamble before the title.")
    word.add_paragraph("Document title", style="Title")
    word.add_paragraph("Body after the title.")
    path = tmp_path / "title-style.docx"
    word.save(path)

    document = parse_file(path)

    assert document.blocks == [
        Block(kind="text", text="Preamble before the title."),
        Block(kind="heading", text="Document title", level=1),
        Block(kind="text", text="Body after the title."),
    ]


def test_docx_custom_style_inherits_heading_level(tmp_path: Path) -> None:
    word = Document()
    custom = word.styles.add_style("Custom Section", WD_STYLE_TYPE.PARAGRAPH)
    custom.base_style = word.styles["Heading 2"]
    word.add_heading("Parent section", level=1)
    word.add_paragraph("Custom subsection", style=custom)
    word.add_paragraph("Content under the inherited heading.")
    path = tmp_path / "inherited-style.docx"
    word.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert document.blocks[1] == Block(kind="heading", text="Custom subsection", level=2)
    [chunk] = chunk_document(document)
    assert chunk.section_path == "Parent section > Custom subsection"


def test_docx_tables_escape_pipes_and_keep_multiline_cells_in_one_row(tmp_path: Path) -> None:
    word = Document()
    table = word.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "A|B"
    table.cell(0, 1).text = "Line one\nLine two"
    table.cell(1, 0).text = "中英文 Mixed"
    table.cell(1, 1).text = "内容"
    path = tmp_path / "cells.docx"
    word.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert len(document.blocks) == 1
    assert document.blocks[0].kind == "table"
    assert document.blocks[0].text.splitlines() == [
        r"| A\|B | Line one Line two |",
        "| --- | --- |",
        "| 中英文 Mixed | 内容 |",
    ]


def test_docx_table_retains_an_interior_blank_row(tmp_path: Path) -> None:
    word = Document()
    table = word.add_table(rows=4, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Before"
    table.cell(3, 1).text = "After"
    path = tmp_path / "blank-row.docx"
    word.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert document.blocks[0].text.splitlines() == [
        "| Name | Value |",
        "| --- | --- |",
        "| Before |  |",
        "|  |  |",
        "|  | After |",
    ]


def test_docx_chunks_retain_tables_and_heading_hierarchy(docx_path: Path) -> None:
    document = parse_file(docx_path)
    chunks = chunk_document(document, overlap_tokens=0)

    [table] = [chunk for chunk in chunks if chunk.is_table]
    assert table.section_path == "项目介绍"
    assert "| 任务 Task | 负责人 Owner |" in table.body
    assert "| 文件解析 | 测试同学 |" in table.body
    assert "| 状态 | 开发中 |" in table.body
    assert any(chunk.section_path is None and "开头正文" in chunk.body for chunk in chunks)
    assert any(
        chunk.section_path == "项目介绍 > 解析细节" and "DOCX 与 PPTX" in chunk.body
        for chunk in chunks
    )


def test_pptx_extracts_slides_titles_placeholders_and_textboxes_in_order(pptx_path: Path) -> None:
    document = parse_file(pptx_path)

    assert document.blocks is not None
    headings = [block for block in document.blocks if block.kind == "heading"]
    assert headings == [
        Block(kind="heading", text="第一页 项目介绍", level=1),
        Block(kind="heading", text="Second 第二页", level=1),
    ]
    texts = [block.text for block in document.blocks]
    assert texts.count("第一页 项目介绍") == 1
    assert texts.count("Second 第二页") == 1
    joined = "\n".join(texts)
    for text in (
        "第一段中文说明。",
        "English paragraph from a placeholder.",
        "文本框 Text box content.",
        "只属于第二页的正文, 中文和 English 都应保留。",
    ):
        assert text in joined
    second_slide = texts.index("Second 第二页")
    assert all("只属于第二页" not in text for text in texts[:second_slide])
    assert any("只属于第二页" in text for text in texts[second_slide + 1 :])


def test_pptx_retains_slide_count_and_core_title(pptx_path: Path) -> None:
    document = parse_file(pptx_path)

    assert document.title == "PC-Mem 汇报"
    assert document.page_count == 2
    assert document.raw_text is None
    assert document.metadata["parser"] == "pptx"


def test_pptx_table_and_slide_sections_survive_chunking(pptx_path: Path) -> None:
    document = parse_file(pptx_path)
    assert document.blocks is not None
    [table_block] = [block for block in document.blocks if block.kind == "table"]
    assert "| 任务 Task | 负责人 Owner |" in table_block.text
    assert "| 文件解析 | 测试同学 |" in table_block.text
    assert "| 状态 | 开发中 |" in table_block.text

    chunks = chunk_document(document, overlap_tokens=0)

    [table] = [chunk for chunk in chunks if chunk.is_table]
    assert table.body == table_block.text
    assert table.section_path == "第一页 项目介绍"
    assert any(
        chunk.section_path == "Second 第二页" and "只属于第二页" in chunk.body for chunk in chunks
    )


def test_pptx_untitled_slide_gets_a_section_boundary(tmp_path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Previous section"
    slide.placeholders[1].text = "Text belonging to the previous section."
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(1)
    ).text = "没有标题的第二页正文。"
    path = tmp_path / "untitled.pptx"
    deck.save(path)

    chunks = chunk_document(parse_file(path))

    [untitled] = [chunk for chunk in chunks if "没有标题" in chunk.body]
    assert untitled.section_path == "Slide 2"
    assert "previous section" not in untitled.body


def test_pptx_repeated_titles_still_separate_slide_content(tmp_path: Path) -> None:
    deck = Presentation()
    for body in ("First slide body.", "Second slide body."):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Repeated title"
        slide.placeholders[1].text = body
    path = tmp_path / "repeated.pptx"
    deck.save(path)

    chunks = chunk_document(parse_file(path))

    assert [chunk.body for chunk in chunks] == ["First slide body.", "Second slide body."]
    assert all(chunk.section_path == "Repeated title" for chunk in chunks)


def test_pptx_title_only_slide_keeps_its_title_block(tmp_path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "只有标题的页面"
    path = tmp_path / "title-only.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.page_count == 1
    assert document.blocks == [Block(kind="heading", text="只有标题的页面", level=1)]


def test_pptx_grouped_textbox_is_not_lost(tmp_path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(1)
    ).text = "组合内的文本框 Grouped text."
    path = tmp_path / "grouped.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.blocks == [
        Block(kind="heading", text="Slide 1", level=1),
        Block(kind="text", text="组合内的文本框 Grouped text."),
    ]
    [chunk] = chunk_document(document)
    assert chunk.section_path == "Slide 1"
    assert chunk.body == "组合内的文本框 Grouped text."


def test_pptx_table_escapes_pipes_and_cell_linebreaks(tmp_path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(6), Inches(2)).table
    table.cell(0, 0).text = "A|B"
    table.cell(0, 1).text = "Line one\nLine two"
    table.cell(1, 0).text = "中文"
    table.cell(1, 1).text = "Mixed English"
    path = tmp_path / "cells.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    [table_block] = [block for block in document.blocks if block.kind == "table"]
    lines = table_block.text.splitlines()
    assert lines[0] == r"| A\|B | Line one Line two |"
    assert lines[-1] == "| 中文 | Mixed English |"
    assert len([line for line in lines if "Line" in line]) == 1
    [chunk] = [chunk for chunk in chunk_document(document) if chunk.is_table]
    assert chunk.body == table_block.text
    assert chunk.section_path == "Slide 1"


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
def test_empty_office_documents_produce_no_chunks(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"empty{suffix}"
    if suffix == ".docx":
        Document().save(path)
    else:
        Presentation().save(path)

    document = parse_file(path)

    assert document.blocks == []
    assert document.page_count == (None if suffix == ".docx" else 0)
    assert chunk_document(document) == []


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
def test_empty_office_tables_do_not_create_fake_content(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"empty-table{suffix}"
    if suffix == ".docx":
        word = Document()
        word.add_table(rows=2, cols=2)
        word.save(path)
    else:
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(6), Inches(2))
        deck.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert all(block.kind != "table" for block in document.blocks)
    assert chunk_document(document) == []


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
@pytest.mark.parametrize("payload", [b"", b"This is not an Office archive."])
def test_corrupt_office_files_fail_clearly(tmp_path: Path, suffix: str, payload: bytes) -> None:
    path = tmp_path / f"broken{suffix}"
    path.write_bytes(payload)

    with pytest.raises(ValueError) as error:
        parse_file(path)

    assert str(error.value).strip()


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
def test_missing_office_files_raise_file_not_found(tmp_path: Path, suffix: str) -> None:
    with pytest.raises(FileNotFoundError):
        parse_file(tmp_path / f"missing{suffix}")


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
def test_office_title_falls_back_to_filename(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"中文 fallback{suffix}"
    source = Document() if suffix == ".docx" else Presentation()
    source.core_properties.title = "  "
    source.save(path)

    assert parse_file(path).title == "中文 fallback"


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
def test_office_embedded_properties_are_preserved(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"properties{suffix}"
    source = Document() if suffix == ".docx" else Presentation()
    source.core_properties.author = "Synthetic Author"
    source.core_properties.subject = "Synthetic coursework"
    source.core_properties.created = datetime(2024, 4, 5, 6, 7, 8, tzinfo=UTC)
    source.core_properties.modified = datetime(2025, 5, 6, 7, 8, 9, tzinfo=UTC)
    source.save(path)

    metadata = parse_file(path).metadata

    assert metadata["author"] == "Synthetic Author"
    assert metadata["subject"] == "Synthetic coursework"
    # python-pptx exposes embedded timestamps without timezone information.
    timezone = "+00:00" if suffix == ".docx" else ""
    assert metadata["created"] == f"2024-04-05T06:07:08{timezone}"
    assert metadata["modified"] == f"2025-05-06T07:08:09{timezone}"


@pytest.mark.parametrize(("suffix", "module"), [(".docx", "docx"), (".pptx", "pptx")])
def test_missing_office_extra_has_install_hint_and_leaves_text_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str, module: str
) -> None:
    path = tmp_path / f"input{suffix}"
    source = Document() if suffix == ".docx" else Presentation()
    source.save(path)
    text_path = tmp_path / "legacy.txt"
    text_path.write_text(
        "Existing text remains readable without the Office extra.", encoding="utf-8"
    )
    original_import = builtins.__import__

    def import_without_office(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == module or name.startswith(f"{module}."):
            raise ModuleNotFoundError(f"No module named {module!r}", name=module)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_office)

    with pytest.raises(ImportError, match="uv sync --extra office"):
        parse_file(path)
    assert (
        parse_file(text_path).raw_text == "Existing text remains readable without the Office extra."
    )


def test_office_suffixes_route_case_insensitively(docx_path: Path, pptx_path: Path) -> None:
    assert {".docx", ".pptx"} <= SUPPORTED_SUFFIXES
    word = docx_path.with_suffix(".DoCx")
    slides = pptx_path.with_suffix(".PpTx")
    docx_path.rename(word)
    pptx_path.rename(slides)

    assert parse_file(word).metadata["parser"] == "docx"
    assert parse_file(slides).metadata["parser"] == "pptx"


def test_discover_folder_finds_office_files_recursively(
    tmp_path: Path, docx_path: Path, pptx_path: Path
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    word = nested / "notes.DoCx"
    slides = nested / "slides.PpTx"
    docx_path.rename(word)
    pptx_path.rename(slides)
    text = tmp_path / "legacy.txt"
    text.write_text("Existing plain text.", encoding="utf-8")
    for unsupported in ("old.doc", "old.ppt", "unrelated.bin"):
        (nested / unsupported).write_bytes(b"unsupported")

    entries = discover_folder(tmp_path, source="office-test")

    assert {entry.path for entry in entries} == {word.resolve(), slides.resolve(), text.resolve()}
    assert all(entry.source == "office-test" for entry in entries)
    assert all(entry.license_class == "unknown" for entry in entries)


def test_manifest_linter_accepts_office_suffixes(
    tmp_path: Path, docx_path: Path, pptx_path: Path
) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            json.dumps({"path": str(path), "title": path.stem}) for path in (docx_path, pptx_path)
        ),
        encoding="utf-8",
    )

    report = lint_manifest(manifest)

    assert report.ok
    assert report.findings == []
    assert report.entry_count == 2


@pytest.mark.parametrize("reader", ["heads", "passages"])
def test_draft_readers_keep_office_files_out_of_prompts(tmp_path: Path, reader: str) -> None:
    (tmp_path / "notes.md").write_text(
        "# Existing notes\n\n"
        "This is an existing Markdown document with enough prose for a passage. "
        "It continues to work when unsupported Office archives share the folder.",
        encoding="utf-8",
    )
    for suffix in (".DoCx", ".PpTx"):
        (tmp_path / f"unreadable{suffix}").write_bytes(b"Not a valid Office archive.")

    if reader == "heads":
        heads = read_heads(tmp_path)
        assert [head.filename for head in heads] == ["notes.md"]
    else:
        sample = sample_files(tmp_path)
        assert sample.document_count == 1
        assert {passage.document_title for passage in sample.passages} == {"Existing notes"}


@pytest.mark.parametrize(
    ("suffix", "text"),
    [
        (".md", "# Legacy document\n\n## Section\n\n已有解析器内容继续保留, English text."),
        (".markdown", "# Legacy document\n\n已有解析器内容继续保留, English text."),
        (".html", "<h1>Legacy document</h1><p>已有解析器内容继续保留, English text.</p>"),
        (".htm", "<h1>Legacy document</h1><p>已有解析器内容继续保留, English text.</p>"),
        (".txt", "已有解析器内容继续保留, English text remains available for chunking."),
    ],
)
def test_legacy_text_parsers_still_produce_chunks(tmp_path: Path, suffix: str, text: str) -> None:
    path = tmp_path / f"legacy{suffix}"
    path.write_text(text, encoding="utf-8")

    document = parse_file(path, prefer_docling=False)
    chunks = chunk_document(document)

    assert document.title == ("legacy" if suffix == ".txt" else "Legacy document")
    assert any("已有解析器内容继续保留" in chunk.body for chunk in chunks)


def test_legacy_pdf_fallback_still_reads_title_and_page_count(tmp_path: Path) -> None:
    path = tmp_path / "legacy.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Legacy PDF document"})
    writer.write(path)

    document = parse_file(path, prefer_docling=False)

    assert document.title == "Legacy PDF document"
    assert document.page_count == 1
    assert document.metadata["parser"] == "pypdf"
    assert document.blocks is None
    assert document.raw_text == ""


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
@pytest.mark.parametrize(
    ("cells", "expected_row"),
    [
        (("字段", "内容"), "| 字段 | 内容 |"),
        (("A|B", "中文 English"), r"| A\|B | 中文 English |"),
        (("", "保留空单元格"), "|  | 保留空单元格 |"),
    ],
)
def test_single_row_office_table_has_separator_and_survives_chunking(
    tmp_path: Path, suffix: str, cells: tuple[str, str], expected_row: str
) -> None:
    path = tmp_path / f"single-row{suffix}"
    if suffix == ".docx":
        source = Document()
        source.add_heading("单行表格", level=1)
        table = source.add_table(rows=1, cols=2)
    else:
        source = Presentation()
        slide = source.slides.add_slide(source.slide_layouts[5])
        slide.shapes.title.text = "单行表格"
        table = slide.shapes.add_table(1, 2, Inches(1), Inches(2), Inches(6), Inches(1)).table
    for index, value in enumerate(cells):
        table.cell(0, index).text = value
    source.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    [table_block] = [block for block in document.blocks if block.kind == "table"]
    assert table_block.text.splitlines() == [expected_row, "| --- | --- |"]
    [chunk] = chunk_document(document, overlap_tokens=0)
    assert chunk.is_table is True
    assert chunk.body == table_block.text
    assert chunk.section_path == "单行表格"


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
@pytest.mark.parametrize("row_count", [1, 2], ids=["single-row", "multi-row"])
@pytest.mark.parametrize(
    "cell_text",
    [
        pytest.param("A|B", id="plain-pipe"),
        pytest.param(r"A\|B", id="one-backslash"),
        pytest.param(r"A\\|B", id="two-backslashes"),
        pytest.param(r"A\|B\\|C", id="mixed-escapes"),
        pytest.param(r"C:\项目\\archive", id="windows-path"),
    ],
)
def test_office_table_cells_round_trip_through_markdown_and_chunking(
    tmp_path: Path, suffix: str, row_count: int, cell_text: str
) -> None:
    rows = [[cell_text, "中文", ""]]
    if row_count == 2:
        rows.append([cell_text, "English", ""])
    path = tmp_path / f"escaped-table{suffix}"
    if suffix == ".docx":
        source = Document()
        source.add_heading("Escaped table", level=1)
        table = source.add_table(rows=row_count, cols=3)
    else:
        source = Presentation()
        slide = source.slides.add_slide(source.slide_layouts[5])
        slide.shapes.title.text = "Escaped table"
        table = slide.shapes.add_table(
            row_count, 3, Inches(1), Inches(2), Inches(6), Inches(1)
        ).table
    for row_index, values in enumerate(rows):
        for column_index, value in enumerate(values):
            table.cell(row_index, column_index).text = value
    source.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    [table_block] = [block for block in document.blocks if block.kind == "table"]
    rendered = MarkdownIt("commonmark").enable("table").render(table_block.text)
    html_table = ElementTree.fromstring(rendered)
    assert html_table.tag == "table"
    assert [
        ["".join(cell.itertext()) for cell in row] for row in html_table.findall(".//tr")
    ] == rows
    [chunk] = chunk_document(document, overlap_tokens=0)
    assert chunk.is_table is True
    assert chunk.body == table_block.text
    assert chunk.section_path == "Escaped table"


def _sized_textbox(
    slide: Any,
    text: str,
    *,
    top: float,
    size: float | None,
    left: float = 0.5,
    width: float = 8.5,
    height: float = 0.6,
) -> Any:
    from pptx.util import Pt

    shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    shape.text = text
    if size is not None:
        for paragraph in shape.text_frame.paragraphs:
            paragraph.font.size = Pt(size)
    return shape


def test_pptx_obvious_textbox_title_keeps_body_group_and_table(tmp_path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    title = "知识图谱课程进度"
    _sized_textbox(slide, title, top=0.3, size=32)
    body = "中文正文与 English 都应保留。"
    _sized_textbox(slide, body, top=2, size=18, height=1)
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(
        Inches(0.5), Inches(3), Inches(8.5), Inches(0.6)
    ).text = "分组文本仍然保留。"
    table = slide.shapes.add_table(2, 2, Inches(0.5), Inches(4), Inches(8.5), Inches(1)).table
    for row_index, values in enumerate((("字段", "内容"), ("状态", "开发中"))):
        for column_index, value in enumerate(values):
            table.cell(row_index, column_index).text = value
    path = tmp_path / "visual-title.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert document.blocks[0] == Block(kind="heading", text=title, level=1)
    texts = [block.text for block in document.blocks]
    assert texts.count(title) == 1
    assert body in texts
    assert "分组文本仍然保留。" in texts
    [table_block] = [block for block in document.blocks if block.kind == "table"]
    assert table_block.text.splitlines() == [
        "| 字段 | 内容 |",
        "| --- | --- |",
        "| 状态 | 开发中 |",
    ]
    chunks = chunk_document(document, overlap_tokens=0)
    assert all(chunk.section_path == title for chunk in chunks)
    assert sum(chunk.is_table for chunk in chunks) == 1
    assert title not in "\n".join(chunk.body for chunk in chunks)


def test_pptx_textbox_title_does_not_depend_on_shape_storage_order(tmp_path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    body = "The body is stored before the visual title."
    _sized_textbox(slide, body, top=2, size=18, height=2)
    _sized_textbox(slide, "真正的标题", top=0.3, size=32)
    path = tmp_path / "body-first.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.blocks == [
        Block(kind="heading", text="真正的标题", level=1),
        Block(kind="text", text=body),
    ]
    [chunk] = chunk_document(document)
    assert chunk.section_path == "真正的标题"
    assert chunk.body == body


@pytest.mark.parametrize(
    "layout",
    [
        "lower-large-body",
        "top-only",
        "same-font",
        "weak-contrast",
        "unknown-run",
        "unknown-body",
        "rotated",
        "multiline",
        "long-text",
        "two-top-boxes",
    ],
)
def test_pptx_ambiguous_textboxes_keep_fallback_and_all_text(tmp_path: Path, layout: str) -> None:
    from pptx.util import Pt

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    if layout == "lower-large-body":
        _sized_textbox(slide, "This large text belongs to the body.", top=2, size=40, height=1)
    elif layout == "top-only":
        _sized_textbox(slide, "No body text provides a font comparison.", top=0.3, size=32)
    else:
        body_size = None if layout == "unknown-body" else 28 if layout == "weak-contrast" else 18
        _sized_textbox(
            slide, "Regular body text remains available.", top=2, size=body_size, height=2
        )
        if layout == "same-font":
            _sized_textbox(slide, "Top body text is not a title.", top=0.3, size=18)
        elif layout in ("weak-contrast", "unknown-body", "rotated"):
            shape = _sized_textbox(slide, "Uncertain visual heading", top=0.3, size=32)
            if layout == "rotated":
                shape.rotation = 15
        elif layout == "unknown-run":
            shape = _sized_textbox(slide, "", top=0.3, size=None)
            paragraph = shape.text_frame.paragraphs[0]
            run = paragraph.add_run()
            run.text = "Mixed "
            run.font.size = Pt(32)
            paragraph.add_run().text = "unresolved style"
        elif layout == "multiline":
            _sized_textbox(slide, "First line\nSecond line", top=0.3, size=32)
        elif layout == "long-text":
            _sized_textbox(
                slide,
                "This text is a full explanatory sentence, with enough detail to belong to the "
                "body rather than provide a short slide title.",
                top=0.3,
                size=32,
            )
        else:
            _sized_textbox(slide, "Left heading", top=0.3, size=32, width=4)
            _sized_textbox(slide, "Right heading", top=0.3, size=32, left=5, width=4)
    expected_texts = [
        paragraph.text.replace("\v", "\n").strip()
        for shape in slide.shapes
        for paragraph in shape.text_frame.paragraphs
        if paragraph.text.strip()
    ]
    path = tmp_path / f"ambiguous-{layout}.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert document.blocks[0] == Block(kind="heading", text="Slide 1", level=1)
    assert [block.text for block in document.blocks if block.kind == "text"] == expected_texts
    assert all(block.kind != "heading" for block in document.blocks[1:])
    [chunk] = chunk_document(document, overlap_tokens=0)
    assert chunk.section_path == "Slide 1"
    assert all(text in chunk.body for text in expected_texts)


def test_pptx_standard_title_wins_and_keeps_other_textboxes(tmp_path: Path) -> None:
    from pptx.util import Pt

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "标准标题"
    slide.placeholders[1].text = "占位符正文应保留。"
    slide.placeholders[1].text_frame.paragraphs[0].font.size = Pt(18)
    _sized_textbox(slide, "更大的普通文本框", top=0.3, size=40)
    path = tmp_path / "standard-title-first.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert [block for block in document.blocks if block.kind == "heading"] == [
        Block(kind="heading", text="标准标题", level=1)
    ]
    assert [block.text for block in document.blocks].count("标准标题") == 1
    assert [block.text for block in document.blocks if block.kind == "text"] == [
        "占位符正文应保留。",
        "更大的普通文本框",
    ]
    assert all(chunk.section_path == "标准标题" for chunk in chunk_document(document))


def test_pptx_empty_standard_title_allows_obvious_textbox_title(tmp_path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "   "
    _sized_textbox(slide, "文本框中的标题", top=0.3, size=32)
    _sized_textbox(slide, "保留正文。", top=2, size=18, height=2)
    path = tmp_path / "empty-standard-title.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.blocks == [
        Block(kind="heading", text="文本框中的标题", level=1),
        Block(kind="text", text="保留正文。"),
    ]


def test_pptx_visual_title_and_fallback_keep_separate_slide_sections(tmp_path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    _sized_textbox(slide, "第一页中文标题", top=0.3, size=32)
    _sized_textbox(slide, "第一页正文 Chinese and English.", top=2, size=18, height=2)
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    _sized_textbox(slide, "第二页只有正文, 不应沿用前一页标题。", top=2, size=18, height=2)
    path = tmp_path / "visual-and-fallback.pptx"
    deck.save(path)

    document = parse_file(path)
    chunks = chunk_document(document, overlap_tokens=0)

    assert document.page_count == 2
    assert [(chunk.section_path, chunk.body) for chunk in chunks] == [
        ("第一页中文标题", "第一页正文 Chinese and English."),
        ("Slide 2", "第二页只有正文, 不应沿用前一页标题。"),
    ]


@pytest.mark.parametrize("kind", ["group", "table"])
def test_pptx_upper_content_blocks_uncertain_textbox_title(tmp_path: Path, kind: str) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    if kind == "group":
        group = slide.shapes.add_group_shape()
        _sized_textbox(group, "上方分组内容", top=0.05, size=48, height=0.4)
    else:
        table = slide.shapes.add_table(1, 2, Inches(0.5), Inches(0.05), Inches(8.5), Inches(0.4))
        table.table.cell(0, 0).text = "上方表格"
        table.table.cell(0, 1).text = "保留内容"
    _sized_textbox(slide, "Details", top=0.8, size=32)
    _sized_textbox(slide, "Ordinary slide body", top=3, size=18)
    path = tmp_path / f"upper-{kind}.pptx"
    deck.save(path)

    document = parse_file(path)

    assert document.blocks is not None
    assert document.blocks[0] == Block(kind="heading", text="Slide 1", level=1)
    texts = [block.text for block in document.blocks]
    assert texts.count("Details") == 1
    assert texts.count("Ordinary slide body") == 1
    if kind == "group":
        assert texts.count("上方分组内容") == 1
    else:
        [table_block] = [block for block in document.blocks if block.kind == "table"]
        assert table_block.text == "| 上方表格 | 保留内容 |\n| --- | --- |"
    chunks = chunk_document(document, overlap_tokens=0)
    assert all(chunk.section_path == "Slide 1" for chunk in chunks)
    assert sum(chunk.is_table for chunk in chunks) == (1 if kind == "table" else 0)
