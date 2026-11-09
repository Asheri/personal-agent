---
title: Office parsers
description: Read DOCX and PPTX files through the existing parser, chunker, and ingestion pipeline.
---

# Office parsers

DOCX and PPTX files use the existing `ParsedDocument` and `Block` types.
The initial change covered two formats within F1. The later
[local file types candidate](file-types.md) adds XLSX, email, code, text data,
and optional OCR. Automatic synchronization triggers remain separate work.

## Use the parsers

Install the optional runtime dependencies:

```powershell
uv sync --extra office
```

The development dependency group also includes these libraries so the unit tests run without skips.
The new libraries are python-docx and python-pptx; no model weights are needed.

Existing entry points work without a new command:

```python
from pathlib import Path
from sci_rag.ingest.parsers import parse_file
from sci_rag.ingest.chunker import chunk_document

document = parse_file(Path("notes.docx"))  # also accepts .pptx
chunks = chunk_document(document)
```

`discover_folder()` finds both suffixes, including mixed-case filenames.
An existing ingestion command can read a folder containing these files.
Use a separate database for development checks. No schema or migration changes are needed.

## Structures and metadata

- DOCX body paragraphs and tables retain their stored order. Heading styles, their derived styles, and the Title style become heading blocks. DOCX page count stays `None`.
- Each PPTX slide starts a level-1 section. A nonempty standard title placeholder takes priority. Otherwise, a clearly styled ordinary textbox may provide the title under the rules below. An uncertain slide uses `Slide N`. The selected title appears once; all other textboxes, placeholders, group shapes, and tables follow their stored shape order. The page count is the number of slides.
- Tables become one pipe-table block each. Cell whitespace is folded, source backslashes are escaped before literal pipes, and empty rows inside a nonempty table are retained. Markdown rendering preserves the backslashes and pipes in the source cells. A single-row Office table includes its Markdown header separator without adding a data row. The existing chunker keeps each table intact and sets `is_table`. The HTML renderer's behavior is unchanged by this fix.
- The document title uses the embedded title property, with the filename stem as fallback. Parser names are `docx` and `pptx`.
- Nonempty embedded author, subject, keywords, and available creation/modification timestamps stay in metadata and pass through to `Document.extra`. These are source properties, which may come from templates; they are not verified authorship or filesystem dates. Timestamp offsets are preserved as returned by each library.
- Manifest authors and other first-class citation fields keep their existing behavior. The ingestion timestamp is set by the ingester and cannot be overridden by parser metadata.

Empty content produces no chunks. A document or slide containing only headings also has no body chunk under the existing chunker. A title-only slide still retains its heading in the parse result. Corrupt packages raise `ValueError`; a missing file raises `FileNotFoundError`. The ingester reports these through its existing failure path.

## Textbox title rules

The fallback uses a conjunction of layout and recorded font evidence. It does not select a title from shape order or font size alone:

- Only an unrotated, top-level ordinary textbox is eligible. It must have one nonblank paragraph, no explicit line breaks, and at most 60 characters.
- Its top must be within the upper 25% of the slide and its bottom within the upper 35%. Its width must cover at least 40% of the slide, stay within the slide edges, and its height must be at most 20% of the slide.
- Every nonblank title run needs a recorded run or paragraph font size of at least 28 pt. The smallest title size must be at least 1.3 times the largest recorded font in the other top-level text shapes.
- At least one other text shape must provide body evidence. All other top-level text shapes must start below the candidate with a gap of 2% of the slide height, and at least one must overlap half the smaller width horizontally. Missing body font sizes prevent inference.
- Nonempty groups or tables above or overlapping the candidate also prevent inference. Their content is still extracted; grouped text is not itself promoted to a title.
- A candidate must be unique. Otherwise the slide keeps `Slide N`, with all text retained as body content.

These rules cover simple, explicitly styled layouts. Theme-inherited font sizes are not resolved, automatic wrapping is not measured, and split or complex visual titles may fall back. A lone visual textbox has no body comparison and also falls back. Standard title placeholders keep their existing behavior regardless of these rules.

## Limits

The parsers do not read old `.doc` or `.ppt` files, encrypted packages, images, OCR, formulas, SmartArt, animations, charts, or speaker notes. DOCX body textboxes, headers, footers, revision markup, and nested tables are outside this change. Shape order in PPTX is the file's stored order, not an inferred visual reading order. Merged table layout is flattened to the library's cell grid.

Draft sampling and manifest drafting keep their previous six suffixes. Office ingestion does not expand the set of raw files sent to drafting prompts.

## Development record

Implementation and tests were prepared with AI assistance on 2026-10-21.
No Git repository was initialized, and no commit, push, or PR was created.
The full F1 task remains open.

The verification commands, baseline failures, and pending review are recorded in
[the review handoff](superpowers/specs/reviews/2026-10-21-office-parsers-review.md).
AGENTS.md section 5 still requires a nonauthor review before merging.

The 2026-10-23 follow-up fixes backslash and pipe escaping in Office tables.
Generated DOCX/PPTX tests verify rendered cell values, table dimensions, and chunk metadata.
The new development evidence and remaining review requirement are recorded in
[the escaping handoff](superpowers/specs/reviews/2026-10-23-office-table-escaping-review.md).

Library API references: [DOCX document iteration](https://python-docx.readthedocs.io/en/latest/api/document.html#docx.document.Document.iter_inner_content) and [PPTX shapes](https://python-pptx.readthedocs.io/en/latest/api/shapes.html).
