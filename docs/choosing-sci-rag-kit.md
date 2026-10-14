---
title: Choosing Sci RAG Kit
description: Compare Sci RAG Kit against LightRAG, PaperQA2, LlamaIndex, and Microsoft GraphRAG, then decide which one fits the work in front of you.
---

# Choosing Sci RAG Kit

Choose Sci RAG Kit for a complete, self-hosted scientific RAG application. Use a framework or
purpose-built research agent when you need a different storage, retrieval, evaluation, or serving
stack. The [FAQ](faq.md) answers shorter questions about fit and design choices.

Cross-system benchmark scores do not appear here because results measured on different corpora are
not comparable. The kit's [benchmarks](benchmarks.md) cover its synthetic demo corpus and state the
provenance and uncertainty of those runs.

## The landscape

The external project descriptions below were checked against their primary repositories as of
2026-09-02.

| System | What it provides | Choose it when |
|---|---|---|
| **Sci RAG Kit** | A repository template with Postgres storage, scoped hybrid retrieval, evaluation, REST, and MCP already wired together | You want a scientific knowledge base with explicit rights and evaluation contracts, and you can operate Postgres |
| [**Microsoft GraphRAG**](https://github.com/microsoft/graphrag/blob/f40e9a26ce62ba0b3fef8837d24aafdcc6e6c704/README.md) | A research implementation of graph-based indexing and local/global search | You are studying the GraphRAG methodology or its current feature set already fits |
| [**LightRAG**](https://github.com/HKUDS/LightRAG/blob/c1248646e4eda4d89054926af2e094730daf23fe/README.md) | A graph-enhanced RAG package with several query modes and storage choices, including PostgreSQL | You want to configure the retrieval and storage stack around a general GraphRAG implementation |
| [**PaperQA2**](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/README.md) | A package focused on scientific literature, with an agent that can search, gather evidence, and refine a query before answering | You want iterative work per question and accept the model calls and latency that workflow requires |
| [**LlamaIndex**](https://github.com/run-llama/llama_index/blob/857efcf7306d81814f790c76eaa079db25ca9523/README.md) | A framework for agentic applications with a core package and separate integrations for models, embeddings, data sources, and stores | You want to compose those components and own the resulting application architecture |

Microsoft states that GraphRAG is [largely in maintenance
mode](https://github.com/microsoft/graphrag/blob/f40e9a26ce62ba0b3fef8837d24aafdcc6e6c704/README.md#L3-L4):
bug and dependency fixes continue, but the project does not plan new features or accept new pull
requests. The repository describes the code as a research demonstration, and Microsoft support
channels do not cover it. A team that expects new upstream capabilities should choose an active
project or plan to maintain its own fork.

## What Sci RAG Kit decides for you

`pipx install sci-rag-kit` followed by `sci-rag new` creates a configured project. `sci-rag init`
configures an existing checkout. Both routes produce a repository you own and can modify.

The kit fixes several architectural choices so a project can start with one coherent system. The
same choices define when another shape fits better.

| Axis | The kit's position | Choose differently if |
|------|--------------------|----------------------|
| Shape | Template repository you own and modify; one Python package and no plugin layer | You want to assemble an application from framework integrations |
| Storage | One Postgres database for text, vectors, full-text search, and graph rows | You need deep graph traversal, centrality, or path analytics in the live query path |
| Corpus building | Discovery from a topic or DOI list, open-access rights resolved per paper, verified PDF download, abstract screening with a human review queue | You already have the documents and their rights, and want nothing between you and ingestion |
| Graph | Ontology-constrained extraction, reviewable entity resolution with an audit row per merge, and citation traversal over resolved DOI edges | You want an unconstrained graph and will do the disambiguation downstream |
| Evaluation | Test questions, per-layer scores, confidence intervals, a two-pass grader, calibration against human labels, and report diffing | You already have an evaluation system and do not want the template's report contract |
| License governance | License classes enforced inside every layer's query, before ranking; built for corpora with mixed rights | Everything you index is uniformly licensed and served to one audience |
| Model wiring | ModelScope embeddings and DeepSeek generation by default; fresh Google projects use `gemini-embedding-001` at 1024 dimensions; Claude and other OpenAI-compatible endpoints remain selectable | You need to switch embedding providers without a migration and full re-embed |
| Serving | REST and MCP from one FastAPI service | You need a hosted service with a vendor-operated SLA |
| Retrieval | Up to five fused layers, selected by a profile and router, with no per-question agent loop | You want an agent to search and refine evidence iteratively for each question |

## The concessions

- **No agent loop.** A question runs through one retrieval pipeline and answer generation. For
  iterative searching and evidence gathering, use PaperQA2 or put an agent above the kit's API.
- **Postgres only.** One database is the point. The kit will not grow a storage abstraction layer.
- **Embeddings are provider-specific.** ModelScope is the default, Google is
  optional, and `local-hash` remains the offline floor. Generation can use
  `deepseek`, `google`, `anthropic`, or `openai-compatible`. Changing the
  embedder requires a full re-embed; a dimension change also requires a
  migration and index rebuild. [ADR 0012](adr/0012-modelscope-deepseek-providers.md)
  records the shipped default.
- **Corpus-specific features need corpus-specific evidence.** The demo enables answer compression
  at a relevance floor of 0.0 because its paired evaluation passed there and failed at 0.15 and 0.3.
  Reranking remains off by default. The [benchmarks](benchmarks.md) publish those runs.
- **Early stage.** 0.x, a small community, and no external deployments yet. [VERSIONING.md](VERSIONING.md) states exactly what 0.x promises.
- **English-centric defaults.** The keyword layer's full-text configuration and the demo prompts assume English scientific text.

Run the [quickstart](quickstart.md) to test the template's path. For the reasoning behind its
choices, read the [methodology](methodology.md) and [decision records](adr/0001-graph-in-postgres.md).
