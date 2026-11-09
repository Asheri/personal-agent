# ADR 0016: Scoped document relations and evidence

Keep similarity, reference, revision, and project relations in their distinct stores
and expose one scoped service. This candidate remains pending nonauthor review.

## Context

Identity/version and project ownership were already implemented, but document similarity,
literal mention citations, and a unified Agent read path were absent. Cached Crossref
references alone do not establish local file links. An unfiltered corpus mean can let
hidden documents affect similarity scores even when final neighbors are filtered.

## Decision

Store uncentered document vector means with their embedding version in revision 0010.
Refresh them on ingestion/re-embedding and center only over visible same-version vectors
at query time. Reuse the existing citation table for explicit references with literal
keys, source chunks, and matching confidence. Resolve unique relative paths/names/DOIs,
retain unresolved keys, and prefer cached Crossref edges for the same pair. Builders
are local, explicit, transactional, and dry-run by default.

Use existing source revision and project fields for the other two views. New CLI/REST/MCP
entry points share scope conditions; both citation endpoints and its source evidence
must be visible. Existing citation reads receive the same scope/evidence guard. History
is explicitly requested by the versions operation. Do not enable retrieval citation
expansion or alter retrieval weights from relation-read tests.

The [pgvector reference](https://github.com/pgvector/pgvector/blob/master/README.md)
documents cosine similarity and grouped vector means. Retain the existing database and
provider stack instead of adopting another graph store, model, or runtime dependency.

## Consequences

The stored mean is derived data, never a semantic judgment. Visible-corpus centering
prevents hidden-vector influence but costs a scan of eligible document vectors. Explicit
syntax matching is conservative, supports only documented forms, and cannot disambiguate
duplicate titles. Evidence confidence is not factual entailment. Changed mention sets
must be rebuilt explicitly. Downgrade refuses to discard new relation data.

Actual database tests are authorized for this stage. Controlled vectors and mock model
interfaces establish mechanics, not real-world model accuracy. The previous Chinese
keyword and extraction-quality gaps remain. No external Agent instance is deployed.

## Reversal conditions

Add a vector index or materialized scope strategy only after measuring query cost and
preserving hidden-corpus isolation. Expand mention parsing only with explicit evidence
and ambiguity tests. Enable citation retrieval only after paired quality evidence.
Adopt a cross-kind view if a later relation type makes it necessary; do not duplicate
version or project authority into a generic edge table.
