# Office table escaping: development verification handoff

- Date: 2026-10-23.
- Implementation and verification: prepared with AI assistance.
- Formal independent group reviewer: unassigned.
- Status: development handoff; no formal approval is asserted.
- Scope: spec section 4.1, table-content portions of A1-2 and checks within A1-7.
- Full F1 remains open. The storage, versioning, and incremental-update work is unchanged.

## Change and regression evidence

`src/sci_rag/ingest/office.py` escapes source backslashes before escaping pipes.
The shared HTML renderer is unchanged. No schema, dependency, or model changes are needed.

The regression reads generated DOCX/PPTX files, renders the resulting Markdown with
the already locked markdown-it-py dependency, and compares every rendered cell with
the source rows. It checks single-row and multi-row tables, one and two backslashes,
mixed escapes, Windows paths, Chinese text, and empty cells. The resulting chunk
must retain its body, `is_table`, and `section_path`.

Before the source fix, the 20 new cases produced 16 failures and 4 passes.
The ordinary-pipe control cases passed. The failures demonstrate lost backslashes.
They do not establish a column-count defect in the original implementation.

## Reproduction and evidence

Use Python 3.12 and the unchanged `uv.lock`, with the `office` extra and development
dependencies. The enclosing handoff includes `task-env.ps1` to direct environment,
temporary files, and caches to D: and `run_check.py` to record exact commands.

Run the Office tests, related HTML/chunker tests, full unit suite, Ruff checks,
format check, scoped mypy, full mypy, and documentation style tests.
Exact command arrays, timestamps, exit codes, JUnit, and logs are stored under
`.context/office-escape-20261023/` in the completed handoff.
`verification-summary.json` is the machine-readable result and failure comparison.

The unmodified baseline on this machine has 1554 passes, 8 failures, and 41 skips.
Five failures require the missing Git history, one reports documented but
unimplemented commands, and two fail because this Git shell lacks `chmod`.
The full mypy baseline contains the existing `embed/google.py:117` argument-type error.
The 2026-10-21 counts remain historical evidence; the new run has its own baseline.

## Review and remaining work

AGENTS.md section 5 requires a real nonauthor group review before merging.
The next reviewer should inspect the code change, verify rendered cell values and
chunk metadata, reproduce the focused checks, and record their own identity,
commands, findings, and decision. AI development checks do not replace that review.

No database integration, external-model quality check, or full course acceptance
is claimed by this fix. The Office parser and chunker checks are offline.
Existing complex-layout limitations and title-only chunk behavior remain documented
in `docs/office-parsers.md`.

References: [markdown-it-py table splitting](https://github.com/executablebooks/markdown-it-py/blob/master/markdown_it/rules_block/table.py)
and [upstream table fixtures](https://github.com/executablebooks/markdown-it-py/blob/master/tests/test_port/fixtures/tables.md).
