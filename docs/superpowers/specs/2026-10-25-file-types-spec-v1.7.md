# Local file parsing candidate v1.7

This serial candidate implements the remaining scoped file families. The reviewed
v1.1 specification stays authoritative until a nonauthor approves these changes.

## Scope

Affected contracts: specification section 4.1/F1, C-1 composite identity,
C-11 document dates, the existing version/write lock contracts, and A1-1 through
A1-7. There is no parallel branch, project merge, or schema migration.

See [local file types](../../file-types.md) for suffixes, dependencies, exact
spreadsheet limits, OCR routing, failure behavior, and mail metadata. Parser
metadata is preserved in `documents.extra`; folder rights remain unknown.

## Explicit departures

- Replace no-ID mailbox ordinal fallback with content-hash/occurrence keys.
  A stateless ordinal cannot preserve identity after deleting/reordering members.
  ID-less edits are removal plus insertion; duplicate valid IDs reject the host.
- Retain full code in ordinary vector/full-text chunks and compact head/symbol
  metadata. Separate compact vector storage is deferred pending measurements.
- Store mail-derived dates in existing extra metadata. This stage does not claim
  the complete project/time/topic browsing implementation.
- Extend parser labels for the added formats. Keep the existing document schema
  and the narrower automatic manifest-drafting subset.
- Route low-native-text image PDF pages to the explicit OCR engine before
  Docling. This replaces the original requirement that both PDF routes be low;
  rich whole-document output cannot prove that every scanned page was read.
  These PDFs now require the configured OCR runtime even when Docling is installed.

## Acceptance

Generate fixtures for all 41 declared suffixes plus mixed PDF coverage; assert
42 sources become 44 documents, table chunks exist, every document retains its
body marker, and unchanged reconciliation makes no embedding calls. Record both
keyword query routes and their union. The first English-only query failed on
Chinese punctuation; this remains a documented retrieval limitation.

Pre-register a 0.90 minimum normalized character accuracy and 10-second maximum
per page before native OCR. Evaluate three clean constructed printed images.
Inject a fake OCR engine for deterministic metadata/page routing and unavailable
engine tests. Check XLSX exact truncation and missing formula caches. Check
mailbox member edits, deletion/reordering, stale snapshots, duplicate IDs, empty
hosts, and rollback after a mid-host failure. Check real CLI exit 1 and a durable
content-free parser receipt after a partial failure.

Run focused tests, full unit tests with no new failures/skips, integration/server
checks on an owned disposable database, Ruff, generated-reference checks, and
mypy compared to the known baseline. Archive evidence before stopping/removing
the owned database, native OCR runtime/data, installer cache, and temporary files.

## Adoption

The [review record](reviews/2026-10-25-file-types-review.md) is a pending template.
The author cannot approve it. This stage completes implementation and controlled
format validation, with the explicit limits above; it does not establish real
course-corpus quality or completion of all F1 research and performance work.
