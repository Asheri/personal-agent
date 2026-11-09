# Local file types

Ingest local spreadsheets, messages, source code, text data, and printed-text
images through the existing document, chunk, version, and retrieval pipeline.
This v1.7 candidate extends the earlier Office parsers and awaits nonauthor review.

## Supported inputs

Folder discovery and explicit manifest parsing share one whitelist of 41 suffixes.
The manifest drafting feature retains its earlier, narrower document subset.

| Family | Suffixes | Behavior |
|---|---|---|
| Existing documents | `.pdf`, `.docx`, `.pptx`, `.md`, `.markdown`, `.txt`, `.html`, `.htm` | Existing block and table routes remain available. |
| Spreadsheet | `.xlsx` | Read each worksheet, including hidden sheets, as a heading and table. |
| Mail | `.eml`, `.mbox` | Prefer the plain MIME body; use local HTML parsing when necessary. |
| Code | `.py`, `.pyi`, `.js`, `.jsx`, `.ts`, `.tsx`, `.sh`, `.bash`, `.ps1`, `.sql`, `.c`, `.h`, `.cpp`, `.hpp`, `.java`, `.go`, `.rs` | Retain source text; never execute it. |
| Text data | `.csv`, `.tsv`, `.json`, `.jsonl`, `.yaml`, `.yml` | Parse delimiter quoting or validate structured syntax; retain source values. |
| OCR image | `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp` | Recognize printed text locally; process every TIFF frame. |

Legacy binary `.doc`, `.xls`, and `.ppt`, audio/video, nested mail attachments,
and semantic image descriptions remain outside this implementation. Convert
legacy Office files to the supported OOXML format before ingestion.

## Install and use

Install Python dependencies with `uv sync --extra office --extra ocr-tesseract`.
The OCR extra contains Pillow and pypdfium2; it does not install a native
Tesseract executable or its language data. The `ocr` extra is an equivalent alias.
Install the native runtime and `chi_sim`/`eng` data separately. Point both
settings at your own installation; the example below is a Homebrew tree on
macOS, and a Windows portable runtime under `PCMEM_DATA_DIR` works the same
way (`Library/bin/tesseract.exe` and `share/tessdata`).

```text
SCI_RAG_OCR_TESSERACT_CMD=/opt/homebrew/bin/tesseract
SCI_RAG_OCR_TESSDATA_DIR=/opt/homebrew/share/tessdata
SCI_RAG_OCR_LANGUAGES=chi_sim+eng
```

Unset executable paths search `PATH`. Native DLLs must also be discoverable.
OCR uses a local subprocess with a 60-second per-page timeout. Missing runtimes,
language data, failed engines, and empty recognition return explicit failures.
No OCR download or network request happens during parsing.

Use `sci-rag ingest "$PCMEM_DATA_DIR/corpus" --no-docling`, or an explicit JSONL
manifest.
Ordinary folder inputs keep `license_class=unknown`; installing parsers grants
no permission to send their contents to an external model.

## Content and identity rules

XLSX reads the first 500 physical rows of each sheet, including its header.
The parser counts omitted rows and stores exact totals in `extra.truncated`.
It reads cached formula results without evaluating formulas or following links.
Missing caches are empty cells listed in `formulas_unevaluated`; existing cache
freshness is unverified. Password-protected OOXML containers fail explicitly.
CSV/TSV currently load all rows into memory; large inputs need resource planning.

Code retains full source chunks for vectors and full-text evidence. Metadata
records the first 2,000 characters and symbol hints. Python uses AST inspection;
other languages use conservative declaration patterns and can have no hints.
This is a deliberate departure from a separate compact vector representation.
Text data accepts UTF BOM encodings, UTF-8, and a strict GB18030 fallback, and
normalizes line endings. YAML uses the safe loader; data is never evaluated.

`parse_file_many` returns one document per MBOX message. `parse_file` preserves
the single-result API by returning the first member; empty containers have no
single result. Ingestion uses the multi-result API for the entire mailbox.
EML remains a single file identity. Mail dates and selected headers are metadata;
attachments are counted and skipped. Remote HTML resources are never fetched.

MBOX member keys prefer a syntactically valid Message-ID. A duplicate Message-ID
rejects the host file without changing existing rows. Missing or malformed IDs
use normalized raw-message hashes plus occurrence counts for identical copies.
Unchanged messages survive deletion and reordering. Editing an ID-less message
creates a new member and removes the old one; stable edit identity cannot be
inferred from ordinal position. Moving a source path retains the existing
path-based identity policy.

One host transaction covers member inserts, version updates, and absent-member
chain deletion. Failed embedding, duplicate IDs, stale plans, and source changes
roll back the host write. Host member counts and aggregate digests are stored
on current members. Existing flattened mailbox rows require an explicit rebuild.
The schema remains revision 0011. Ingest signature version 2 causes one checked
reparse of earlier sources; unchanged text can retain its existing document row.

PDF parsing checks every page for low native text (fewer than 40 characters) and
an image before accepting rich output. Those pages use OCR at 2.5x rendering;
native pages retain their original text and page numbers. Other PDFs keep the
Docling or pypdf route. Image-free vector outlines and blank pages are not
classified as scans. OCR confidence is an engine score, not measured accuracy.
Changing OCR paths or languages invalidates its ingest signature; replacing
language data in place needs a manual reparse or a changed configured path.

## Reports and validation

CLI output includes `parser=<name> ok=<n> failed=<n> skipped=<n>`. A numeric JSON
receipt is written under `.context/ingest-reports/` in the working directory,
without source paths or contents. Any failed source keeps the CLI exit code 1.
Counts measure source files: a three-message mailbox contributes one source and
three database documents. Unchanged sources count as skipped, not parsed.

`scripts/run_format_acceptance.py` generates all fixtures in a caller-selected
temporary directory. It requires an explicit loopback disposable `_test` database,
uses local-hash embeddings for pipeline checks, and freezes OCR thresholds before
native recognition. Run it with `--fixtures`, `--output`, and `--font` paths.
It creates 42 sources across 41 suffixes and 44 logical documents, including a
mixed PDF and a three-message mailbox. Labels are constructed, not field-tested.

Evidence is archived in `.context/file-types-20261025/`, including failed trials.
The initial pure-English marker query missed eight bodies ending in Chinese
punctuation, although all bodies retained the marker. Acceptance records both
the English and Chinese query routes and their union, without changing retrieval
ranking or claiming that either query alone finds every document. This existing
query-dispatch limitation remains open. OCR measurements cover three clean printed
Chinese/English images; they do not establish handwriting or noisy-scan accuracy.

See [ADR 0019](adr/0019-local-file-parsing.md) and the
[candidate review](superpowers/specs/reviews/2026-10-25-file-types-review.md).
Full project/time/topic browsing, automatic update triggers, representative course
validation, and group adoption remain separate work.

## Upstream choices

The initial GitHub comparison included
[python-calamine](https://github.com/dimastbk/python-calamine) and
[RapidOCR](https://github.com/RapidAI/RapidOCR). This candidate uses
[openpyxl](https://openpyxl.readthedocs.io/en/stable/) for the existing OOXML stack,
the Python standard library for MIME/mbox, and optional
[Tesseract](https://github.com/tesseract-ocr/tesseract) with
[pypdfium2](https://github.com/pypdfium2-team/pypdfium2) for offline printed-text OCR.
These choices avoid an additional inference service and preserve cached-formula
and mail-member behavior inside the existing ingestion transaction.
