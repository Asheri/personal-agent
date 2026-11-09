# Office parser review handoff

- Date: 2026-10-21.
- Implementation: prepared with AI assistance for the user's DOCX/PPTX task.
- Independent reviewer: unassigned.
- Status: awaiting independent review. No approval or finding counts are asserted.
- Scope: spec section 4.1; A1-1 only for DOCX/PPTX, A1-2 for their tables, and A1-7 checks within this change. Full F1 acceptance remains open.

## Changes

`ingest/office.py` adds `parse_docx()` and `parse_pptx()`. `parse_file()` dispatches to them, and the shared suffix set enables discovery and manifest checks. The table renderer has an opt-in flag for retaining empty Office rows; its default HTML behavior is unchanged. The ingester preserves parser metadata in the existing JSONB field. Draft readers retain their old suffix list.

The `office` extra and development dependencies include python-docx and python-pptx. The lockfile is updated. Tests generate files at runtime. Two previous unsupported-file fixtures now use `.doc` because `.docx` is supported.

## Verification

Commands ran in the existing Python 3.12.10 environment. Exit codes are recorded separately from test counts.

| Command | Result | Exit code |
|---|---|---|
| `py -3.12 -m uv lock --check` | Lock matches; existing third-party versions retained | 0 |
| `py -3.12 -m uv sync --locked --extra office` | Office libraries installed | 0 |
| `.venv/Scripts/python.exe -m pytest tests/unit/test_office_parsers.py -q` | 43 passed | 0 |
| `.venv/Scripts/pytest.exe tests/unit -q --tb=short --junitxml=.context/office-parsers/final-unit.xml` | 1534 passed, 6 failed, 40 skipped; same failure set as before | 1 |
| `.venv/Scripts/ruff.exe check src tests examples scripts` | Passed | 0 |
| `.venv/Scripts/ruff.exe format --check src tests examples scripts` | 290 files formatted | 0 |
| `.venv/Scripts/mypy.exe --no-incremental` | One existing Google adapter type error under Office dependencies | 1 |
| `.venv/Scripts/mypy.exe --follow-imports=silent src/sci_rag/ingest/office.py src/sci_rag/ingest/parsers.py src/sci_rag/ingest/html_parser.py src/sci_rag/ingest/ingester.py src/sci_rag/draft/sampling.py src/sci_rag/draft/manifest.py` | No issues in the six changed source files | 0 |

Before changes, Ruff check and format passed; mypy passed for 115 source files. The unit baseline was 1491 passed, 6 failed, 40 skipped. Five failures require Git history missing from this ZIP checkout; one checks documented project/refresh/relate commands that are not implemented.

After installing Office dependencies, the unchanged original source also reproduces a mypy argument-type error in `src/sci_rag/embed/google.py:117`. Pillow makes the Google SDK image type concrete. This is separate from parser behavior; the Google adapter was left unchanged.

An isolated temporary PostgreSQL container on a dynamic loopback port ingested two generated files: 2 documents, 5 chunks, and 2 table chunks. Parser metadata, section paths, DOCX page count `None`, and PPTX page count 2 were checked. Both repeated ingestions were skipped. The existing `pcmem-demo` database was not used. The temporary container and its tmpfs data were removed after verification. The verification script exited 0; evidence is under `.context/office-parsers/` locally.

## Changed files

| File | Change |
|---|---|
| `src/sci_rag/ingest/office.py` | New DOCX/PPTX parsers and shared Office helpers |
| `src/sci_rag/ingest/parsers.py` | Suffix registration and dispatch |
| `src/sci_rag/ingest/html_parser.py` | Optional empty-row preservation in the shared table renderer |
| `src/sci_rag/ingest/ingester.py` | Preserve parsed metadata in the existing extra field |
| `src/sci_rag/draft/sampling.py` | Keep the previous drafting suffix list |
| `src/sci_rag/draft/manifest.py` | Apply that list before parsing draft inputs |
| `pyproject.toml`, `uv.lock` | Office extra and development test dependencies |
| `tests/unit/test_office_parsers.py` | 43 generated-file test cases |
| `tests/unit/test_licensing_and_manifest.py`, `tests/unit/test_manifest_lint.py` | Use unsupported `.doc` fixtures |
| `docs/bring-your-own-domain.md`, `docs/office-parsers.md` | Usage and limits |
| `AGENTS.md`, this review handoff | Scoped progress and pending review |

## Remaining limits and review questions

- Confirm stored-order DOCX/PPTX extraction and table escaping against the scoped requirements.
- Confirm metadata pass-through and reserved ingestion timestamp behavior.
- Confirm optional dependencies leave legacy formats usable, and draft readers keep their prior input scope.
- Review the documented heading-only behavior of the unchanged chunker.
- XLSX, OCR, email, parse_file_many, synchronization, privacy summaries, and per-parser failure totals are outside this subtask.
- No real model calls or course quality evaluation were performed.

The next teammate can install `uv sync --extra office` and use the existing parse or ingestion entry points. AGENTS.md section 5 requires an independent nonauthor review and an archived decision before merging this scoped implementation.

## P2 follow-up: single-row tables and textbox titles

This follow-up was prepared with AI assistance on 2026-10-21. Formal independent review is still pending.

- Office-only table rendering now adds the Markdown separator for one-row DOCX/PPTX tables. It preserves the real row, empty cells, escaping, and existing multirow behavior. HTML and the chunker are unchanged.
- PPTX keeps nonempty standard titles first. A conservative layout/font check can select one ordinary textbox above smaller body text. Uncertain layouts retain `Slide N`; the selected title is excluded from body extraction only once.
- Self-review reproduced a further ambiguity with a group or table above a possible textbox title. These nonempty shapes now block inference in that region, while their content is retained.
- Modified files: `src/sci_rag/ingest/office.py`, `tests/unit/test_office_parsers.py`, `docs/office-parsers.md`, and this handoff. No dependencies, schema, or other PC-Mem modules changed.

Before production edits, the original 43 Office cases passed, and all six known unit failures were rerun and reproduced. New table and title cases produced 10 failures before the fixes. Two upper-content ambiguity cases were also observed failing before their correction.

The 23 new generated-file cases cover six DOCX/PPTX single-row table variants and 17 title/layout cases. They assert exact table rows, escaping, empty cells, Chinese text, `is_table`, section paths, standard-title priority, title de-duplication, and retention of uncertain body text. Negative cases include unknown fonts, weak font contrast, rotation, multiline text, competing upper text, and upper groups/tables.

### Follow-up verification

Commands ran with the existing `.venv` executables on Python 3.12.10. Logs and before/after evidence are in `.context/office-p2-20261021/` locally.

| Command | Result | Exit code |
|---|---|---|
| `.venv/Scripts/pytest.exe tests/unit/test_office_parsers.py -q --tb=short` | 66 passed | 0 |
| `.venv/Scripts/pytest.exe tests/unit/test_office_parsers.py tests/unit/test_chunker.py tests/unit/test_html_parser.py -q --tb=short` | 105 passed | 0 |
| `.venv/Scripts/pytest.exe tests/unit -q --tb=short --junitxml=.context/office-p2-20261021/final-unit.xml` | 1557 passed, 6 failed, 40 skipped; same six failures as the pre-fix run | 1 |
| `.venv/Scripts/ruff.exe check src tests examples scripts` | Passed | 0 |
| `.venv/Scripts/ruff.exe format --check src tests examples scripts` | 290 files already formatted | 0 |
| `.venv/Scripts/mypy.exe --follow-imports=silent src/sci_rag/ingest/office.py` | No issues in the changed source file | 0 |
| `.venv/Scripts/mypy.exe --no-incremental` | Same single `embed/google.py:117` error as the pre-fix run | 1 |
| `.venv/Scripts/pytest.exe tests/unit/test_docs_style.py -q --tb=short` | 15 passed | 0 |

The full unit run took 311.09 seconds. Failure IDs match the pre-fix rerun exactly: five Git-dependent checks fail because this checkout has no Git history, and `test_every_documented_command_exists` still reports unimplemented project/refresh/relate commands. The full mypy output also matches the pre-fix output exactly. No new failure was found. The prior full unit result was 1534 passed, 6 failed, and 40 skipped; the increase is the 23 new Office cases.

The disposable database check ran `../../.venv/Scripts/python.exe verify_office_ingest.py` from `.context/office-p2-20261021/`, with environment variables pointing only to a new temporary PostgreSQL/pgvector container on a dynamic loopback port. It used `LocalHashEmbedder(64)` and generated files. The successful run exited 0: 2 documents, 5 chunks, and 2 single-row table chunks. Assertions checked exact stored table bodies, escaped pipes, an empty cell, visual/default section paths, no title repeated in the body, page counts, and two duplicate skips. The check accounts for the existing breadcrumb prefix in stored chunk content. An earlier check-script assertion omitted that prefix and was corrected before rerunning in a fresh temporary container. No production parser correction was needed for that assertion. Both task-owned containers and their tmpfs data were removed. The existing `pcmem-demo` database was not used.

A separate agent performed a read-only development review and found no remaining confirmed defect in these fixes. This is not the formal nonauthor review required by AGENTS.md section 5; a group member still needs to review and record a decision before merge. The checkout still has no Git history, and no repository was initialized.

Limits and the exact conservative title rules are described in `docs/office-parsers.md`. Theme-inherited font sizes, automatic wrapping, split/grouped visual titles, and complex layouts are not resolved by the new heuristic. Uncertain text remains body content under `Slide N`. This is still a DOCX/PPTX subtask; full F1 acceptance remains open.
