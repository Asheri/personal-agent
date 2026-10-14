---
title: Extend the kit
description: Add a parser, corpus collector, reranker, model provider, or authentication backend at Sci RAG Kit's supported extension boundaries.
---

# Extend the kit

Choose one of five extension points: parser, corpus collector, reranker, model provider, or
authentication backend. Protect its existing behavior with tests, and measure any change to
retrieval. Sci RAG Kit does not use a plug-in registry.

<div class="srag-meta-strip">
  <div><strong>You'll build</strong>A new parser, collector, reranker, provider, or auth backend</div>
  <div><strong>You'll need</strong>A working checkout and its test suite</div>
  <div><strong>Time</strong>An hour to a day, depending on the extension</div>
  <div><strong>Tested with</strong>v0.5</div>
</div>

## Before you start

| Requirement | Why | Check |
|---|---|---|
| `make check` green on an unmodified checkout | Separates baseline failures from your change | `make check` |
| A read of [Architecture](architecture.md) | Places each extension point in the ownership map | |
| An evaluation baseline, for anything touching ranking | Makes the retrieval change measurable | `uv run sci-rag eval retrieval --ablation` |

## Choose an extension point

| Need | Contract | Primary file | Evidence to add |
|---|---|---|---|
| New document type | Produce the shared parsed block model | `src/sci_rag/ingest/parsers.py` | Parser and chunking tests with a fixture |
| New source system | Produce `CorpusEntry` values | `src/sci_rag/ingest/manifest.py` | Metadata, rights, pagination, and resume tests |
| New post-fusion ranking | Implement `Reranker` | `src/sci_rag/retrieve/rerank.py` | Failure fallback test and before/after ablation |
| New embedding or generation model | Implement `EmbeddingProvider` or `LLMClient` | `src/sci_rag/embed/`, `src/sci_rag/llm/` | Offline contract tests plus version and dimension checks |
| New identity system | Implement `AuthBackend` and wire the app factory | `src/sci_rag/server/auth.py` | Auth, scope, rate, REST, and MCP coverage |

## 1. Add a document parser

`parse_file()` dispatches by suffix and returns one `ParsedDocument`. Structured parsers produce ordered `Block` values: `heading`, `text`, or `table`. The chunker owns normalization, token sizing, overlap, and section breadcrumbs.

Uphold these properties:

- Report which route was used when a fallback changes fidelity.
- Keep tables as one block when possible.
- Do not repeat the document title in every section path.
- Fail with the supported list when the suffix is unknown, and reject blank text.
- Add a test with a fixture demonstrating block order and metadata.

Add the suffix to `SUPPORTED_SUFFIXES`, add a branch in `parse_file()`, and let the ingester handle deduplication, embedding, and transactions.

## 2. Add a corpus collector

A collector emits `CorpusEntry` records containing a local path plus source metadata:

```python title="src/sci_rag/ingest/manifest.py"
path: Path
title: str | None
authors: list[str]
year: int | None
doi: str | None
journal: str | None
url: str | None
license_class: str
source: str
```

Resolve remote bytes to stable local paths before ingestion. Normalize identifiers and retain provider source references. Rate-limit external APIs and make resume behavior explicit. If you cannot establish redistribution rights, leave `license_class` as `unknown`.

## 3. Add a reranker

`Reranker` is a structural protocol with one async operation:

```python title="src/sci_rag/retrieve/rerank.py"
class Reranker(Protocol):
    name: str

    async def rerank(
        self, query: str, items: list[RetrievedItem], *, top_k: int
    ) -> list[RetrievedItem]: ...
```

The orchestrator passes a wider fused pool and expects a reordered, truncated list. If the reranker raises an exception, leave a visible trace and fall back to the fused order. Add adapter selection to the domain tuning model only when projects need to configure it.

Do not enable a new reranker by default. Run `sci-rag eval retrieval --ablation` with and without it on your corpus, including latency and confidence intervals.

## 4. Add a model provider

An embedding provider exposes `version`, `dim`, and one batch method:

```python title="src/sci_rag/embed/provider.py"
class EmbeddingProvider(ABC):
    version: str
    dim: int

    async def embed(
        self, texts: list[str], *, task: EmbeddingTask
    ) -> list[list[float]]: ...
```

Stamp a provider-specific version whenever stored vectors become incompatible, and assert every returned dimension. Distinguish document and query tasks when the model supports asymmetric embeddings. Normalize vectors if the provider's reduced dimensions require it.

An LLM client implements full generation and streaming. JSON consumers use the shared `generate_json()` helper to request deterministic JSON mode and remove a surrounding code fence.

Provider additions need a deliberate selection path in `get_embedder()` or `get_llm()`. This factory keeps supported providers in one place.

### Generation providers that ship with the kit

Four provider choices live behind `src/sci_rag/llm/`, selected by a
`provider:model` spec. A bare model id uses `SCI_RAG_LLM_PROVIDER`; a prefixed
one overrides it. DeepSeek keeps its own key and endpoint while reusing the
OpenAI-compatible transport.

Install the shipped provider pair with
`uv sync --extra modelscope-embedding --extra openai`.

| Provider | Reaches | Credentials | Extra |
|---|---|---|---|
| `deepseek` (default) | DeepSeek chat models | `SCI_RAG_DEEPSEEK_API_KEY`; `SCI_RAG_DEEPSEEK_BASE_URL` defaults to `https://api.deepseek.com` | `openai` |
| `google` | Gemini | `SCI_RAG_GOOGLE_API_KEY` or `SCI_RAG_GCP_PROJECT` | built in |
| `anthropic` | Claude, on Vertex or the direct API | `SCI_RAG_GCP_PROJECT` (ADC) or `SCI_RAG_ANTHROPIC_API_KEY` | `anthropic` |
| `openai-compatible` | Vertex partner models (Grok, Llama, Mistral, DeepSeek), OpenAI, self-hosted vLLM/Ollama | `SCI_RAG_GCP_PROJECT` (ADC) or `SCI_RAG_OPENAI_API_KEY` (+ optional `SCI_RAG_OPENAI_BASE_URL`) | `openai` |

On Google Cloud, `openai-compatible` is the path to non-Google partner
models. Vertex serves them behind an OpenAI-compatible endpoint, so one
transport covers each supported model. Model ids keep their publisher prefix,
such as `xai/grok-4.1-fast-reasoning`; the adapter rejects a bare id.

!!! warning "Check model regions, including for Gemini"

    `SCI_RAG_GCP_LOCATION` defaults to `us-central1`, but a regional location does not serve every Google model. Gemini is served from `global`, and a deployed job calling it from `us-central1` gets a `404` on every batch. Claude and Grok also require `global`, and Grok is available only there. Set `SCI_RAG_GCP_LOCATION=global` unless you have confirmed your chosen model in your chosen region. Google embeddings work from `global` too, though slower than from a region.

    An unsupported location returns a `400`; a missing or unavailable model returns a `404`. `sci-rag doctor --probe` catches these before a pipeline run and recommends `SCI_RAG_GCP_LOCATION=global` for the location error. A `404` can also mean the model id is wrong or the project has not enabled that offering.

    Which models a project can reach depends on its Model Garden settings. Check the example ids above with `doctor` before using them.

!!! note "Partner model ids are dated examples"

    Partner models come and go on a schedule this project does not control. Every id here and in `.env.example` last answered both ordinary generation and strict JSON calls on **2026-08-30**, from `global`. Google publishes each model's lifecycle on [Vertex AI partner-models](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/partner-models).

    Verify your models before using them:

    ```console title="Terminal"
    $ make providers-check
    ```

    It calls each model at its documented location and fails when one no longer works. It needs `SCI_RAG_GCP_PROJECT` and application-default credentials. A model absent from your Model Garden also fails it.

### What a new adapter has to normalize

`LLMClient` presents one signature to every call site. An adapter absorbs the differences between providers:

| `generate()` argument | google | anthropic | openai-compatible / deepseek |
|---|---|---|---|
| `system` | `system_instruction` | `system=` | leading `system` message |
| `temperature` | forwarded | **dropped** | forwarded |
| `max_tokens` | `max_output_tokens` | `max_tokens` (required) | `max_tokens` |
| `json_mode` | `response_mime_type` + `thinking_budget=0` | `output_config={"effort": "low"}` | `response_format` |

Two mappings are tricky:

- **Current Claude models removed the sampling parameters.** Forwarding `temperature` returns a 400, so the Anthropic adapter drops it. Low temperature intent maps to `effort` instead.
- **Keep thinking enabled when lowering effort.** Disabling thinking on current Claude models can leak reasoning tags into visible text and corrupt the parsed JSON.
- **Not every Claude model accepts the effort knob.** `claude-sonnet-5` takes it; `claude-haiku-4-5` rejects it. The adapter probes once per client and remembers the result.

Where a provider may reject a knob, adapters retry once without it. Retry policy is shared: `retry_async()` in `llm/client.py` manages backoff. SDK clients are constructed with `max_retries=0` to prevent compounding retries.

### Embedding providers that ship with the kit

| Provider | Source | Credentials | Extra |
|---|---|---|---|
| `modelscope` (default) | Local `Qwen/Qwen3-Embedding-0.6B` downloaded from ModelScope | none | `modelscope-embedding` |
| `google` | Fresh projects use `gemini-embedding-001` at 1024 dimensions | `SCI_RAG_GOOGLE_API_KEY` or `SCI_RAG_GCP_PROJECT` | built in |
| `local-hash` | Deterministic lexical vectors for offline tests and dry runs | none | built in |

Install the default model stack with
`uv sync --extra modelscope-embedding --extra openai`.
ModelScope's official model record reports `SupportApiInference=false`, so the
adapter downloads the snapshot and loads it locally. See
[ADR 0012](adr/0012-modelscope-deepseek-providers.md) for the provider decision.

Changing the embedder requires a full re-embedding. A dimension change also
requires a schema migration because `SCI_RAG_EMBEDDING_DIM` is the pgvector
column width, and each chunk stores the `version` that produced it. The
shipped ModelScope model uses 1024 dimensions; [ADR 0002](adr/0002-embeddings-1536-hnsw.md)
keeps the HNSW limit and guardrails behind that value.

For an existing 1536-dimensional database, Settings restricts ModelScope
embeddings to 32 through 1024 and fails fast outside that range. Separately,
migration `0007` requires the current configuration to be between 32 and 1024
for every provider and fails fast outside that range. Old Google 1536 `.env`
must be changed to 1024 before `uv run sci-rag db upgrade`. Upgrade in this
order:

1. Back up the database.
2. Change `SCI_RAG_EMBEDDING_DIM` from 1536 to 1024 in `.env`.
3. Run `uv run sci-rag db upgrade`.
4. Run `uv run sci-rag embed reindex --dry-run`, inspect the stale chunk and
   community-summary counts, then run the same command with `--apply`.

Finish with `uv run sci-rag doctor`; it checks revision `0007`, both column
dimensions, and the stored embedding versions. `sci-rag embed reindex` writes
nothing until `--apply`, and it refuses a configured dimension that differs
from the live columns.

## 5. Add an authentication backend

`AuthBackend` has two synchronous operations: authenticate a bearer token into an `AuthContext`, and enforce its rate limit. The shipped factory selects open local mode or static JSON keys from `SCI_RAG_API_KEYS`.

To add OAuth or institutional identity:

1. Map external identity and claims to the existing scope vocabulary.
2. Implement `authenticate()` and `check_rate()`.
3. Wire the backend into the application factory to guard REST and `/mcp`.
4. Keep `application/problem+json` error codes stable.
5. Test REST and MCP access together.

`create_app()` builds the shipped backend from settings. Keep factory changes explicit, and never import arbitrary authentication code from configuration.

## Invariants for every extension point

- Apply rights scope and all other document conditions before the candidate limit.
- Record optional-component failures in the trace even when the request continues.
- Validate stored model output, dropping or rejecting unknown ontology values and malformed JSON.
- Add domain logic to `RagService` before exposing it through REST or MCP.
- Run tests offline by default and mark credentialed coverage with the `cloud` tag.
- Include ablation results with every retrieval change.

See [Architecture](architecture.md#extension-points-in-order-of-likely-need) for ownership, [Contributing](contributing.md) for the change bar, and [Evaluate your pipeline](evaluation.md) for the measurement workflow.

<div class="srag-checkpoint" markdown>
**Checkpoint: the extension passes**

Completion requires a green `make check`, an offline test that exercises the new code, and two ablation tables from the same corpus fingerprint when ranking changed.
</div>

## Next steps

- Produce the before-and-after your change needs: [Evaluate your pipeline](evaluation.md)
- Check the ownership map before broadening an interface: [Architecture](architecture.md)
- Read the bar a contribution has to clear: [Contributing](contributing.md)
