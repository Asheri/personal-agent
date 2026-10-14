---
title: "ADR 0011: Commit benchmark graph replay evidence"
description: Why the synthetic demo benchmark replays one reviewed extraction draw instead of sampling a new graph for every run.
---

# ADR 0011: Commit benchmark graph replay evidence

The synthetic demo benchmark replays one reviewed graph-extraction draw so its published entity and relationship counts are reproducible on a fresh database.

**Status:** accepted

## Context

The benchmark page publishes entity and relationship counts for the tracked
synthetic demo corpus. Repeating graph extraction over the same recorded inputs
produced 83, 72, and 93 entities. Setting model temperature to zero did not make
provider output deterministic, so another machine could not reproduce the
published graph even when its corpus, domain profile, model, and source commit
matched.

Fresh databases added another source of drift. Extraction batches were ordered
by database document identifiers, which change when the same corpus is ingested
again. A repeatable replay first needs stable call inputs ordered by document
content hash and chunk index.

Running the model for every benchmark would keep sampling a new graph. An
ignored local cache would make one workstation repeatable but would not let CI
or another researcher verify the published counts. A product cache or replay
API would add persistence, configuration, and rights boundaries that ordinary
corpora do not need.

The bounded case is different. `data/demo/` contains tracked synthetic CC0
documents with `source=demo_fixture` and `license_class=public`. Their extraction
responses can be reviewed and redistributed with the template.

## Decision

Order extraction calls by document content hash and chunk index. Persistence
identifiers remain database-local and do not determine prompt grouping.

Commit one reviewed, content-addressed graph replay artifact under
`data/demo/graph-replay/`. The artifact records the corpus, extraction model,
domain, extractor contract, generation parameters, ordered call-input digests,
raw completions, expected counts, and canonical graph digest. It records no API
key and no full prompt. Raw completions are permitted only for the tracked
public `demo_fixture` corpus.

Replay stays behind `scripts/graph_replay.py`, which has three benchmark-only
modes:

* `require` validates artifact identity before graph work, constructs no real
  provider client, consumes every recorded call exactly once, and refuses any
  mismatch without a live fallback.
* `refresh` requires a pristine graph over only the public demo corpus, calls
  the configured extraction model, and writes a new content-addressed candidate
  atomically. It never overwrites approved evidence.
* `off` retains ordinary live extraction behavior without reading or writing a
  replay artifact.

The Makefile names the reviewed artifact through one explicit
`BENCH_GRAPH_REPLAY` path. `make benchmark` uses `require`; it never discovers an
artifact by timestamp, wildcard, or modification time. Credentialed refresh is
a separate `make benchmark-refresh-graph` target that prints a candidate path
and stops. Selecting that candidate requires a reviewed source change to
`BENCH_GRAPH_REPLAY`.

Every successful replay or refresh writes an ignored provenance receipt. The
benchmark renderer checks that receipt against the reports and published graph
counts. Entity and relationship deltas are exact failures once the graph is
pinned. Tolerances remain for measurements that are still stochastic.

This mechanism does not add product configuration, a database table, a public
CLI flag, a REST endpoint, an MCP tool, or a new dependency. Real corpora move
between machines through database backup and restore, and ordinary graph
extraction remains incremental and live. Generated projects that decline the
demo remove the replay artifact, script, Make targets, PHONY entry, architecture
record, and related references.

## Consequences

* A fresh database can reproduce the reviewed demo graph even when its database
  identifiers differ. A changed entity, relationship, evidence locator, or
  canonical graph digest becomes visible contract drift.
* The committed artifact adds raw model responses and couples the benchmark to
  an extractor contract. Contract, prompt, model, corpus, or domain changes
  require a new credentialed candidate and review.
* Refresh needs explicitly configured LLM provider credentials and a named pristine
  disposable database. It is a deliberate evidence-producing operation, not a
  routine CI step.
* The repository grows with reviewed replay evidence. Content-addressed names
  prevent a refresh from silently replacing the artifact behind a published
  benchmark.
* Committing raw completions is acceptable only because this corpus is
  synthetic and CC0. Candidate review must still check for credentials, full
  prompts, unexpected private content, and unreasonable size.
* Community summaries, answers, judges, HyDE, reranking, and routing remain
  outside replay. Their documented stochastic behavior and tolerances do not
  become deterministic by association.
* Missing, stale, reordered, partially consumed, or mismatched evidence stops
  the benchmark instead of falling back to a provider call.

The operational workflow and its published receipt are described in
[Benchmarks](../benchmarks.md).

## Reversal conditions

Revisit this decision if any of these conditions holds:

* Replay artifacts grow enough that tracked repository storage is no longer a
  reasonable distribution path.
* The project loses permission to redistribute any recorded input or output.
* A durable content-addressed service becomes available and preserves the same
  immutable identity, review, and offline verification guarantees.
* Measured, rights-safe demand justifies a product replay feature for real
  corpora rather than this benchmark-only path.
