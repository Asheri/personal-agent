# Document relations: development verification handoff

- Date: 2026-10-25.
- Authoring: AI-assisted serial implementation.
- Nonauthor reviewer: unassigned; formal group review pending.
- Scope: F3, C-4 through C-9, schema 0010, CLI/REST/MCP relation reads.
- Status: candidate; no merge, adoption, or production deployment claim.

The user authorized a task-owned local PostgreSQL run after database tests were deferred
in the prior stage. All new data stays under D:/Codex and is removed after evidence
archival and service shutdown. No model is downloaded and no paid API is called.

Initial relation tests reproduce the legacy citation facade's absent scope argument.
The corrected read checks seed, both endpoints, source chunk ownership, and literal
evidence. Controlled vectors test ordering, same-version comparability, and lack of
hidden-corpus influence. Prepared and executed migration checks cover safe round-trip
and refusal before relation-data loss. REST and registered MCP tools share the service.

Actual commands, failures/retries, final counts, baseline comparison, schema tests, and
cleanup receipts are in `.context/document-relations-20261025/`. Previous stage results
remain historical; only current completed checks validate this candidate.

Review migration compatibility, citation pair/key deduplication and Crossref priority,
derived-vector refresh on source changes, scope before centering/ranking, explicit
history access, source deletion cleanup, and Agent-facing descriptions. Controlled
vectors and a mock answer engine are not evidence of real semantic or model accuracy.
Chinese retrieval, the previous extraction-quality gap, real Agent operation, and
automatic trigger integration remain open. A real nonauthor must record an adoption decision.
