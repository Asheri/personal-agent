# Personal extraction supplement, v1.3 candidate

This scoped implementation candidate supplements the pending v1.2 identity work.
The reviewed baseline remains v1.1 until a real nonauthor reviewer adopts a revision.
Scope: C-6/C-7, F2, A2-1 through A2-8, and current-evidence/transaction safeguards.

Revision 0009 supplies projects and document ownership, manual tags, and automatic
tags. Existing document data receives null ownership and empty tag arrays. Project
source is null exactly when project id is null; otherwise it is manual, rule, or
inferred. Safe rollback removes empty additions; nonempty project/tag data prevents
downgrade before destructive DDL. Deferred version constraints are validated before
schema changes when migrations share an open transaction.

Manual ownership and tags survive source revisions. Rules sort by descending priority
with declaration-order ties; first match wins and conflicting projects are reported.
Inference cannot replace manual/rule sources or create projects. It requires an
existing project, finite confidence at least 0.5, and a quote from the source head.
Invalid model results preserve prior state. Manual and automatic tags remain separate.

Exact-name enrichment appends method=exact receipts. Person source pointers remain
distinct from catalog authors. Rejection counters and domain digests make extraction
loss visible without logging contents. The implementation conservatively skips model
calls for unknown/restricted rights even on local endpoints. No implicit private-local
exception is introduced. Model responses cannot commit superseded graph evidence.

Correction to the old F2 rebuild sequence: graph gc is not a full ontology reset.
An explicit graph reset with confirmation clears derived graph rows and stamps while
retaining documents, metadata, and audit history, before extraction under the new
ontology. Runtime prompt completion makes the personal profile independently usable.

Acceptance uses real disposable PostgreSQL migrations and transaction tests, plus a
real local-model sample run. Sample labels are AI-authored and provisional; target
recall and visible evidence paths do not establish general quality or the specification's
larger-sample inference threshold. Browsing, scheduling, filesystem reconciliation,
and a representative human-reviewed course experiment remain open.
