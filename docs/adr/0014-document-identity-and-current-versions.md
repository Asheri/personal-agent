# ADR 0014: Document identity and current revisions

Separate local source identity from content equality, retain revisions atomically,
and retrieve current evidence by default. This decision is pending group review.

## Context

The inherited ingester globally deduplicates normalized content. This collapses local
copies and skips a revert to an earlier version. The v1.1 proposal to make the same
content hash unique only among current rows still conflicts with preserving copies.
Current-only retrieval must also hold when a request has no rights filters.

## Decision

Use a canonical path/member identity, an indexed identity digest, and retained revision
rows. Keep content hashing as a coarse comparison and verify parsed chunk text and structure
before skipping. Serialize revision writes, deletion, and aggregate rebuilds using one
transaction advisory lock. Enforce one current row per identity and same-identity
predecessors in PostgreSQL. Demote and insert atomically, with current-row filters in
all normal evidence paths. Clear affected unversioned graph descriptions and invalidate
communities on revision advance.

Add the scoped 0008 migration; leave project, embedding, and file-event schemas to later
work. Refuse downgrade when the previous schema would discard history or source copies.
The existing inventory snapshot is not a database backup. This implements the v1.2
candidate at `../superpowers/specs/2026-10-24-identity-version-spec-v1.2.md`; group review
is pending, so this decision has no formal adoption claim.

## Consequences

Copies and reverts remain visible and traceable. Current readers cannot accidentally
serve historical chunks or old graph bridges. A failed write leaves the prior current
row intact. The global lock favors correctness for this single-user, serial workflow;
long embeddings or aggregate rebuilds can delay other writers. A revision may temporarily
reduce graph coverage until current content is extracted again. Historical document
content is retained; unversioned graph aggregates do not constitute a temporal graph.

Legacy edit order comes from recorded ingestion timestamps and deterministic ties.
Unknown paths remain isolated. Automatic file discovery and metadata-only refresh are
not delivered here. Production upgrades require review and a real backup; validation
in this change runs only on disposable data.

## Reversal conditions

Revisit the global lock if measured write contention becomes unacceptable. Revisit
path identity if explicit rename tracking or stable filesystem ids are required.
Introduce temporal graph storage only when historical graph facts must be reconstructed
without re-extraction. Revise rollback only with an explicit, tested data-conversion
policy. All such changes require a new review and must preserve historical decisions.
