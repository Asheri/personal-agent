# ADR 0013: Document-level source reconciliation

Use stored fingerprints and the existing transactional writer to reconcile local files.
This candidate reserves the previously vacant reconciliation number without changing ADR 0012.

## Context

Ingestion reparsed unchanged files and never reconciled a deleted source. The old
2026-10-08 proposal assumed replacement deletion and globally unique content hashes;
the later identity/version candidate instead preserves revisions and equal-content copies.
Filesystem events alone do not maintain graph evidence and document version invariants.

## Decision

Implement an on-demand planner and a checked PendingIngest handoff. Reuse stat hints,
exact chunk comparison, PostgreSQL writer locks, existing JSON metadata, and corpus
deletion transactions. Include declared metadata and parsing/chunking options in the
skip signature. Recheck file stability and planned predecessors before version writes.

Missing-source deletion requires a stable existing root, a recorded in-root path,
confirmed absence, and a fresh locked identity check. Keep existing but unlisted files,
defer removal after processing failures, and report source and database outcomes separately.
Use a pinned PostgreSQL advisory lock for overlapping reconcile invocations.

[Watchdog snapshots](https://github.com/gorakhargosh/watchdog/blob/master/src/watchdog/utils/dirsnapshot.py)
provide a mature stat/diff reference; [CocoIndex](https://github.com/cocoindex-io/cocoindex)
provides an incremental pipeline alternative. Retain the existing stack because a new
pipeline still needs custom revision, rights, and graph cleanup integration. Add no
watcher, second state store, runtime dependency, or schema migration for this scope.

## Consequences

Unchanged sources avoid parsing, changed sources retain history, and absent in-root
identities can be removed without flattening versions. Same-size/mtime-preserving edits
can escape the hint. Metadata refresh changes only the current row. Multi-member files
remain unsupported. Explicit garbage collection can remove leftover empty entities.

Input enumeration precedes the reconcile lock. Source failures conservatively postpone
missing-file deletion. Database locks and transaction behavior need the deferred database
acceptance run; mock-only unit checks do not establish them. The user deferred sample
testing, and formal nonauthor review is pending.

## Reversal conditions

Reconsider a watcher only when measured polling cost or delay requires it. Adopt a larger
incremental framework only if it demonstrably reduces lifecycle code without weakening
graph evidence cleanup, source identity, or rollback. Revisit stat-only skips when measured
timestamp-preserving changes justify stronger source proofs.
