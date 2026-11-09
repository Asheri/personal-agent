---
title: Incremental source reconciliation
description: Reconcile file changes while retaining revisions and restricting missing-source deletion.
---

# Incremental source reconciliation

Run ingestion again to reconcile supported sources with their stored documents. This
implementation candidate has code-level checks; sample and database acceptance are deferred.

## Run on demand

```bash
sci-rag ingest YOUR_FOLDER
sci-rag ingest --manifest YOUR_MANIFEST.jsonl
sci-rag build YOUR_FOLDER --no-graph
```

Both ingestion and build now reconcile. In folder mode the root is the selected
directory; in manifest mode it is the manifest's parent. Folder inputs must exist,
directory traversal errors stop the scan, and symlink/junction directories are not
traversed. An empty existing folder can reconcile the last removed source. An empty
manifest still exits with its existing draft-manifest hint.

The first run after upgrade verifies legacy rows without fingerprints. Subsequent
unchanged files skip parsing and embedding when size, nanosecond modification time,
manifest metadata, and chunking/parser settings match. Stat fingerprints are hints:
edits deliberately preserving both size and mtime can be missed. Performance is not
measured on a representative corpus.

## Changes and failures

New sources are ingested normally. Changed sources retain earlier revisions and manual
ownership/tags. Exact parsed chunks are compared even when the coarse hash matches;
case or heading changes are not hidden by hash normalization. Equal chunks update the
fingerprint and declared metadata without embedding or creating a revision. Rights
changes invalidate derived graph evidence and extraction stamps for that current row.
Inputs describe a full metadata record, not a partial patch. Missing manifest fields
use their defaults, and switching to folder mode supplies unknown rights and empty
catalog fields. Keep a manifest when those declarations must be retained.

`PendingIngest` carries the selected predecessor and next sequence separately from
user-authored `CorpusEntry`. The ingester checks the plan under the existing writer
lock, along with source fingerprints before/after parsing, embedding, and final writes.
Stale plans and source/embedding failures preserve the existing revision transaction.
Historical rights metadata is not retroactively rewritten by a current-row metadata refresh.

Offline/cloud-recall placeholders are reported as `placeholder_skipped` without opening
their contents. Multi-member sources are conservatively refused until the multi-document
parser exists; no mail/archive support is claimed.

## Missing-source deletion

Only a recorded absolute source path inside the selected root can be removed. A URL,
relative path, or title is never guessed into a local path. A file merely omitted from
a manifest is preserved while it still exists. Permission errors do not prove absence.

Before deleting, the writer checks the root identity, source absence, and stored path
again under the transaction lock, then deletes the entire identity chain using the
existing corpus cleanup. Root replacement and source reappearance defer deletion.
Any source-processing failure defers all missing-source deletion for that run. Deletion
errors remain failures and do not trigger a broad cleanup of other identities.

Graph evidence and summaries are invalidated through existing lifecycle helpers. Empty
entities can remain for the explicit graph garbage collector; no automatic global GC
is added. Current-evidence filters exclude these entities from community construction.
Build keeps existing summaries when no graph change or newly extracted chunk is reported.
Automatic project/tag passes remain a separate `sci-rag project classify` command.

## Reporting and concurrency

Source-file outcomes and database-only outcomes are separate. Each selected input has
one source outcome. Database-only counts describe missing chains, out-of-root chains,
and untraceable rows; they are not counts of scanned files. A removal outcome includes
the number of removed revisions. `doctor` reports rows without recorded source paths.

A dedicated database advisory lock rejects a second reconcile before planning/writes;
CLI input enumeration precedes lock acquisition. The lock connection is pinned until
release, and connection invalidation releases it if cleanup fails. The existing writer
transaction lock still serializes mutations with other corpus writers. These mechanisms
await real PostgreSQL concurrency and interruption validation for this candidate.

Failure exits are 1; an already-running reconcile exits 2. Operational logs contain
counts and error classes, without source paths or exception contents. Direct CLI tables
display the source names the operator selected.

## Verification and remaining work

The user deferred sample testing on 2026-10-24. No model, database service, course files,
or end-to-end demonstration was run for this stage. Prepared integration cases cover
revision updates, zero-parse repetition, manual metadata, failed-update retention,
rights refresh, deletion boundaries, and lock contention; they are not passing evidence.
Run them only against an explicitly disposable database before adopting this candidate.

Scheduler/hooks/polling integration, durable file-event history, model-quality acceptance,
multi-member parsing, and nonauthor approval remain open. See [ADR 0013](adr/0013-document-level-reconciliation.md)
and the dated review handoff. This scoped change has no schema migration or new dependency.
