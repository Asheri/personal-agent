# PC-Mem identity and version contract, v1.2 candidate

- Date: 2026-10-24.
- Status: implementation candidate, pending independent nonauthor group review.
- Previous reviewed baseline: `设计方案-全PC文件记忆系统-spec.md`, v1.1.
- Proposed supersession: C-1 through C-5, the identity/version portion of section 3,
  and the current-version baseline in section 5.1. Other v1.1 requirements stay open.
- Affected acceptance: A3-6 through A3-8, A4-6, A6-2, and transaction interruption tests.
- This candidate and its implementation have no formal approval or merge decision.

## Identity and content

A source identity is the SHA-256 of UTF-8 JSON encoding
`[normcase(resolve(absolute_path)), source_member]`. Windows paths are case-insensitive;
POSIX paths follow the host filesystem. `source_member` is a stable string, empty for
ordinary single-document files. Canonical path and member stay in `Document.extra`;
`identity_key` is the indexed identity. Content hashes are never identities.

The existing `content_hash` normalization stays compatible with upstream fixtures.
It is a coarse comparison only. An unchanged decision also compares the ordered
parsed chunk text including breadcrumbs, section paths, and table flags. Case or
section changes therefore create a revision even when coarse hashes agree. Properties or container bytes that
do not change the parsed chunk representation do not establish a revision.

Different paths containing equal content remain separate current documents. An
A-to-B-to-A edit of one identity creates three rows, not a duplicate skip. Renaming a
file establishes another identity; cross-path version inference is outside this task.

## Storage and writes

Revision 0008 adds `identity_key`, `version_seq`, `version_of`, and `is_current`.
It replaces global content-hash uniqueness with:

- one current row per identity, through a partial unique index;
- unique `(identity_key, version_seq)`;
- a unique non-null predecessor reference, preventing forks;
- a deferred composite foreign key keeping predecessor and successor in one identity;
- positive revision numbers and a predecessor requiring a revision number above one.

No new projects, document-embedding, or file-event tables are claimed by this scoped
migration. The rest of the previously proposed M-0008-R work requires later migrations.

The ingester is the single revision writer for explicit ingestion. It locks document
writes, checks the current row, obtains embeddings, demotes and flushes the predecessor,
then inserts its successor and chunks in the same transaction. This flush order is
required by current-row uniqueness. Other readers see the previous committed state
until commit; interruption rolls back both changes. Revision numbers increase along
the retained chain, and an API-managed nonempty chain has exactly one current row.

The database lock also serializes deletion and community rebuilds. Explicit document
deletion reconnects surviving rows and promotes the last survivor, without renumbering.
Filesystem deletion, scheduler wiring, fingerprint skips, and automatic reconciliation
remain future work. The API does not claim zero parsing on repeated ingestion.

## Historical isolation

`scope_conditions()` includes `is_current=true` by default, independently of whether
rights restrictions are present. `is_unrestricted()` describes rights and metadata;
it does not exempt callers from the current-version baseline. An explicit Python
`RetrievalScope(include_superseded=True)` enables historical retrieval.

Vector, keyword, graph, and evidence resolution filter before bounded ranking. Graph
seeds, edges, citation neighbors, and candidate chunks must all have eligible evidence;
an old relationship cannot bridge two current documents. Default document reading,
catalogs, statistics, MCP graph inspection, drafting, extraction, and export follow
current evidence. Hidden predecessor ids and internal identity keys are omitted from
normal exports. Explicit unrestricted all-history export remains available in Python.

On revision advance, affected entity evidence is detached from the superseded source,
unversioned descriptions and aliases are cleared, and stored communities are invalidated.
Rebuilding communities uses eligible current evidence while holding the same writer
lock. Mixed or unattributed aggregate descriptions are hidden by default. Old document
rows and chunks remain available for explicit historical retrieval; historical graph
descriptions are not immutable graph snapshots.

Physical maintenance, garbage collection, embedding maintenance, and the existing
inventory fingerprint retain their administrative access to stored historical rows.
They are not answer candidates. The inventory snapshot contains counts and hashes,
not a database backup, and cannot restore deleted content.

## Migration and rollback

The upgrade supports a fresh database and revision-0007 data. Existing absolute paths
are normalized lexically from recorded metadata or `source_ref`, without reading the
source filesystem. Rows with one recorded identity form a chain ordered by ingestion
time, then id for deterministic ties. This order is reconstructed, not independently
verified edit history. Unresolvable paths receive isolated stable legacy identities.
Copies previously discarded by global deduplication cannot be reconstructed.

Revision 0001 uses live model metadata, so revision 0008 also handles columns and
constraints already created by a fresh install. Upgrade tests cover both paths.

Downgrade to 0007 succeeds only when data can be represented by the old schema: singleton
current roots with globally unique content hashes. If revisions or distinct source
copies would be lost, downgrade raises before altering columns or deleting rows.
Operators must keep a real database backup and choose an explicit conversion before
retrying. This replaces v1.1's automatic lossy collapse proposal. No destructive
conversion or production migration is part of this task.

## Acceptance evidence

Use generated local files, deterministic local embeddings, and a disposable PostgreSQL
with pgvector. Verify source copies, member identities, reverts, case and section edits,
interruption rollback, concurrent ingestion, uniqueness, deletion reconnection, historical
candidate limits, obsolete graph edges, aggregate invalidation, and both migration paths.
Results and commands belong in the dated development record; only a real nonauthor
group review can adopt this candidate as the reviewed baseline.
