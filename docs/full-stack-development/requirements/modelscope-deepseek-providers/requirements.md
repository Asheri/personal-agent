# ModelScope Embedding and DeepSeek LLM Requirements

## Rough Request

Modify the project so embedding uses `Qwen/Qwen3-Embedding-0.6B` obtained from
ModelScope and generation uses a DeepSeek LLM.

Agent interpretation: add first-class provider support and make these providers
the shipped defaults while preserving Google, local-hash, Anthropic, and
OpenAI-compatible providers as selectable alternatives.

## Business Requirements

- A new project should work with ModelScope embeddings and DeepSeek generation
  without editing Python source.
- Credentials must remain environment-only and must never be logged or written
  to reports.
- Existing projects must retain a migration path for their current embedding
  dimension and model version.
- Retrieval scope, citation provenance, visible degradation, and offline test
  behavior must not change.
- Provider failures must remain visible through existing traces, error events,
  logs, and `sci-rag doctor`.

## Product Requirements

### Embedding

- Add `modelscope` to `SCI_RAG_EMBEDDING_PROVIDER`.
- Default to repository id `Qwen/Qwen3-Embedding-0.6B`.
- Download once through ModelScope and load through Sentence Transformers.
- Load the model once per process and run blocking download/inference outside
  the asyncio event loop.
- Apply the model's `query` prompt for query embeddings and its document
  behavior for document embeddings.
- Normalize vectors, assert the configured dimension, and stamp
  `embedding_version`.
- Support a configurable local device with a safe automatic selection.

### LLM

- Add `deepseek` to `SCI_RAG_LLM_PROVIDER`.
- Use `https://api.deepseek.com` as the default OpenAI-compatible base URL.
- Read a dedicated `SCI_RAG_DEEPSEEK_API_KEY`.
- Support `deepseek` in `provider:model` specs for answer, extraction, judge,
  HyDE, graph extraction, summaries, routing, and reranking call sites.
- Preserve streaming, JSON mode, retry behavior, BYO request keys, and
  provider/model identity in traces.
- Default to `deepseek-flash`; allow answer, extraction, and judge roles to
  override it independently.

## Data and Schema Requirements

- Qwen3-Embedding-0.6B supports at most 1024 dimensions, while the current
  default schema is 1536.
- The shipped default dimension becomes 1024 for new installations.
- Existing databases require an explicit Alembic migration for
  `chunks.embedding` and `kg_communities.summary_embedding`.
- The migration must invalidate old vectors before changing their width, then
  recreate the HNSW indexes. Existing corpus text and graph rows are retained.
- After migration, every chunk and community summary must be re-embedded with
  the Qwen model before vector retrieval claims completion.
- Provider, model id, dimension, and version remain part of the embedding
  fingerprint and evaluation provenance.

## API and Configuration Contract

New settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `SCI_RAG_EMBEDDING_PROVIDER` | `modelscope` | Select the ModelScope embedder |
| `SCI_RAG_EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | ModelScope repository id |
| `SCI_RAG_EMBEDDING_DIM` | `1024` | pgvector width and output dimension |
| `SCI_RAG_MODELSCOPE_DEVICE` | `auto` | `auto`, `cpu`, `cuda`, or `cuda:N` |
| `SCI_RAG_MODELSCOPE_CACHE_DIR` | unset | Optional ModelScope model cache |
| `SCI_RAG_LLM_PROVIDER` | `deepseek` | Default generation provider |
| `SCI_RAG_LLM_MODEL` | `deepseek-flash` | Default generation model |
| `SCI_RAG_DEEPSEEK_API_KEY` | unset | DeepSeek API credential |
| `SCI_RAG_DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek endpoint |

REST and MCP request schemas do not change. Corpus manifest, domain files, and
retrieval scope semantics do not change.

## Engineering Contract

- Reuse `EmbeddingProvider` and `LLMClient`; do not bypass either interface.
- Keep heavy ModelScope and Sentence Transformers dependencies behind an
  optional project extra so offline tests remain lightweight.
- Reuse the existing OpenAI-compatible protocol behavior for DeepSeek rather
  than duplicating streaming and retry logic.
- Keep tests offline by default. Mock ModelScope download/model inference and
  DeepSeek HTTP calls.
- Add focused unit coverage for provider selection, model-spec parsing,
  credentials, query/document prompts, normalization, dimension validation,
  streaming, JSON mode, and missing-credential errors.
- Add disposable-PostgreSQL migration coverage for 1024-wide vector columns and
  reindex refusal/completion across dimension changes.
- Add an optional credentialed smoke test for ModelScope download/inference and
  DeepSeek generation; it must skip without credentials or model access.
- Update `.env.example`, README, configuration reference, provider extension
  documentation, ADR, and troubleshooting guidance in the same change.

## Error Handling

- Missing DeepSeek key fails generation with actionable configuration guidance
  and never falls back silently to another provider.
- Missing ModelScope/Sentence Transformers dependency fails embedder creation
  with the exact installation command.
- Download or model-load failures are visible and do not leave partial vectors.
- Dimension mismatch is refused before embedding calls or database writes.
- Existing per-stage timeout and degradation semantics remain unchanged.

## Acceptance Contract

- `uv run ruff check src tests examples scripts`
- `uv run ruff format --check src tests examples scripts`
- `uv run mypy`
- `uv run pytest tests/unit -q`
- Disposable PostgreSQL integration tests prove the 1024 migration and
  dimension guard.
- Offline tests prove ModelScope and DeepSeek dispatch without network access.
- Optional live smoke tests prove one Qwen embedding batch and one DeepSeek
  completion when credentials and model access are available.
- No credential value appears in source, logs, reports, test snapshots, or
  documentation.

## Non-Goals

- No hosted ModelScope inference API; the ModelScope model record reports API
  inference unavailable, so this change uses local model loading.
- No change to retrieval weights, scope rules, answer prompts, ontology, or
  evaluation methodology.
- No automatic conversion of an existing corpus without an explicit migration
  and full re-embedding run.
- No removal of existing provider adapters.
