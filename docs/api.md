---
title: REST, MCP, and Python API
description: Look up authentication scopes, endpoint shapes, streaming events, agent tools, error codes, and importable entry points.
---

# REST, MCP, and Python API

Run `sci-rag serve` to expose the REST and MCP interfaces backed by the shared service. Interactive OpenAPI documentation is available at `/docs`.

## Authentication

Send `Authorization: Bearer <key>`. If an upstream service claims that header, send `X-API-Key: <key>` instead. Cloud Run's frontend inspects `Authorization: Bearer` for its own identity tokens before the container receives the request, so deployed Cloud Run clients use `X-API-Key`. `X-API-Key` wins when both are sent, because the header a caller sets deliberately outranks one the surrounding infrastructure may have filled in.

The operator configures keys as a JSON map in `SCI_RAG_API_KEYS`:

```json
{"team-key":  {"scopes": ["retrieval:query", "retrieval:answer", "corpus:read"],
               "rate_limit_per_minute": 120},
 "agent-key": {"scopes": ["retrieval:query", "retrieval:answer", "byo_llm"]}}
```

| Scope | Grants |
|-------|--------|
| `retrieval:query` | `POST /v1/query`, and the MCP mount |
| `retrieval:answer` | `POST /v1/answer` (spends LLM tokens) |
| `corpus:read` | document catalog and `/v1/status` |
| `byo_llm` | may supply `llm_api_key` per request |

With no keys configured, the server runs **open** and warns loudly at startup; that is for localhost development only. `GET /health` and `GET /v1/corpus-manifest` never require auth.

## Errors

Every error is RFC 9457 `application/problem+json` with a stable `code` and request ID:

```json
{"type": ".../docs/api.md#invalid_key", "title": "Unknown API key",
 "status": 401, "code": "invalid_key", "detail": "", "request_id": "9f2c..."}
```

The same ID appears in the `X-Request-ID` response header. Send an ID in the request header to have it echoed, and quote it when asking an operator to find the call in logs.

A `500` never carries the exception message, query, or chunk text. It names the exception type and points to the logs.

Codes you can branch on:

| Code | Status | Meaning |
|------|-------:|---------|
| <a id="missing_key"></a>`missing_key` | 401 | No bearer token; `WWW-Authenticate: Bearer` is set |
| <a id="invalid_key"></a>`invalid_key` | 401 | Token not recognized |
| <a id="insufficient_scope"></a>`insufficient_scope` | 403 | Key lacks the required scope |
| <a id="rate_limited"></a>`rate_limited` | 429 | Over the per-key limit; honor `Retry-After` |
| <a id="invalid_request"></a>`invalid_request` | 422 | Body failed validation |
| <a id="document_not_found"></a>`document_not_found` | 404 | Unknown document id |
| <a id="llm_unavailable"></a>`llm_unavailable` | 503 | No LLM credentials configured server-side |
| <a id="generation_failed"></a>`generation_failed` | 502 | The model call failed |
| <a id="http_error"></a>`http_error` / <a id="internal_error"></a>`internal_error` | varies | Everything else, with the request id for the logs |

## REST endpoints

### POST /v1/query

Retrieval only: ranked evidence with full transparency, no generation.

```bash
curl -s -X POST localhost:8000/v1/query \
  -H 'Authorization: Bearer team-key' -H 'Content-Type: application/json' \
  -d '{"query": "biogas yield of pretreated rice straw",
       "top_k": 5, "profile": "deep",
       "license_classes": ["public", "open_commercial"]}'
```

Request fields:

* `query`, required.
* `top_k`, 1 to 50, default 8.
* `profile`: `interactive` (the default), `deep`, or `auto`.
* Per-layer overrides: `include_graph`, `include_community`,
  `include_hyde`, `include_rerank`.
* `license_classes` and `sources` allowlists. Omit them for all; an empty
  license list returns nothing by design.
* The metadata filters below.
* `include_content: false` for lean responses.

**Metadata filters.** `year_min`, `year_max`, `authors`, `journals`, and
`exclude_dois` narrow by publication metadata:

```bash
curl -s -X POST localhost:8000/v1/query \
  -H 'Authorization: Bearer team-key' -H 'Content-Type: application/json' \
  -d '{"query": "pretreatment of rice straw", "top_k": 5,
       "year_min": 2020, "journals": ["Biomass and Bioenergy"],
       "exclude_dois": ["10.1016/j.biombioe.2019.00000"]}'
```

Every layer enforces these filters in SQL before ranking, as it does license scope. An out-of-range document cannot displace an eligible one from a bounded pool. `authors` and `journals` require an exact whole-string match.

Any filter disables the community layer. A stored community summary aggregates evidence across documents before your scope is known, so nothing can filter it after the fact. The `community` trace reads `skipped` when this happens. `journal` comes directly from your manifest or refreshed from Crossref metadata with `sci-rag corpus enrich`.

The response contains `items`, `traces`, and `degraded_stages`. Each item has a title, section path, citation, license class, fused score, and `layers`. Each trace records the stage status and timing, including visible timeout information.

### POST /v1/answer

A grounded, cited answer. Two modes in one endpoint:

**Streaming (default).** `"stream": true` returns Server-Sent Events:

```
event: retrieval_started   data: {"profile": "deep"}
event: retrieval_done      data: {"item_count": 8, "degraded_stages": [], "traces": [...]}
event: compression_done    data: {"enabled": true, "prompt_tokens_before": 1408, "prompt_tokens_after": 462, ...}
event: generation_started  data: {"model": "gemini-3.6-flash"}
event: delta               data: {"text": "Given its ash content, ..."}   (repeats)
event: citations           data: {"citations": [{"index": 1, "title": "...", "cited": true, ...}]}
event: done                data: {"finish_reason": "stop"}
```

`finish_reason` is `stop` for a generated answer, `no_sources` when the allowed scope holds no matching material, `no_relevant_sources` when what was retrieved does not support an answer, and `retrieval_timeout` when evidence stages ran out of budget. The last carries `timed_out_stages`, which distinguishes an unreachable corpus from an empty one.

An `error` event (`code`, `message`) replaces the tail on failure.

**JSON.** `"stream": false` returns one body: `answer`, `model`,
`citations` (with a `cited` flag per source), `traces`,
`degraded_stages`, measured `prompt_tokens_before` and
`prompt_tokens_after`, plus compression failure and dropped-source counts.

Set `include_compression` to `true` or `false` to override the domain's `compression.enabled` setting. Compression scores chunks by relevance and summarizes them before prompt assembly. The shipped demo enables it after the judged-answer gate in [Evaluate your pipeline](evaluation.md). A new domain should run that gate before enabling it.

Failed, malformed, empty, duplicate, or over-budget model output falls back to the complete chunk and increments `compression_failure_count`. Evidence is never silently removed. Citations always keep the original document and chunk identity.

Known retracted documents are excluded from answers by default. The flag comes from explicit Crossref metadata written by `sci-rag corpus enrich`; missing enrichment does not imply retraction. Raw `/v1/query` retrieval keeps its previous behavior. To include retracted evidence when needed, use `sci-rag answer --include-retracted`.

**Bring your own key.** A request may include `llm_api_key` (an AI Studio key) if the API key holds the `byo_llm` scope. Operators can also bind an LLM key to an API key server-side. Either way, the credential is used for that call only and never stored or logged.

### GET /v1/documents and GET /v1/documents/{id}

The corpus catalog (scope `corpus:read`): paginated summaries with title, source, license class, authors, and counts. Filters: `search` (title substring), `source`, `license_class`. The detail view adds the formatted citation, source ref, and chunk previews.

### GET /v1/status, GET /health, GET /v1/corpus-manifest

`status` (scope `corpus:read`): counts of everything plus breakdowns by license, source, and embedding version. `health` (no auth): liveness plus a database check. `corpus-manifest` (no auth, deliberately): the machine-readable descriptor of this knowledge base. Includes domain, counts, embedding model and dimension, retrieval layers and fusion weights, endpoint URLs, and feature flags. A router in front of several sci-rag deployments reads this to decide which knowledge base fits a query.

## MCP

MCP exposes the corpus to agents through two transports:

* **stdio** (local agents): `sci-rag mcp`, or register with `claude mcp add my-corpus -- uv run --directory /path/to/repo sci-rag mcp`
* **HTTP** (remote agents): `POST /mcp/` on the running server, guarded by bearer keys (scope `retrieval:query`).

The eight tools:

| Tool | Use it to |
|------|-----------|
| `search_corpus(query, top_k, deep, license_classes, year_min, year_max, journals)` | get ranked evidence chunks to reason over yourself |
| `answer_question(query, top_k, license_classes)` | get a grounded answer with numbered citations |
| `get_document(document_id)` | inspect a cited source: metadata, license, chunk previews |
| `get_citations(document_id)` | follow its references and the corpus documents that cite it |
| `search_entities(name_contains, entity_type, limit)` | find knowledge-graph entities by name |
| `get_entity_relationships(entity_name)` | see every stated relationship of an entity, with evidence quotes |
| `list_sources()` | learn the corpus's source buckets and license mix |
| `corpus_stats()` | size and shape; a fast "is this corpus worth querying" check |

The server also exposes two resources: `corpus://manifest`, with the same payload as the REST manifest, and `corpus://methodology`, which explains retrieval. Tool descriptions are written for the agent that calls them.

## Generated clients

The running server publishes its schema at `/openapi.json`. Generate typed clients from that schema, for example:

```console title="Terminal"
$ uvx openapi-python-client generate --url http://127.0.0.1:8000/openapi.json
$ npx openapi-typescript http://127.0.0.1:8000/openapi.json -o sci-rag.d.ts
```

The first command writes an installable Python package; the second writes a TypeScript type file. Pass the key as `Authorization: Bearer <key>` or, behind Cloud Run, `X-API-Key`. Generated clients use the same authentication contract as `curl`.

## Python API

The CLI and server wrap importable components that also work in notebooks and custom applications. The package ships type information in `py.typed`.

```python
from sci_rag import Retriever, AnswerEngine, RetrievalScope

retriever = Retriever()  # settings from environment, domain from domain/
result = await retriever.retrieve(
    "rice straw availability",
    profile="deep",
    limit=5,
    scope=RetrievalScope(
        license_classes=("public", "open_commercial"),
        year_min=2020,
        journals=("Biomass and Bioenergy",),
    ),
)
for item in result.items:
    print(item.title, item.layers, item.score)

engine = AnswerEngine(retriever=retriever)
answer = await engine.answer("What biogas yield should I expect?")
print(answer.text, [s.citation for s in answer.cited_sources])
```

Ingestion, graph building, and evaluation are importable the same way (`ingest_entries`, `extract_graph`, `build_communities`, `run_retrieval_eval`). See `examples/library_quickstart.py` for a complete, runnable walkthrough.
