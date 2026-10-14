---
title: "ADR 0012: ModelScope and DeepSeek defaults"
description: Why new projects default to local Qwen3 embeddings, native 1024-dimensional vectors, and DeepSeek generation.
---

# ADR 0012: ModelScope and DeepSeek defaults

New projects download Qwen3 embeddings locally from ModelScope, store native
1024-dimensional vectors, and call DeepSeek for generation with a dedicated
credential.

**Status:** accepted

## Context

The shipped defaults previously paired Gemini embeddings at 1536 dimensions
with Gemini generation. That made Google credentials the shortest path to a
semantic corpus, but it tied the base template to one hosted provider and
required model-backed embeddings to leave the machine.

The requested alternative has two different transport shapes. ModelScope hosts
the `Qwen/Qwen3-Embedding-0.6B` model record, but that record officially marks
`SupportApiInference=false`. The current implementation follows that record:
it calls `modelscope.snapshot_download()` and loads the snapshot through
Sentence Transformers as a local model. DeepSeek exposes an
OpenAI-compatible chat-completions API, which already matches one of the
kit's existing transports.

Embeddings also have a persistence constraint that generation does not.
`chunks.embedding` and `kg_communities.summary_embedding` are pgvector columns
whose width belongs to the schema. The prior 1536-dimensional columns cannot
hold native Qwen3 vectors, and mixing widths or truncating them silently would
make retrieval results impossible to reproduce.

## Decision

Make `modelscope`, `Qwen/Qwen3-Embedding-0.6B`, and 1024 dimensions the
defaults for new projects. Keep the heavy ModelScope and Sentence Transformers
stack behind `uv sync --extra modelscope-embedding`; download the model once
to the configured cache and run inference in the local process. Do not route
embedding through hosted ModelScope inference while the official record says
it is unavailable and the implementation is designed around local loading.

Add Alembic migration `0007` for existing installations. It backs the operator
into an explicit sequence: back up the database, apply the migration, rebuild
both vector columns and their HNSW indexes at the configured dimension, then
re-embed every chunk and community summary. The migration invalidates old
vectors before changing their width, so no query can compare vectors from
different dimensions.

Make `deepseek` and `deepseek-flash` the default generation provider and
model. DeepSeek reads `SCI_RAG_DEEPSEEK_API_KEY` and defaults to
`https://api.deepseek.com` through `SCI_RAG_DEEPSEEK_BASE_URL`. Its adapter
subclasses the OpenAI-compatible implementation, so streaming, JSON mode,
retry policy, request-level key overrides, and provider identity keep one
tested path.

Keep Google, Anthropic, the generic OpenAI-compatible provider, and
`local-hash` selectable. Google remains the hosted semantic option, Anthropic
remains a direct or Vertex choice, and `local-hash` remains the deterministic
offline test and dry-run floor. This supersedes the Google-only and
1536-default statements in the current-state sections of ADR 0002 and ADR
0006; their persistence and adapter-boundary reasoning still applies.

## Consequences

* A fresh installation uses
  `uv sync --extra modelscope-embedding --extra openai` for the default
  provider pair. The OpenAI extra supplies the shared DeepSeek client. A
  DeepSeek key is required for generation, but no Google credential is
  required by the default pair.
* The first embedding downloads a model and uses local compute. Device and
  cache location remain explicit settings, and `doctor` reports a missing
  extra with the exact install command.
* New schemas create both vector columns at 1024 dimensions. Existing
  1536-dimensional databases require backup, migration `0007`,
  `sci-rag embed reindex --dry-run`, `--apply`, and a final
  `sci-rag doctor` check of schema revision, column dimensions, and embedding
  versions.
* Reports continue to stamp provider, model, dimension, and version, so
  changing the default changes provenance instead of hiding it.
* Existing provider flags keep working. Removing them would turn a default
  change into a compatibility break for offline projects, Google Cloud
  deployments, and Anthropic users.

## Reversal conditions

Revisit this decision when one of these conditions holds:

* ModelScope officially enables hosted inference for the selected model and
  the project deliberately adopts a hosted embedding contract with equivalent
  availability, privacy, and provenance guarantees.
* A replacement default improves measured retrieval quality or operational
  cost on representative corpora under the same ablation protocol, and its
  dependency and migration costs are no higher.
* The supported model no longer natively produces at most 1024 dimensions, or
  pgvector's HNSW limit changes enough that the schema default should move.
  Reversal then needs a new migration and full re-embedding.
* DeepSeek's API stops matching the shared OpenAI-compatible behavior in a
  way that the existing extension boundary cannot express without weakening
  retries, JSON validation, streaming, or visible failures.
* Deprecating Google, Anthropic, generic OpenAI-compatible, or `local-hash`
  support has an explicit compatibility policy and migration path. The desire
  for a smaller provider table alone is not enough.
