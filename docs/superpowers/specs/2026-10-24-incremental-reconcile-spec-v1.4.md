# Incremental reconciliation supplement, v1.4 candidate

This scoped serial candidate adds on-demand F6 reconciliation to the pending v1.2/v1.3
implementations. The independently reviewed baseline remains v1.1. Adoption is pending.

Scope: C-1 through C-5, current-row metadata refresh, F6 on-demand ingestion/build,
and components of A6-1 through A6-7/A6-9. No full acceptance or A6-8 trigger claim.

The planner uses canonical absolute source paths and stored member identities. Existing
multi-member hosts are refused until supported parsing exists. A size/mtime hint plus
manifest/parser/chunking signature skips unchanged files. Ingest compares exact chunks,
updates metadata for equal content, or writes the checked predecessor/next revision in
one transaction. Source instability, stale plans, and failed processing retain old rows.

Only confirmed absent in-root identities can lose their full version chain. Existing
files omitted from a manifest, unknown paths, unavailable roots, replaced roots, and
permission failures cannot authorize deletion. Source-processing failures defer removal.
Source counts and database-only counts remain separate. Windows cloud placeholders are skipped.

The batch advisory lock pins its connection until release. Directory enumeration happens
before this lock. Existing single-writer locks remain responsible for corpus transactions.
No second state store or migration is added; file-event persistence and scheduler/hooks/
polling are later integration work. Current-row rights changes invalidate its graph data,
without rewriting historical rights metadata. Project classification remains explicit.

Supersedes the historical 2026-10-08 replacement/global-hash assumptions, not its historical
approval record. ADR 0013 is now occupied by this reconciliation decision; ADR 0012 keeps
its existing provider topic. Automatic global GC is excluded because current-evidence
filters already protect readers; explicit maintenance remains available.

At the user's request, this stage performs code/static checks without sample, model,
or database acceptance runs. Prepared integration tests remain unexecuted and cannot be
reported as passed. Real concurrent writers, interruption recovery, root/permission changes,
and full lifecycle behavior must be verified in a disposable PostgreSQL run before adoption.
