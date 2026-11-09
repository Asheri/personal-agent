# Engineering requirement evidence

This matrix maps the reviewed specification to implementation and controlled
evidence. Candidate v1.8 awaits independent review. Existing environmental test
exceptions, historical real-model measurements, and unperformed human assessment
are disclosed separately; a source file or a skipped test is not a pass.

## Course requirements

| Requirement | Engineering state | Main implementation and checks |
|---|---|---|
| A1-1 to A1-7: local file types | Implemented, with declared optional OCR and legacy-format limits | `ingest/`, `tests/unit/test_extra_file_types.py`, `test_ocr_parsing.py`, mailbox/CLI integration; inherited v1.7 native OCR and 41-suffix acceptance. |
| A2-1 to A2-8: extraction/ownership | Implemented; quality remains controlled and provisional | `graph/extractor.py`, `projects.py`, personal extraction/project/grounding tests; inherited v1.6 real-model evidence with its five omitted authorship edges. Doctor lists ontology types. |
| A3-1 to A3-9: relations/versions | Implemented | `relate/`, `versions.py`, document relation/version/citation integration; scoped external alternate-read negatives. |
| A4-1 to A4-8: retrieval/answers | Implemented with explicit provider and community degradation | Retrieval stages and typed answer events; existing offline boundary, compression, citation, API/MCP tests; inherited controlled RAG/KG answers. The new boundary spike repairs single-query identifier coverage. |
| A4-9: document-date range | Implemented | `document_dates.py`, scope fields, 0012 backfill, date unit tests and `test_core_browse.py`; null-date rows survive range filters. |
| A5-1/A5-2/A5-5: facet partitions/nulls | Implemented | `browse.py` and `test_core_browse.py`: current scoped project/time sums, empty buckets, empty corpus. |
| A5-3: topic distinction | Implemented | Literal Topic evidence defines facets; communities only define overview and are suppressed under restrictions. |
| A5-4: pagination | Implemented for a fixed corpus | Date descending/nulls-last, ingestion descending, id; full traversal assertion. Concurrent mutation requires a new traversal. |
| A5-6: tags | Implemented | Independent manual/automatic scope fields and overlap checks. |
| A5-7: relation navigation | Implemented | Every browse document lists four relation entry types; CLI/REST/MCP relation reads reapply scope. |
| A5-8/A5-9: parity/empty corpus | Implemented | Shared facade, real REST versus registered MCP callables, and denied/empty arrays. External defaults are safe; parity compares the same effective rights scope. |
| A6-1 to A6-7/A6-9: incremental state | Implemented | Existing reconcile/version/mailbox tests plus durable refresh records, failure preservation, interruption recovery, and repeat-call checks. |
| A6-8: three trigger channels | Implemented and locally exercised | `refresh.py`, generated PowerShell launcher, unchanged upstream hooks/dispatch and scheduler protocol; busy exit 2 before writes. No persistent OS task is registered during tests. |
| A7-1/A7-2: freshness | Implemented | Access counts, lifecycle maintenance, 30-line hot index, preserved documents, and explicitly labeled expired version responses. |
| A7-3: five memory scenes | Implemented and exercised | Task start, retrieval, successful write, confirmed completion, scheduled maintenance; content-free operation log assertions. |
| A7-4: verified patches | Implemented | Managed/append memory patches archived; rules preserved, no source bodies/query/path logging. Failed tasks cannot create procedures. |
| A7-5: repeated-task procedure | Implemented as a bounded confirmed-template workflow | Three actual successful local retrieval tasks create an L3 procedure; a new router instance reuses it. No arbitrary model-learning claim. |

## Exact evidence boundaries

Full current-stage run receipts, JUnit cases, matched matrices, source hashes,
installation/seed hashes, polling measurements, and cleanup/package verification
are archived in `.context/core-completion-20261026/`. Its final verification
summary contains exact pass/failure/skip counts. Development failures remain
alongside corrected runs. Counts across overlapping suites are not additive.

Historical `.context/*` directories retain earlier 0011 and model/OCR evidence.
Those measurements belong to their original snapshots. This stage does not claim
to rerun native OCR or real-model extraction after their runtimes were cleaned.
Unchanged parser/model code has current regression checks; changed browsing,
scope, refresh, migration, and memory behavior has new local mechanism checks.

The unit suite retains identified Git-history/Windows-shell environment failures
under the repository's no-new-failure rule. This is an exception to a literal
all-green A1-7 statement, not hidden success. Rendered-site/browser tests may skip
without a site build; those skips are declared. Large-directory costs, handwriting,
representative private corpus quality, and live Agent model conversations remain
unclaimed. Private corpus selection and real provider credentials are deployment
configuration, not values an implementation author may invent.

## Excluded work

The user excluded independent review/adoption and course report/slides/demo
delivery. Optional P6 narrative/multimodal research remains outside the stated
course-engineering scope; it needs its own human-scoring protocol and cannot be
declared complete by mechanical tests. The candidate never approves itself or
relabels constructed repeated evaluations as independent course acceptance.
