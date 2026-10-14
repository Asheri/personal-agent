---
title: Benchmarks
description: Measured results on the shipped demo corpus, with confidence intervals, snapshot provenance, model identifiers, and the command that reproduces them.
---

# Benchmarks

These results measure the shipped demo corpus and can be regenerated with one command. They
validate the evaluation workflow on this synthetic corpus. See
[Choosing Sci RAG Kit](choosing-sci-rag-kit.md) for a feature-level comparison.

## What was measured

- Corpus: 5 documents, 34 chunks, 67 entities, 78 relationships, 8 communities (the synthetic agricultural-residue demo corpus shipped in `data/demo/`)
- Corpus snapshot: `benchmark-20260902-051515` (see `data/snapshots/`; the digest pins the exact document set)
- Embedding: `gemini-embedding-001@1536`; models: answer `google:gemini-3.6-flash`, extraction `google:gemini-3.6-flash`, judge `google:gemini-3.6-flash`
- Code: commit `44ecac4`; domain and prompts: `11194722ed59`
- Graph: strict replay from `data/demo/graph-replay/a24c3fb88f163941048866b86fc494a3470337b0c24257f1d9235c8b00f19d15.json` (`a24c3fb88f163941048866b86fc494a3470337b0c24257f1d9235c8b00f19d15`); 4 recorded calls replayed, 0 live extraction calls; canonical graph `3ec1cba1f5484bef25101812c3240cecb5b1be55652c3caebea2e2c1d5485b14`
- Rendered: 2026-09-02

The reviewed graph replay makes entity and relationship counts exact. Judged answers and other model-backed measurements remain stochastic. Repeating the command below reproduces those measurements within a declared tolerance of 0.1 absolute on a metric and 10% on other counts, and `--check` fails visibly when one moves further. Publishing movement beyond the tolerance requires a reviewed source report and an explanation of which recorded input changed.

## Retrieval ablations

Cells are mean [95% bootstrap CI], resampled per question. The
demo corpus has single-digit questions, so intervals are wide by
construction: treat differences whose intervals overlap heavily as
noise. Read the table for the qualitative story about which layers
earn their keep. On a small sample
like this, that qualitative story is the only defensible claim.

| Config | hit@5 | hit@10 | MRR | nDCG@10 | n |
|--------|---:|---:|---:|---:|---:|
| full_deep | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.91 [0.73, 1.00] | 0.90 [0.79, 0.99] | 9 |
| interactive | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.96 [0.91, 1.00] | 9 |
| vector_only | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.96 [0.91, 1.00] | 9 |
| keyword_only | 0.33 [0.00, 0.67] | 0.33 [0.00, 0.67] | 0.33 [0.00, 0.67] | 0.33 [0.00, 0.67] | 9 |
| no_graph | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.93 [0.78, 1.00] | 0.91 [0.82, 0.99] | 9 |
| confidence_weighted | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.91 [0.73, 1.00] | 0.91 [0.81, 1.00] | 9 |
| with_citations | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.91 [0.73, 1.00] | 0.90 [0.80, 0.98] | 9 |
| no_hyde | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.94 [0.83, 1.00] | 0.94 [0.88, 0.99] | 9 |
| no_community | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.91 [0.73, 1.00] | 0.90 [0.79, 0.99] | 9 |
| with_rerank | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.94 [0.89, 0.98] | 9 |
| no_rerank | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.94 [0.83, 1.00] | 0.93 [0.87, 0.99] | 9 |
| auto_routed | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.93 [0.78, 1.00] | 0.90 [0.79, 0.98] | 9 |
| no_retracted | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.91 [0.73, 1.00] | 0.90 [0.80, 0.98] | 9 |

The missing `resolved_entities` row records the outcome of its precondition.
It is a separate condition (`sci-rag eval retrieval
--condition resolved_entities`) measured on a post-resolution
snapshot, and it requires at least one persisted resolution audit
row. On this corpus `sci-rag graph resolve-entities` finds no
automatic pairs and plans no merges: 67 extracted entities with
nothing duplicated enough to merge. The condition requires a real merge
and stops here because it would otherwise repeat `full_deep` under another
name. A corpus with real alias variation
is what would exercise it.

How to read it:

- `full_deep` vs the `*_only` rows shows what fusion buys over any
  single layer.
- `no_graph` / `no_hyde` / `no_community` vs `full_deep` shows each
  layer's marginal contribution on this corpus.
- `with_rerank` vs `no_rerank` is the paired evidence the reranker
  must show before `retrieval.reranker.enabled: true` is justified.
- `auto_routed` vs `full_deep` and `interactive` is the evidence for
  (or against) making adaptive routing a default. Until it clearly
  matches `full_deep` at lower cost, `auto` stays opt-in.

## Judged answers (blind two-pass judge)

| Dimension | Mean [95% CI] |
|-----------|--------------:|
| groundedness | 2.00 [2.00, 2.00] |
| citation_accuracy | 2.00 [2.00, 2.00] |
| completeness | 2.00 [2.00, 2.00] |
| correctness | 1.80 [1.40, 2.00] |
| graded / total | 10 / 10 |

The grounding judge never sees the reference answer; correctness
is graded in a separate reference-only pass (docs/evaluation.md).

## Contextual compression: the paired gate

Compression defaults on for the shipped demo at `relevance_floor: 0.0`.

Two judged-answer runs over the same questions and the same corpus,
one with `--compressed` and one without. The gate requires judged
quality to HOLD while measured prompt tokens fall. Token savings alone
cannot justify the default.

Measured at the load-bearing `relevance_floor: 0.0` setting.
The floor decides whether a source is dropped
or summarized, and dropping evidence is what an answer cannot recover
from. Raising it trades groundedness for tokens; that is a different
trade from summarizing, and it needs its own paired run.

| Dimension | Uncompressed | Compressed |
|-----------|-------------:|-----------:|
| groundedness | 2.00 [2.00, 2.00] | 2.00 [2.00, 2.00] |
| citation_accuracy | 2.00 [2.00, 2.00] | 2.00 [2.00, 2.00] |
| completeness | 2.00 [2.00, 2.00] | 2.00 [2.00, 2.00] |
| correctness | 1.80 [1.40, 2.00] | 2.00 [2.00, 2.00] |
| median prompt tokens | 1315 | 887 (33% lower) |

Sources dropped by the relevance floor: 0. Compression failures: 0. Questions: 10.

On this run the gate holds: no judged dimension fell while prompt tokens dropped. That justifies the default on THIS corpus only; re-run the gate before carrying it to another.

## Judge calibration (human labels vs judge)

Cohen's kappa between independent human labels
(`domain/eval_calibration_labels.jsonl`, a NON-EXPERT seed set)
and the judge's scores on the same answers:

| Dimension | kappa | exact agreement | n |
|-----------|------:|----------------:|--:|
| groundedness | 1.00 | 1.00 | 10 |
| citation_accuracy | 1.00 | 1.00 | 10 |
| completeness | 1.00 | 1.00 | 10 |
| correctness | 0.00 | 0.90 | 10 |

Kappa is reported as measured, never asserted as a target. A
kappa of 0 with high exact agreement means one rater was
constant (kappa cannot credit agreement it attributes to
chance). A seed set with more score variance fixes that limitation.
Expert labels supersede this seed set.

## Reproduce it

```bash
make benchmark
```

Prerequisites: a selected PostgreSQL backend with pgvector, uv, and Google
credentials in `.env` (`SCI_RAG_GOOGLE_API_KEY` or
`SCI_RAG_GCP_PROJECT`; see `.env.example`). The backend must point to a
named, disposable PostgreSQL database. The target ingests the tracked
demo corpus into otherwise pristine graph state before strict replay.
Select a disposable database for that preflight and leave development corpora intact.
It then creates communities, snapshots the
corpus, runs the full retrieval ablation plus the judged answers eval, and
re-renders this page from the report JSONs. Without credentials the eval
commands stop with a clear message. Published numbers require real models.
