---
title: "ADR 0002: 1536-dimensional embeddings"
description: Why vectors are truncated to 1536 dimensions, and what would happen to query latency without it.
---

# ADR 0002: 1536-dimensional embeddings

Embeddings are truncated to 1536 dimensions and re-normalized, so every vector column stays inside pgvector's HNSW index limit.

**Status:** accepted

## Context

Modern embedding models emit up to 3072 dimensions, and bigger sounds
better. But pgvector's HNSW index tops out at 2000. Give it a
3072-dimension column and it quietly falls back to exact scans, where
every vector query reads every row. At ten thousand chunks that is fine.
Past that it hurts, and it is the kind of slowdown nobody notices until
the corpus has already grown.

Models trained with Matryoshka representation learning, the default
`gemini-embedding-001` among them, are designed to be truncated: the
first N dimensions carry most of the signal, at a small and published
cost in quality.

## Decision

Default to 1536 dimensions, requested from the model via
`output_dimensionality`, with two guardrails:

* Re-normalize every truncated vector to unit length before storing it.
  Truncation breaks the unit norm that cosine ranking assumes.
* Check the configured dimension twice. The provider asserts it on every
  response and the database column enforces it on every insert, so a
  model or configuration mismatch fails at the source.

`SCI_RAG_EMBEDDING_DIM` sets the dimension, and a migration bakes it into
the schema. Changing it later takes a migration and a full re-embed. The
`embedding_version` stamp on every chunk is what makes the second half
tractable: the embedder re-runs only the chunks whose stamp no longer
matches.

## Consequences

* Vector search stays indexed as the corpus grows. The demo's ~2 second
  vector stage is connection and API latency, not scan time.

## Reversal conditions

* pgvector raises the HNSW dimension limit past 3072, which removes the
  constraint this decision exists to work around.
* An ablation on a real corpus shows the 1536-to-3072 quality gap
  mattering more than the exact-scan cost it would buy back. Measure it
  before assuming it.

Reversing means a migration, a full re-embed, and an index rebuild, so
the evidence has to be worth that.
