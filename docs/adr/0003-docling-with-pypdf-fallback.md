---
title: "ADR 0003: Docling for PDFs, with a pypdf fallback"
description: Why the best PDF parser is an optional extra and a smaller one is always available.
---

# ADR 0003: Docling for PDFs, with a pypdf fallback

Docling is the recommended PDF parser and an optional extra. pypdf is always available, and both routes produce the same block model.

**Status:** accepted

## Context

Scientific PDFs hide their best content in tables, and table extraction
is where cheap parsers fail. Docling (IBM's open-source document
converter) does genuine layout analysis and table-structure recognition,
and exporting its result to Markdown lets us reuse one battle-tested
block segmentation for every input route. The catch: it pulls a large ML
stack (multiple gigabytes with models), which would make `uv sync` and
CI miserable if it were a hard dependency.

## Decision

* Docling is the **recommended** PDF route, installed as an extra
  (`uv sync --extra docling`), and used automatically when importable.
* pypdf is the always-available fallback: raw text extraction feeding
  the chunker's heuristic segmentation. The parser logs which route ran,
  per file.
* Both routes, plus native Markdown, converge on one block model
  (headings, tables, prose), so downstream code has exactly one input
  shape.

## Consequences

* The base install stays light and CI stays fast; tests exercise the
  markdown and pypdf routes offline.
* A corpus ingested with pypdf will have worse table fidelity; the docs
  say so plainly and tell users when the upgrade is worth it.
* Docling API drift is contained to one function
  (`_parse_pdf_docling`), because everything after "export to Markdown"
  is ours.

## Reversal conditions

* Docling's install footprint drops far enough that carrying it by
  default stops being a tax on everyone who never opens a PDF.
* A lighter parser reaches Docling's table fidelity on scientific PDFs,
  measured on real documents and not on a vendor's benchmark.
* Docling's Markdown export changes shape often enough that containing
  the drift in one function stops being containment.
