---
title: FAQ
description: Short answers to what Sci RAG Kit is, who it is for, and why each design decision went the way it did.
---

# Frequently asked questions

Sci RAG Kit is for teams building a self-hosted knowledge base from scientific documents. Rights
controls and evaluation are built into the retrieval workflow.

## What this is

### What is Sci RAG Kit?

A project template for retrieval-augmented generation over scientific documents. Point a copy at
your documents to build a Postgres-backed knowledge base that answers with numbered citations to
the passages it used.

The kit parses PDF, HTML, Markdown, and text. It can build a knowledge graph from the domain
ontology, merge five retrieval layers, evaluate the results, and serve the same behavior through
REST and MCP. Postgres with pgvector stores the corpus and graph.

### Who is it for?

A scientific group that wants a reviewable knowledge base without assembling the storage,
retrieval, evaluation, and serving layers from separate components. The repository records the
reasons behind its architectural choices, and the operational data stays in one database.

A group building a bespoke retrieval application and wanting to make every architectural call itself is better served by a library. [Choosing Sci RAG Kit](choosing-sci-rag-kit.md) names the alternatives.

### Is this a library, a framework, or a template?

A template: a GitHub template repository that is also a working application. Adapt it through
`domain/`, the corpus manifest, and `.env`. The tree contains no template placeholders, and generated
projects keep the `sci_rag` import path. [Why use a template
repository?](#why-a-template-repository-and-not-a-cookiecutter) explains the choice.

### What does "scientific" buy me over a general RAG framework?

Scientific evidence is often numeric or tabular, questions may use different terms from their
sources, and a corpus can mix redistribution rights. The kit preserves table structure, combines
complementary retrieval methods, and applies license scope before ranking. [The
methodology](methodology.md) explains the design.

### How does it compare to LightRAG, PaperQA2, or LlamaIndex?

They assign different work to the project owner. LightRAG provides a configurable GraphRAG
implementation, LlamaIndex provides a framework and integrations, and PaperQA2 provides an agentic
workflow for scientific literature. Sci RAG Kit supplies an opinionated application template.
[Choosing Sci RAG Kit](choosing-sci-rag-kit.md) gives the dated comparison and decision conditions.

## Getting started

### What is the fastest way to try it?

Clone the repository and run the demo. In about ten minutes, with no credentials, it ingests five synthetic documents about agricultural residues, retrieves evidence for one question, and scores retrieval against the bundled test questions. To start a new project, run `pipx install sci-rag-kit` and then `sci-rag new`. The [quickstart](quickstart.md) covers both routes.

### Do I need Google credentials?

No. The default embedder downloads `Qwen/Qwen3-Embedding-0.6B` from ModelScope
and needs `uv sync --extra modelscope-embedding --extra openai`, but no cloud
credential. Generation defaults to DeepSeek and needs
`SCI_RAG_DEEPSEEK_API_KEY`; its default base URL is
`https://api.deepseek.com`. A Google key is an alternative credential and
does not switch generation by itself: also set `SCI_RAG_LLM_PROVIDER=google`.
Fresh Google projects use `gemini-embedding-001` with
`SCI_RAG_EMBEDDING_DIM=1024`. Google, Anthropic, and OpenAI-compatible
generation remain selectable. For a credential-free retrieval pass, set
`SCI_RAG_EMBEDDING_PROVIDER=local-hash`;
[changing persisted embeddings has its own migration
path](#why-can-i-change-the-llm-but-not-the-embedding-provider).

### Do I need Docker?

No. Pixi and conda install PostgreSQL and pgvector from conda-forge and use
`SCI_RAG_DB_BACKEND=local`. Docker remains the default for uv and venv + pip. The local backend can
also use an installed PostgreSQL 16 through 18 server, including Postgres.app, while Advanced setup
can retain the optional Cloud SQL development helper. [ADR 0008](adr/0008-supported-postgresql-versions.md)
records the supported range and [ADR 0009](adr/0009-cloud-dev-database.md) covers the Cloud helper.

### Do I have to clone the repository?

No. `pipx install sci-rag-kit` followed by `sci-rag new` fetches a pinned template tag and creates a
configured Git repository. Quick asks for six setup decisions; Advanced exposes the applicable
model, parser, retrieval, infrastructure, and licensing choices. Choose Offline when you do not
want to configure a model yet.

**Use this template** or cloning works too. Run `sci-rag init` inside that checkout. It configures the same files without downloading a template or running the credential check. Both routes start from the same tree and use the same appliers.

### Can I run it completely offline?

The shipped Offline mode supports ingestion, retrieval, and retrieval scoring without a model
call. It does not generate answers. Set `SCI_RAG_EMBEDDING_PROVIDER=local-hash`; an answer request
then reports that no model is configured.

## Why it is built this way

The linked decision records contain the full context, consequences, and reversal conditions.

### Why use Postgres for the knowledge graph? {#why-is-the-knowledge-graph-in-postgres-and-not-neo4j}

The graph traversal is a two-hop walk from seed entities to evidence chunks, which PostgreSQL can
run over indexed foreign keys. Keeping the graph with the corpus also preserves one transaction,
backup, migration, and access-control boundary. Deep path queries and centrality are out of scope;
export the graph tables if those needs arise. [ADR 0001](adr/0001-graph-in-postgres.md) records the
decision and its reversal conditions.

### Why are embeddings 1024 dimensions?

The default Qwen3-Embedding model natively produces 1024 dimensions, which
stays inside pgvector's 2000-dimension HNSW limit without truncation. A new
installation creates both vector columns at 1024. An existing 1536-dimensional
database needs migration `0007`, a full re-embedding, and an index rebuild;
[ADR 0012](adr/0012-modelscope-deepseek-providers.md) records the default and
its operational consequences. [ADR 0002](adr/0002-embeddings-1536-hnsw.md)
keeps the truncation and re-normalization rule for other models.

### Why is Docling an optional extra?

Docling has a large dependency footprint, so install it with `uv sync --extra docling` when its
structure-aware PDF parsing is needed. The base installation falls back to pypdf and records which
parser handled the document. [ADR 0003](adr/0003-docling-with-pypdf-fallback.md) explains the
tradeoff.

### Why use a template repository? {#why-a-template-repository-and-not-a-cookiecutter}

This repository remains runnable and testable before anyone generates a project. The generator
changes configuration in that working tree, which contains no placeholders. The tradeoff is less
parameterization at generation time. [ADR 0004](adr/0004-template-repo-not-cookiecutter.md) records
the alternatives.

### Why do citations get their own table?

Knowledge-graph edges connect typed entities and retain the phrase that states the relationship.
Citations connect documents through matched references. The `document_citations` table keeps those
semantics separate from entity extraction and community detection. [ADR
0005](adr/0005-citation-edges-as-a-document-table.md) gives the full rationale.

### Why hand-written provider adapters?

The shared `LLMClient` contract leaves provider-specific request construction
in small adapters. Four generation choices ship: `deepseek`, `google`,
`anthropic`, and `openai-compatible`. DeepSeek supplies its own key and base
URL but reuses the OpenAI-compatible streaming, JSON, and retry behavior from
the `openai` extra.
[ADR 0006](adr/0006-multi-provider-llms.md) explains the adapter boundary, and
[ADR 0012](adr/0012-modelscope-deepseek-providers.md) explains why DeepSeek is
the default.

### Why does changing the embedding provider require a migration? {#why-can-i-change-the-llm-but-not-the-embedding-provider}

Generation is request-time work, but embeddings are persisted data with a fixed database dimension
and model stamp. Changing the embedding model can require a schema migration, full re-embedding,
and index rebuild. For the shipped 1536 to 1024 change, Settings restricts
ModelScope embeddings to 32 through 1024. Migration `0007` separately requires
the current configuration to be between 32 and 1024 for every provider. Back
up the database. Old Google 1536 `.env` must be changed to 1024 before
`uv run sci-rag db upgrade`. Review
`uv run sci-rag embed reindex --dry-run`, run it again with `--apply`, and
finish with `uv run sci-rag doctor`. Doctor verifies migration revision `0007`,
both 1024-dimensional columns, and the stored embedding versions. [ADR
0006](adr/0006-multi-provider-llms.md) defines why embeddings are a data
operation; [ADR 0012](adr/0012-modelscope-deepseek-providers.md) records the
new default and its reversal conditions.

### Why does the generator configure files in place?

`sci-rag new` downloads a pinned repository tag and changes its configuration files. This keeps the
template itself browsable, runnable, and subject to the application's tests. [ADR
0007](adr/0007-interactive-project-generator.md) describes the generator contract.

### Will `--template-path` copy my credentials into a new project?

No. A local template copies only Git-tracked files, excluding ignored `.env` files, proxy
credentials, virtual environments, and Terraform state. An untracked source directory uses a
deny-by-default rule for hidden files. [ADR 0010](adr/0010-template-copy-boundary.md) specifies the
copy boundary.

### Why commit model output for the demo benchmark?

Because a live extraction call can produce a different graph from the same
corpus, model, and prompt. The benchmark needs one reviewed graph draw that a
fresh database can reproduce without another provider call.

The committed replay artifact is limited to the tracked synthetic CC0 demo. It
stores raw completions with content, model, prompt-input, and graph-output
digests, then strict replay sends them through the normal parser and persistence
path. Any mismatch stops the benchmark. General caches remain local and ignored,
and real corpora still move between systems through database backup and restore.

Full argument and reversal conditions: [ADR 0011](adr/0011-committed-benchmark-graph-replay.md).

### When should I use local PostgreSQL, Cloud SQL, or Docker?

Use Docker for the template default, local PostgreSQL when a supported server is already available,
or the Cloud SQL helper when workspaces need isolated databases on a shared managed development
instance. The Cloud route uses the Cloud SQL Auth Proxy and has higher round-trip latency. Use it
only for development. [ADR 0009](adr/0009-cloud-dev-database.md) defines the safety
boundary.

### Why support three PostgreSQL majors?

Docker and CI exercise PostgreSQL 16, while the current conda-forge development path exercises 18.
The supported range is PostgreSQL 16 through 18. [ADR
0008](adr/0008-supported-postgresql-versions.md) defines how that range is tested and updated.

## Retrieval and answers

### Why five retrieval layers? {#why-five-retrieval-layers-is-vector-search-not-enough}

The layers cover different retrieval signals. Vector search handles semantic similarity, keyword
search retains exact terms, graph traversal follows concepts up to two hops, community summaries
provide corpus-level context, and hypothetical-answer search bridges question and document wording.
The `interactive` profile uses vector and keyword retrieval; `deep` enables all five.

### Why merge by rank? {#why-merge-by-rank-and-not-by-score}

Each layer scores results on a different scale, while rank gives them a shared ordering. Each layer contributes
`weight / (60 + rank)` per passage. The shipped starting weights are vector 1.5, keyword 1.0, graph
0.8, community 0.6, and hypothetical answer 1.2. Treat these values as starting points and use the
[evaluation workflow](evaluation.md) before changing them for another corpus.

### What is HyDE, and why is it never cited?

HyDE (hypothetical document embeddings) has a model write a short passage describing what a real document would say if it answered a question. The kit then searches near that passage. This search probe never appears in citations. The domain profile can steer its style per question class.

### Why is the reranker off by default?

Two reranking adapters ship: one uses the configured model, and one uses a local cross-encoder
behind the `rerank` extra. The shipped profiles leave reranking off until a `with_rerank` against
`no_rerank` comparison justifies the added latency for that corpus. The shipped demo enables answer
compression at a relevance floor of 0.0 based on a separate gate. [Benchmarks](benchmarks.md)
publishes the runs.

### Why does the community layer skip my query when I filter?

Because a community summary was written from several documents before anyone's scope was known, and the prose cannot be separated afterward. When a request restricts license classes, sources, documents, or retractions, the layer reports `skipped` and the other four layers apply the scope inside their own queries.

### Why does it sometimes refuse to answer?

The answer prompt requires numbered citations, preserves source numbers and units, and reports when
the retrieved evidence does not answer the question. Real evaluation sets keep at least one
`unanswerable` question so this behavior is measured.

## Rights and evidence

### Can I use this on papers I hold but may not redistribute?

The kit can classify a document as `restricted` and expose it only to callers whose scope allows
that class. You remain responsible for having the right to ingest and use the document. The
manifest taxonomy supports runtime filtering; consult counsel for legal guidance. The available classes are `public`, `open_commercial`,
`open_noncommercial`, `restricted`, and `unknown`. Every retrieval layer applies scope before
ranking. [Scope precedes ranking](methodology.md#7-scope-precedes-ranking) defines the contract.

### Why does an empty license allowlist return nothing?

Because "allow nothing" and "no restriction" are different requests. `license_classes=None` means the caller did not restrict by license. `license_classes=()` means the caller allows nothing, and retrieval returns nothing before any embedding call or database query. Reading an empty list as "no restriction" would be an invisible failure.

### Why is `unknown` treated as unsafe?

Missing or unrecognized license metadata normalizes to `unknown`, which is included only when a
caller explicitly allows it. Publicly accessible services allow only `public` and
`open_commercial` by default. Campaign discovery follows the same normalization rule.

### Why does the grader never see the reference answer?

Because a grader that sees the expected answer rewards agreement with it, including agreement the cited sources do not support. Grading runs in two passes. The first sees the question, the answer, and the retrieved sources, and scores grounding, citation accuracy, and completeness. The second compares the answer to the reference without the sources and scores correctness. Both run at temperature 0, and a malformed grader response is recorded as a failure, never coerced into a score.

## Scale, cost, and operations

### How large a corpus can this handle?

The repository does not publish a universal corpus ceiling. Capacity depends on document size,
chunk count, graph density, query mix, database resources, and latency targets. The current graph
decision should be revisited at millions of entities or when requests need three or more graph hops.
Measure the full ingest and query path on a representative corpus before committing to a deployment
shape. [ADR 0001](adr/0001-graph-in-postgres.md) records that threshold.

### What does it cost to run?

Cost depends on the database, corpus size, selected models, and retrieval profile. Offline mode avoids
model calls. The Terraform development helper currently configures `db-g1-small` for development.
The `interactive` profile uses one query embedding; `deep` can
add generation calls for graph extraction and hypothetical-answer retrieval. Consult current
provider pricing and destroy temporary infrastructure with `terraform destroy`.

### What happens when a retrieval layer times out?

It contributes no candidates, the request continues, and the trace says `timeout`. Each layer runs as its own task with its own database session and timeout. Traces carry stage, status, duration, and counts, never query or passage text, so they are safe to log.

## Extending and adapting

### Can I add my own parser, reranker, or model provider?

Yes. The public contracts for the supported extension points are:

| Need | Contract | Primary file |
|---|---|---|
| New document type | produce the shared parsed block model | `src/sci_rag/ingest/parsers.py` |
| New source system | produce `CorpusEntry` values | `src/sci_rag/ingest/manifest.py` |
| New post-fusion ranking | implement `Reranker` | `src/sci_rag/retrieve/rerank.py` |
| New embedding or generation model | implement `EmbeddingProvider` or `LLMClient` | `src/sci_rag/embed/`, `src/sci_rag/llm/` |
| New identity system | implement `AuthBackend` | `src/sci_rag/server/auth.py` |

Anything that changes ranking owes a before-and-after evaluation. [Extend the kit](extend.md) is the walkthrough.

### Is there a plugin system?

No. There is also no task queue, cache service, vector-store sidecar, or graph database. Small
factories select the supported implementations, and a new generation provider belongs behind the
existing `LLMClient` contract.

### Can I rename the Python package?

It's possible, but derived projects keep the `sci_rag` import path. Renaming buys nothing functional and costs the ability to diff a project against the upstream template and pull improvements. `sci-rag init` and `scripts/init_domain.py` set the project name and description without touching the import path.

### How much of this should I change?

Start with `domain/`, the corpus manifest, and `.env`. Use the extension contracts above when the
project needs a new parser, source, reranker, model provider, or identity system. Retrieval changes
need a before-and-after evaluation, and rights scope must remain inside every layer's query.

## The project

### Is this production ready? What does 0.x mean?

It is alpha. During 0.x, minor releases may contain documented breaking changes with migration
notes, while patch releases preserve compatibility. Schema changes use forward migrations, report
JSON changes are additive, and older 0.x domain profiles remain supported. The contract covers the
documented Python exports, CLI, REST and MCP surfaces, `domain/` format, and report keys.
[Versioning](VERSIONING.md) lists the complete policy and the conditions for 1.0.

### How do I cite it?

Cite the software title, the version or exact Git commit, the repository URL, and the access date. There is no archival DOI yet. A software citation alone does not identify a retrieval experiment, so also report the corpus snapshot and digest, the license scope, the model identifiers, the domain profile, the enabled layers, and the question set. [How to cite](project.md#how-to-cite) has the BibTeX.

### Who maintains it, and how are decisions made?

The Sustainability Software Lab at Berkeley Lab maintains it. Code-level decisions happen in pull requests and resolve by evidence. Architecture decisions get a decision record. Direction-level proposals start as a GitHub Discussion and become a record plus issues when they converge. [Governance](GOVERNANCE.md) has the roles.
