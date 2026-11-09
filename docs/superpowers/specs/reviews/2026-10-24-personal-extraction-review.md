# Personal extraction: development verification handoff

- Date: 2026-10-24.
- Authoring: AI-assisted implementation.
- Nonauthor reviewer: unassigned; formal group review pending.
- Scope: C-6/C-7, F2, A2-1 through A2-8; scoped schema revision 0009.
- Status: candidate implementation; no merge, adoption, or production deployment claim.

The v1.3 candidate supplements the still-pending v1.2 identity candidate. ADR 0015
records the decision. The v1.1 approved text is preserved and receives only an appended
revision note. Human reviewers must record their identity and independent commands.

Initial regressions reproduce missing rejection counters and missing exact-name
audit receipts. Tests cover manual/rule/inferred priority, manual locks across revisions,
unknown projects, missing confidence, absent evidence, rule conflicts, rights gates,
separate tags, stale graph responses, ontology reset, and migration rollback guards.

Commands, actual final results, retries, baseline comparison, software versions, model
weights/runtime hashes, provisional sample labels, and raw synthetic model outputs are
in `.context/personal-extraction-20261024/`. Only the actual final records establish
passing checks. Earlier red runs remain evidence, including the missing personal
query prompt detected by the first real-model attempt.

An additional red/green regression covers scoped CJK graph seeds on a C-locale
database. Literal names must still occur in eligible source content. Same-corpus
eval diff isolates this fix with deterministic entity extraction; it is separate
from the real 3B trial, whose target recall is only 7/15 and whose project-name
query still returns no evidence. Neither result establishes representative quality.

Review ambiguous entity types and same-name people, metadata locks, quoted evidence,
invalid-response handling, source provenance, and the distinction between local model
inference and semantic embeddings. Review the confirmed ontology reset and loss-refusing
downgrade. The model sample is small and provisional and cannot replace course-quality
evaluation. Do not label the whole F2/course project complete from component test counts.

Reference investigated before implementation: [LightRAG source attribution and merging](https://github.com/HKUDS/LightRAG/blob/main/lightrag/operate.py).
The implementation retains the existing SQLAlchemy/PostgreSQL/provider stack.
