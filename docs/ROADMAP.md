---
title: Roadmap
description: See what has shipped, what comes next, and which calls the project deliberately leaves to a human.
---

# Roadmap

Where the kit is going, in the order the evidence supports.

Wave 1, v0.2 "Credibility", has shipped. Waves 2 and 3 are committed directions, and each one gets its own planning pass before anyone writes code. Anything that touches retrieval lands the same way: behind an ablation config, with before and after numbers on a benchmark page. If the numbers do not hold up, it does not land.

Development happens in the open, so the issue tracker milestones say what comes next. The roadmap records the evidence required before planned work can ship.

## Shipped: v0.2 "Credibility"

This release closed the gap between what the methodology promised and
what the code actually did:

- Post-fusion reranker (LLM adapter by default, local cross-encoder
  behind the `rerank` extra), off until the ablation justifies it
- Bootstrap 95% confidence intervals, small-sample warnings, and paired
  significance tests across the eval harness
- `sci-rag eval diff`: per-question rank moves and paired metric deltas
  between any two runs
- `sci-rag eval calibrate`: Cohen's kappa between human labels and the
  judge, with a seeded (non-expert) demo label set
- `sci-rag embed reindex`: act on embedding version stamps
- `sci-rag corpus delete` + `sci-rag graph gc`: full-lifecycle corpora,
  with a regression test proving deleted content unreachable through
  every retrieval layer
- `sci-rag corpus snapshot` + a backup/restore runbook
- Adaptive routing (`--profile auto`) with `--explain-routing`
- [docs/benchmarks.md](benchmarks.md): measured numbers, reproducible
  with `make benchmark`

## Shipped: v0.3 "Campaigns"

The release that makes the kit better for science than a general-purpose
RAG framework. Every item below landed ([epic #38](https://github.com/sustainability-software-lab/sci-rag-kit/issues/38)),
including the stretch item. The evidence reached two different verdicts
on the gated work, and the reasons are the interesting part:

- **Campaign corpus builder.** `sci-rag campaign build --topic|--doi-file`:
  OpenAlex/Crossref discovery, Unpaywall open-access resolution, verified
  direct OA PDF downloads, and a corpus manifest whose license classes derive
  only from explicit recognized license signals, otherwise `unknown`.
  Rate-limited, resumable, dry-run first.
- **Retraction awareness and metadata enrichment.** Crossref (including
  Retraction Watch data) enrichment into document metadata; retrieval
  scope gains `exclude_retracted`, default ON for answering; `doctor`
  warns when retracted documents are present.
- **Citation-graph edges.** References become first-class `CITES`
  relationships between corpus documents (Crossref metadata first,
  GROBID/Docling reference parsing as fallback); citation traversal
  joins the graph stage; MCP gains `get_citations`.
- **Metadata filters.** Year range, author, journal, DOI excludes,
  enforced inside every layer's SQL like every other scope dimension.
- **Entity resolution.** Extraction emits aliases;
  `sci-rag graph resolve-entities` merges by alias/fuzzy/LLM
  adjudication with an audit log; the ablation decides whether it stays.
- **Confidence-weighted traversal.** Calibrated extraction confidence,
  used by the graph stage; ablation-gated like everything else.
- **Contextual snippet compression** (the PaperQA2 pattern):
  per-chunk relevance-scored summarization before answer assembly,
  landing only if judged answer quality holds while tokens drop.
- **PRISMA-style screening**: LLM inclusion/exclusion on abstracts with a
  human-review queue and PRISMA-aligned counts. Landed despite being
  marked stretch.

Two of those are ablation-gated, and the follow-up evidence reached a
different answer for each:

- **Compression defaults on at `relevance_floor: 0.0`.** The original paired judged-answer gate, at floor 0.3, cut median prompt tokens from 1280 to 378. But all four judged dimensions moved down. At n=10 no single drop separates from noise, which is exactly why that run was rejected: the gate asks for evidence that quality holds, and overlapping intervals are not that evidence. The follow-up floor sweep in [#90](https://github.com/sustainability-software-lab/sci-rag-kit/issues/90) found the setting where the gate holds. At 0.0, three independent paired runs kept every judged dimension at or above baseline while median prompt tokens fell 25% to 28%. The shipped profile therefore enables compression at floor 0.0. Raising the floor needs another paired run.
- **Entity resolution is unexercised by the demo corpus.** Resolution
  finds no automatic pairs and plans no merges across 67 extracted
  entities, so the `resolved_entities` condition cannot be measured here
  and the command refuses to fabricate one. The feature is shipped; the
  evidence needs a corpus with real alias variation.

The project factory (main `sci-rag new` command,
[epic #59](https://github.com/sustainability-software-lab/sci-rag-kit/issues/59))
landed alongside wave 2 as separate work.

## Wave 3: v0.4+ "Scale and intelligence"

Patterns already proven elsewhere in GraphRAG. They land once the kit
has users whose corpora need them:

- Lazy, cached community summaries with graph-change invalidation
- Per-document extraction caching for cheap update/delete (the LightRAG pattern)
- Bi-temporal edge validity with `as_of` scoping
- Multi-corpus deployments (schema-per-corpus) behind corpus routing,
  feeding the federation interface
- Prometheus/OpenTelemetry observability and `/metrics`
- HTML/LaTeX/DOCX parsers; Docling OCR exposure
- Hierarchical communities (the `level` column earns its keep)
- A visual-retrieval extension point (image chunks + vision embeddings), last,
  behind an extra

Five things stay out of scope: a Neo4j or dedicated graph-database
migration, RAPTOR, agentic retrieval loops on every query, index-time
contextual embedding, and learned fusion. The reasons are written down in
the [methodology](methodology.md) and the planning docs.

## Collaboration points

Extend the kit at a supported extension point. Reserve a fork for changes outside those interfaces. Two collaborations
shape which extensions come first:

**UW SSEC** (University of Washington Scientific Software Engineering
Center). Three workstreams use extension points that exist today, on their
timeline:

- An **evaluation platform** consuming the eval harness's JSON reports
  (`eval_results/*/report.json`, `calibration.json`), which are stable,
  versioned artifacts precisely so external tooling can build on them
- **OAuth** through the `AuthBackend` interface in `src/sci_rag/server/auth.py`
  (static API keys are the shipped default; the interface supports an
  institutional identity provider)
- **Federation** on the corpus-manifest endpoint
  (`/v1/corpus-manifest`), the machine-readable descriptor a multi-RAG
  router reads to decide which knowledge base fits a query

**BioCirV** (LBL) is the flagship deployment: an agricultural residues
and bioeconomy corpus built with the kit. It supplies three things a
template cannot generate for itself. A real corpus at real scale.
Calibration labels from domain experts, which replace the non-expert seed
set that ships in the box. And the first public case study.

## Launch-gated decisions (owner: maintainer)

These are listed here so they stay visible. No tooling executes them,
because each one is a judgment call with public consequences. Two are now
done, and stay on the list as a record of when:

- Restoring `CITATION.cff` and attribution wording
- Minting a Zenodo DOI on the next tagged release
- JOSS (Journal of Open Source Software) submission
- **PyPI publication: done.** `sci-rag-kit` is published, over Trusted
  Publishing (OIDC, no stored token). `0.3.0a1` was cut first as a
  deliberately expendable version, because PyPI does not allow reuploading
  one and the workflow had never run. Release mechanics are in
  [VERSIONING.md](VERSIONING.md).
- A hosted demo (for example Hugging Face Spaces)
- **Flipping the repository public: done.** This one gated more than it
  looked: the project generator fetches the template tarball anonymously, so
  while the repository was private the generator would have installed cleanly
  from PyPI and produced nothing for anyone outside the org.

## How to influence this roadmap

Open a Discussion for direction-level proposals (see
[GOVERNANCE.md](GOVERNANCE.md)), or pick up a
[good first issue](https://github.com/sustainability-software-lab/sci-rag-kit/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
Success for this project is measured behaviorally: external
contributions merged, adopters listed in [ADOPTERS.md](adopters.md),
and citations of the methodology. Repository stars do not measure adoption.
