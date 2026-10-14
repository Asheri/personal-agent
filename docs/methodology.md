---
title: Methodology
description: Read the specification behind chunking, graph extraction, fusion, answer generation, and evaluation, with the reasoning for every choice.
---

# Methodology

Methodology defines how Sci RAG Kit handles chunking, retrieval, scope, answer generation, and
evaluation. Use it to review the design for a domain or describe the method in a paper.
[Architecture](architecture.md) maps each stage to the code that owns it.

The kit combines hybrid retrieval over Postgres, a knowledge graph built from a user-defined
ontology, fail-closed license scoping, and evaluation designed to resist inflated results.

## Why this shape {#1-why-this-shape}

Three properties of scientific question answering shape the design:

1. **The evidence is numeric and tabular.** The answer to "What yield should I expect?" requires the exact table row and its units. Chunking that shreds tables, or retrieval that cannot find the number's context, produces confident, wrong answers.
2. **Questions and documents use different words.** A user asks "how much straw does the county produce"; the document says "141,000 harvested acres at a 1.1 straw-to-grain ratio". Keyword search can miss this relationship, while embedding search can blur the specific numbers.
3. **Corpora mix redistribution rights.** A lab's document pile mixes public reports, CC-BY papers, and paywalled PDFs it may hold but not redistribute. A RAG that quotes retrieved text **is** redistribution, so rights have to be a first-class property of every retrieval layer.

These constraints motivate the choices below.

## One database {#2-one-database}

Text, chunks, embeddings, full-text indexes, the knowledge graph, and licensing metadata all live in a single PostgreSQL database with the pgvector extension. No separate vector store. No graph database either.

A dedicated graph database supports deep traversal, but this kit stops at two hops. See
[Knowledge-graph traversal](#6-3-knowledge-graph-traversal).
Keeping the graph with its evidence gives the project one backup, migration path, and access-control
surface. It also keeps a chunk and its graph entries transactionally consistent. Projects that
need deeper traversal or live graph analytics can replace the graph stage behind the retrieval
facade.

## Ingestion {#3-ingestion}

Every document follows the same pipeline, in order:

```
parse -> chunk -> classify license -> deduplicate -> embed -> store (one transaction)
```

* **Parse.** PDFs go through a structure-preserving parser (Docling when
  installed, pypdf as the fallback). Markdown parses directly. HTML goes
  through the standard library's parser, which drops page chrome (`nav`,
  `header`, `footer`, `aside`, scripts and styles) so a shared sidebar does
  not become the most repeated text in the corpus, and renders tables as pipe
  tables so they take the same path a Markdown table does. Plain text passes
  through. All routes produce the same block model: headings, tables, and
  prose.
* **License.** Each document carries a redistribution class declared in
  the corpus manifest: `public`, `open_commercial`, `open_noncommercial`,
  `restricted`, or `unknown`. Nobody said otherwise means `unknown`, and
  the kit treats `unknown` as unsafe. See [Scope precedes ranking](#7-scope-precedes-ranking).
* **Deduplicate.** Content identity is a SHA-256 over the normalized
  chunked text, and a unique constraint enforces it. Re-ingesting a file, or
  the same content under a new filename, is a no-op.
* **Store transactionally.** A document and all its chunks commit
  together or not at all; a crash cannot leave half a document behind.

## Structure-aware chunking {#4-structure-aware-chunking}

A generic recursive text splitter throws away the two most valuable
signals in technical writing: where a statement sits in the section
hierarchy, and whether a table survives intact. The chunker keeps both:

1. Normalize the raw text: form feeds, stray page-number lines,
   end-of-line hyphenation ("ligno-\ncellulosic" becomes
   "lignocellulosic"), null bytes.
2. Segment into paragraphs; drop fragments under 20 characters (almost
   always extraction noise).
3. Detect headings three ways: numbered ("2.1 Feedstock handling"), ALL
   CAPS, and short Title Case lines. Maintain a section path such as
   "2 Methods > 2.1 Feedstock handling".
4. Detect table-like paragraphs (pipe tables, tab columns, aligned space
   grids) and emit each table as its own intact chunk, flagged
   `is_table`.
5. Merge ordinary paragraphs up to a target of **800 tokens**, splitting
   oversized paragraphs on sentence boundaries, and never merging across
   a section boundary.
6. Carry roughly **150 tokens** of trailing overlap into the next prose
   chunk (tables hand over at most their last two rows), and never carry
   overlap across a heading.
7. Prepend the document title and section path to every chunk, so each
   chunk embeds and reads sensibly on its own.

The 800-token target and 150-token overlap are configurable.

## Embeddings {#5-embeddings}

* One embedding model per corpus, with the model identity stamped on
  every chunk (`embedding_version`). A model upgrade is then a findable
  migration ("re-embed rows whose version is stale"), never a silent
  mixture of incompatible vectors.
* The default dimension is **1024**, produced natively by the ModelScope Qwen3
  model. That keeps vectors inside pgvector's 2000-dimension HNSW index limit,
  so nearest-neighbor search uses the HNSW index. Google remains optional;
  when selected, Matryoshka-capable models may request a reduced dimension and
  the embedder re-normalizes truncated vectors to unit length before storage.
* The embedder asserts the returned dimension on every call. A
  model/configuration mismatch fails before retrieval begins.
* ModelScope uses the `query` prompt for queries and no prompt for documents.
  Google uses `RETRIEVAL_QUERY` and `RETRIEVAL_DOCUMENT`. This provider-specific
  asymmetry is what lets the same words encode differently on each side of the
  search. Interactive query embeddings cache briefly in process memory under
  hashed keys, and the raw query text is never a cache key.

## Retrieval pipeline {#6-the-five-retrieval-layers}

Five candidate generators run concurrently where their dependencies allow. Each owns a database
session and timeout, and their ranked lists fuse once.

### Dense vector search {#6-1-dense-vector-search}

Cosine similarity over chunk embeddings, served by HNSW. The workhorse;
carries the highest fusion weight.

### Keyword full-text search {#6-2-keyword-full-text-search}

Postgres full-text search over a generated `tsvector` column (GIN
indexed), using `websearch_to_tsquery` so raw user input is always safe.
This layer catches exact terms, identifiers, and chemical names that
embeddings blur.

### Knowledge-graph traversal {#6-3-knowledge-graph-traversal}

Graph work happens at two times. Extraction and entity resolution build the graph after ingestion.
The walk and its scope rules run for each graph-enabled query.

#### Extraction {#6-3-1-extraction}

An LLM extracts entities and typed relationships from each chunk. The **domain ontology** declares
the allowed entity and relation types with short descriptions. The extractor drops unknown types
and dangling endpoints.

Entities are canonical by name. They accumulate pointers to the chunks and documents that support
them while retaining the aliases used in those sources.

Relationships keep the quoted phrase that stated them and a confidence score: 1.0 for direct statements, 0.7 for strong implications, and 0.4 for cross-sentence inferences. When extraction runs again, it merges aliases and preserves the highest confidence for a typed edge from the same evidence surface. Edges with different document or chunk provenance stay separate, because retrieval scope cannot erase otherwise eligible relationship evidence.

#### Entity resolution {#6-3-2-entity-resolution}

Extraction can give one concept several names. Run `sci-rag graph resolve-entities --dry-run` to
inspect a three-tier resolution pass. It checks normalized names and alias overlap, then
high-similarity names of the same type, then sends ambiguous cases through one batched LLM
decision. Use `--no-llm` to stop after the deterministic checks.

Nothing changes until `--apply`. A merge combines evidence and aliases, repoints relationships,
and leaves the old row as a `canonical_entity_id` tombstone. Every applied merge creates a durable
row in `entity_resolution_audit`. Graph cleanup preserves the tombstone, and `doctor` reports
probable duplicates.

An applied merge clears community summaries because they materialize entity membership. Review the
merge, then rebuild them with `sci-rag graph communities`.

#### The two-hop walk {#6-3-3-the-two-hop-walk}

At query time, a fast LLM call extracts entity names from the question. The walk follows matching graph entities up to **two hops** in either direction. The chunks those entities point to re-enter the candidate pool, retaining their hop-distance ordering by default.

The domain profile can set a minimum relationship confidence and rank by the strongest minimum-edge confidence along each path, using hop distance as a tie-breaker. Both are off by default; they must earn their place through the `confidence_weighted` versus `full_deep` ablation. The graph stage can also expand to one resolved citation hop in either direction, off by default. It uses only `document_citations` rows whose target resolves to a corpus document, applying the request scope before chunk ranking. The `with_citations` ablation measures this effect. Unresolved DOI pointers remain visible provenance and never enter retrieval.

This architecture makes multi-hop questions work because the connecting entity brings its evidence along, even when the question's words never appear in that text.

#### Scope inside the walk {#6-3-4-scope-inside-the-walk}

Alias strings currently do not carry per-surface document provenance, so only unrestricted graph walks may expand them. A restricted walk may seed from an exact active or tombstone name only when that literal surface occurs in one of the entity's eligible evidence chunks. Resolution tombstones retain their original evidence pointers for this check. The walk restricts retrieved chunks before ranking. Every traversed relationship must carry eligible document or chunk provenance. Restricted evidence therefore cannot seed, extend, or contribute a candidate to the walk.

### Community summaries {#6-4-community-summaries}

Deterministic label propagation groups connected entities, and an LLM writes a short summary of
each group. The embedder indexes those summaries for vector search. This layer can retrieve a
corpus-level summary when no single chunk covers the question.

One hard rule: a stored summary aggregates evidence from many documents before any caller's scope is known. **This layer disables itself whenever license, source, or exclusion filters are active.** A scoped caller must never receive a summary built from outside-scope documents.

### HyDE (hypothetical document embeddings) {#6-5-hyde-hypothetical-document-embeddings}

A fast model writes a short passage that a real document would contain if it answered the question. That passage embeds as if it were a document, and vector search runs near it. This bridges the question-document terminology mismatch described under [Why this shape](#1-why-this-shape). The domain profile can steer the passage style per query class, so an availability question reads like a resource assessment and a properties question reads like a characterization table. The generated passage is a search probe only: never shown, never cited.

### Fusion {#6-6-fusion}

Weighted reciprocal rank fusion:

```
score(c) = sum over layers of  weight_layer / (k + rank_of_c_in_layer)
```

with rank starting at 1 and k = 60. Native scores (cosine distance,
ts_rank, hop counts) use different scales. Rank provides a shared ordering. A
candidate several layers agree on beats a candidate one layer loved.

| Layer | Default weight |
|-------|---------------:|
| vector | 1.5 |
| keyword | 1.0 |
| graph | 0.8 |
| community | 0.6 |
| HyDE | 1.2 |

These shipped values are starting points. Before changing a weight, use the evaluation harness's
ablation mode to measure what each layer contributes on that corpus.

### Profiles and degradation {#6-7-profiles-and-degradation}

Two profiles select starting behavior. **Interactive** enables vector and keyword retrieval, short
per-stage timeouts, and the query-embedding cache. **Deep** can enable all five layers with longer
timeouts for agents, batch jobs, and evaluation.

A slow or failing layer contributes no candidates. Its trace records `timeout`, `error`, `empty`,
`skipped`, or `disabled`, while the other layers continue. Traces contain the stage, status,
duration, and candidate count, but not query or chunk text.

## Scope precedes ranking {#7-scope-precedes-ranking}

A retrieval scope is the caller's rights: allowed license classes, allowed sources, excluded documents. Three rules make it trustworthy.

1. **Every layer applies scope inside its own SQL, before ordering and limiting.** Filtering after ranking fails twice over: an out-of-scope row can crowd an eligible row out of a bounded candidate pool, and excluded content silently shapes what survives.
2. **An explicitly empty license allowlist means "return nothing".** Fail closed, before any embedding call or database query.
3. **`unknown` is never external-safe.** Only `public` and `open_commercial` belong on publicly accessible surfaces.

Excluded document IDs use the same mechanism, which also makes [evaluation holdouts](#9-evaluation-design) real. An excluded document is unreachable through every layer, including graph traversal; a regression test proves it.

Every document carries one of five license classes. Missing or unrecognized
values normalize to `unknown`.

| Class | Meaning | Typical examples |
|---|---|---|
| `public` | Public domain or equivalent; safe to redistribute | CC0, many US federal works |
| `open_commercial` | An open license that permits commercial reuse under its conditions | CC BY, CC BY-SA |
| `open_noncommercial` | An open license that restricts commercial reuse | CC BY-NC variants |
| `restricted` | Holding permitted; redistribution prohibited | Paywalled version of record, proprietary report |
| `unknown` | Nobody has established the rights | The default for incomplete metadata |

The taxonomy supports runtime filtering. Record the actual license and any attribution requirement separately, and consult counsel for legal guidance. To see what a corpus holds, by document and by chunk, run:

```bash
sci-rag corpus license-report            # the table
sci-rag corpus license-report --strict   # exit 1 if anything is still `unknown`
```

Retraction is another scope condition. Crossref enrichment records whether a document has been
retracted, and `exclude_retracted` drops known retracted documents inside every layer's SQL.
Answering enables the filter by default. Raw retrieval does not, because a caller may need to
inspect what a retracted paper claimed. Updated Crossref metadata changes the next answer without
re-ingestion, and `doctor` reports the known retracted-document count.

## Grounded answers {#8-grounded-answers}

The answer prompt receives numbered sources: the retrieved chunks, each with title, section path, and citation. It also carries three standing orders: cite every claim by number, prefer the sources' numbers and units over summary, and say so when the sources do not contain the answer.

The response carries a structured citation list mapping each number to its document. The evaluation judge checks that honesty rule after the fact. A citation identifies the stored passage the answer referenced: its title, formatted citation, document and chunk identifiers, section path, license class, source bucket, and the retrieval layers that found it. Readers must still judge the source's method and the model's interpretation.

Between retrieval and prompt assembly, sources may be compressed: question-aware summarization of each chunk, dropping any whose relevance falls below a floor. This shortens the prompt without changing which documents are cited. Compression is off in the model default and on for the shipped demo. Compression only earns a default where a paired judged-answer evaluation holds every quality dimension while measured prompt tokens fall.

The relevance floor decides whether a source is summarized or discarded. A v0.3 floor sweep tested both. At 0.15 and above, groundedness and citation accuracy fall below ceiling, so the answer loses evidence. At 0.0, where every source is summarized and none dropped, three paired runs held every dimension while median prompt tokens fell a quarter. The demo ships at 0.0; the model default floor matches it. The numbers are on the [benchmarks page](benchmarks.md). To use compression on a specific corpus, run that gate; do not inherit the demo's result. Raising the floor requires running the gate again.

## Evaluation design {#9-evaluation-design}

* **Ground truth requires expert review.** A seed question holds the question, what a correct answer must say, which documents contain it, and distinctive evidence phrases. Drafted questions remain tagged and their reports remain provisional until a domain expert reviews them.
* **Retrieval metrics are mechanical and transparent.** A retrieved item is relevant if it comes from a reference document or contains an evidence phrase (whitespace and case normalized). The harness computes hit@5, hit@10, and MRR per layer-ablation config, so every layer must earn its fusion weight on the specific corpus.
* **The judge is blind.** Grading happens in two independent passes. The grounding pass sees the question, the answer, and exactly the sources the assistant retrieved. It scores groundedness, citation accuracy, and completeness against those sources only, never seeing the reference answer. A judge that sees the reference will reward reference-matching answers the sources do not support. The correctness pass compares the answer to the expert reference in a separate call, without the sources. Both run at temperature 0. Scores clamp to 0-to-2, and a malformed judge response is a failure, never a coerced score.
* **Numbers carry their context.** Every report carries a corpus fingerprint (document, chunk, and graph counts, embedding versions, latest ingestion time) and the git commit. A fingerprint documents what corpus state produced that result.
* **Honesty probes.** Questions tagged `unanswerable` sit outside the retrieval metrics. They check whether the system reports unsupported questions accurately.

## Current limits {#10-what-this-methodology-does-not-do-yet}

The current implementation leaves these capabilities open:

* ~~**Cross-encoder reranking** of the fused pool.~~ Filled in v0.2. `src/sci_rag/retrieve/rerank.py` ships a `Reranker` protocol with an LLM adapter (default, zero new dependencies) and a local cross-encoder adapter behind the `rerank` extra. It stays **off** until the `with_rerank` versus `no_rerank` ablation justifies it on the corpus. GCP users can implement the same protocol against the Vertex AI Ranking API (the `discoveryengine.googleapis.com` rank endpoint). Score the pool, return the reordered items, and point `retrieval.reranker` in `domain.yaml` at the adapter through a small subclass of the retriever or a fork of `build_reranker`.
* **Hierarchical communities** (communities of communities) for very large graphs.
* **Automatic license classification** (DOI lookups against registries). The manifest declares rights in v1; a classifier can enrich it later. It must only ever downgrade toward `restricted`, never upgrade.
* **A learned fusion model.** Weighted RRF is transparent and debuggable. Adopt a learned model only after an ablation demonstrates better results.
