# ADR 0019: Extend local parsing and write mailboxes atomically

Local file support needs both text extraction and correct document identity.
One mailbox can contain several independently versioned documents.

## Context

The earlier parser handled common documents but lacked XLSX, mail, code, text
data, and a controlled OCR route. A suffix-only change would miss mailbox
member deletion and allow partial host updates after embedding failures.

## Decision

Share discovery suffixes, add `parse_file_many`, retain the first-result API,
and reuse existing blocks, chunks, rights, versions, and writer locks. Use
openpyxl, safe text readers, standard-library mail parsing, and optional native
Tesseract/Pillow/pypdfium2. Retain 500 physical spreadsheet rows per sheet with
exact truncation metadata. Never evaluate code, formulas, or YAML constructors.

Write an entire mailbox in one transaction. Prefer Message-ID member identity;
otherwise use a content hash and duplicate occurrence count. Reject duplicate
Message-IDs and stale plans. Delete absent member chains with existing cleanup
logic. Record host member counts and aggregate digests. No new schema is needed.

Persist content-free per-parser source counts in CLI receipts. Probe PDF pages
for missing native text before accepting whole-document rich output.
Low-native-text image pages use explicit OCR before Docling, departing from the
original two-route low-text condition; these pages require the optional native
OCR runtime even if Docling is installed.

## Consequences

ID-less edits become remove/add operations, since ordinal identity cannot survive
both edits and arbitrary reordering. Code uses full source chunks plus compact
metadata instead of introducing separate vector and keyword representations.
Large CSVs and mailbox containers still consume memory. OCR is optional and
requires an installed native runtime and traineddata; clean printed samples do
not validate all image conditions. The existing mixed-language keyword dispatch
can miss identifiers next to Chinese punctuation on its English route.

The v1.7 candidate documents departures from the v1.1 specification and awaits
independent review. Earlier candidate stages and the reviewed baseline remain
historical records. Default domain files and schema revision 0011 are unchanged.

## Reversal conditions

Revisit the format boundary if representative files require legacy Office,
attachment documents, handwritten text, larger containers, or more exact language
parsing. Any identity change needs a migration plan and adversarial version/delete
tests. Separate compact vectors only after measured cost and retrieval evidence
justify that storage change. Preserve failed receipts before changing acceptance.
