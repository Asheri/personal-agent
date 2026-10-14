---
title: Evaluate your pipeline
description: Run retrieval ablations and judged-answer evaluation, compare two reports, and calibrate the judge against human labels.
---

# Evaluate your pipeline

Measure every pipeline change against the same corpus and question set. The retrieval report
isolates each layer. Answer evaluation separately checks whether the sources support the answer
and whether the answer is correct.

<div class="srag-meta-strip">
  <div><strong>You'll build</strong>A reproducible before-and-after on your own corpus</div>
  <div><strong>You'll need</strong>An ingested corpus and seed questions</div>
  <div><strong>Time</strong>About 20 minutes for the first run</div>
  <div><strong>Credentials</strong>Required for judged answers</div>
  <div><strong>Tested with</strong>v0.5</div>
</div>

## Before you start

| Requirement | Why | Check |
|---|---|---|
| An ingested corpus | Every metric is computed against real chunks | `uv run sci-rag stats` |
| `domain/eval_seed_questions.jsonl`, reviewed | This file is the ground truth. Drafted rows still tagged `drafted` make every number provisional | `uv run sci-rag doctor` |
| LLM provider credentials | Retrieval metrics run offline; judged answers do not | `uv run sci-rag doctor` |
| A corpus snapshot, for anything you will cite | A number without a corpus identity cannot be traced to its inputs | `uv run sci-rag corpus snapshot` |

## The two commands

```bash
sci-rag eval retrieval --ablation   # did the right evidence come back, per layer?
sci-rag eval answers                # are the generated answers grounded, cited, correct?
```

Both read `domain/eval_seed_questions.jsonl`, print a summary table, and write JSON and
Markdown reports to `eval_results/`. Each report records a corpus fingerprint, the git
commit, and the model configuration. Those fields identify the run; they do not make a
model-backed score deterministic. Keep the reports so you can state exactly what a
published number measured.

These historical example reports show the output shape from an earlier demo run:
[examples/demo-eval/retrieval-ablation.md](examples/demo-eval/retrieval-ablation.md)
and [examples/demo-eval/answers.md](examples/demo-eval/answers.md).

## Seed questions: your ground truth

One JSON object per line:

```jsonl title="domain/eval_seed_questions.jsonl"
{"id": "biogas-yield-pretreated",
 "question": "What biogas yield does alkali-pretreated rice straw achieve per dry ton?",
 "reference_answer": "About 320 cubic meters per dry ton at roughly 54 percent methane.",
 "reference_titles": ["Anaerobic Digestion of Crop Residues: A Working Primer"],
 "evidence_phrases": ["alkali pretreated", "320"],
 "tags": ["conversion"]}
```

* **question**: natural wording copied from how a user would ask it.
* **reference_answer**: what a correct answer must say. An expert should
  be willing to sign it.
* **reference_titles**: the documents that contain the answer.
* **evidence_phrases**: distinctive strings from the passages that
  answer it. Numbers with units are ideal; short generic strings (under
  three characters) are ignored on purpose.
* **tags**: your own labels, plus two special values. `unanswerable`
  marks an honesty probe (see below), and `drafted` marks a question a
  model wrote that no expert has checked yet (see below).

Start with 10 to 20 questions a domain expert can defend. Include a multi-document
question when the corpus supports one, and add real user questions as the system misses
them. A small reviewed set is more useful than a large set of vague or unchecked rows.

For help drafting seed questions from scratch,
[`sci-rag draft questions`](bring-your-own-domain.md#step-5-write-seed-questions-then-measure) writes a first pass
grounded in your own documents and verifies every quoted phrase against the
passage it claims to come from.

If questions already exist,
[`sci-rag draft seed-from-answers questions.txt`](bring-your-own-domain.md#step-5-write-seed-questions-then-measure) fills
in the rest. It answers each of your questions and proposes the reference
answer and evidence phrases from what that answer cited, keeping only phrases
that appear verbatim in both the answer and its source. Rows arrive tagged
`drafted` like any other draft, and the reference answers are the kit's own
words, so they are hypotheses until you have checked them.

## Drafted ground truth is provisional, and the report says so

A question tagged `drafted` came from a model. That tag is provenance, and
it travels into the reports: while any question carries it, both
`sci-rag eval retrieval` and `sci-rag eval answers` print a warning saying
how many of the questions behind the numbers are unreviewed, and the JSON
carries the same receipt.

The JSON block sits beside the corpus fingerprint:

```json
"ground_truth": {"drafted": 7, "reviewed": 3}
```

Read the question, check its evidence against the document it cites, then delete the `drafted` tag. That deletion is the expert sign-off, and it is the only thing that moves the counts. The kit does not remove the tag automatically.

## Retrieval metrics, and how to read the ablation table

A retrieved item counts as **relevant** to a question if it comes from a reference document or contains an evidence phrase (case and whitespace normalized). From that definition: hit@5 (was relevant in the top 5), hit@10, and MRR (mean reciprocal rank of the first relevant item).

This metric is deliberately mechanical. It catches retrieval regressions and shows what each layer contributes. The judged-answer evaluation measures correctness. Retrieval metrics never grade answer text by substring matching because that would conflate paraphrase with grounding. The judge exists to detect fluent but incorrect answers.

`--ablation` re-runs the questions under the registered configurations:
`full_deep`, `interactive`, `vector_only`, `keyword_only`, `no_graph`,
`confidence_weighted`, `with_citations`, `no_hyde`, `no_community`, the paired reranker rows,
`auto_routed`, and `no_retracted`. Entity resolution changes persisted corpus state, so it needs
two named snapshots and stays outside this same-state table:

```bash
sci-rag eval retrieval --snapshot before-resolution
sci-rag graph resolve-entities --apply
sci-rag eval retrieval --condition resolved_entities --snapshot after-resolution
sci-rag eval diff BEFORE.json AFTER.json
```

The post-resolution command requires a durable merge audit row, preventing an
unchanged corpus from being mislabeled. Read every layer-ablation row against
`full_deep`:

* A layer earns its fusion weight when **removing** it hurts. If `no_graph`
  equals `full_deep` on your corpus, its measured contribution is zero;
  fix the ontology or the corpus before touching weights.
* `vector_only` versus `keyword_only` tells you how your users' phrasing
  relates to your documents' phrasing. On the demo corpus, keyword-only
  scores 0.33 where vector scores 1.00; that gap is the reason hybrid
  retrieval exists.
* Small corpora can saturate. In the five-document demo, most configurations
  reach 1.00, so only the observed differences support a conclusion. A larger
  corpus may behave differently; measure it directly.

<div class="srag-checkpoint" markdown>
**Checkpoint: measure each layer's contribution**

Point at one row of the ablation table and say what removing that layer cost on the corpus. If every row equals `full_deep`, the corpus may be too small or the ontology may be missing its concepts. Weight changes will have no measurable effect yet.
</div>

## The judge, and why it is blind

Grading a generated answer happens in two independent passes that cannot influence each other.

**Pass 1: grounding (blind).** The judge sees the question, the answer, and exactly the sources the assistant retrieved. It scores three dimensions (each 0 to 2): groundedness (do the sources support the claims?), citation accuracy (do the bracketed numbers point at sources that actually back up the adjacent claim?), and completeness (did the answer use the relevant material you gave it?). The judge never sees the reference answer. A judge that did see it would reward answers that match the reference even when the sources contradict it, converting grounding into paraphrase detection.

**Pass 2: correctness (reference-based).** A second call compares the answer against the expert reference, without the sources. It scores factual agreement from 0 to 2 and allows additional correct detail.

Both passes run at temperature 0. Malformed judge responses fail validation and never become scores. The judge prompts live in `domain/prompts/judge_grounding.md` and `judge_correctness.md`. If you edit them, keep the blindness rules intact and spot-check a few judged answers by hand afterward. That is why the rationale strings are kept in `report.json`.

## Deciding whether to adopt snippet compression

Evaluate contextual snippet compression with two answer-generation runs over the same questions, corpus snapshot, and models:

```bash
uv run sci-rag eval answers --snapshot comparison-corpus
uv run sci-rag eval answers --compressed --snapshot comparison-corpus
uv run sci-rag eval diff eval_results/<uncompressed>/report.json \
  eval_results/<compressed>/report.json
```

Adopt compression only when every judged dimension stays within the confidence interval and median prompt tokens drop noticeably. Otherwise, keep `compression.enabled: false` and record why. Token savings alone do not show answer quality stayed the same; the grounded and correctness scores must stay strong too.

The demo's own comparison, run at three floors on the v0.3 benchmark with
10 seed questions and one corpus snapshot:

| relevance_floor | groundedness | citation accuracy | completeness | correctness | median prompt tokens |
|---|---:|---:|---:|---:|---:|
| uncompressed | 2.00 | 2.00 | 2.00 | 1.60 | 1359 |
| **0.0** | **2.00** | **2.00** | 1.90 | 1.70 | **990** |
| 0.15 | 1.80 | 1.80 | 1.60 | 1.70 | 348 |
| 0.3 | 1.80 | 1.80 | 1.80 | 1.50 | 356 |

The demo enables compression at floor 0.0, where every source is summarized and
none dropped. [See the benchmarks for the full gate](benchmarks.md#contextual-compression-the-paired-gate).

## Calibrating the judge

The judged-answers table is only as citable as the judge behind it. The kit ships calibration as a repeatable workflow you can run yourself:

1. Run an answers eval (`sci-rag eval answers`) and open `report.json` from `eval_results/`.
2. Have a human read each generated answer (and its sources) **without** looking at the judge's scores. Record their own 0-2 scores per dimension, one JSON object per line:

   ```
   {"question_id": "rice-straw-ash", "groundedness": 2,
    "citation_accuracy": 2, "completeness": 1, "correctness": 2}
   ```

   Comment lines starting with `#` are allowed. Omit dimensions you did not score.
3. Compare your labels to the judge's:

   ```bash
   uv run sci-rag eval calibrate --labels labels.jsonl --report eval_results/<run>/report.json
   ```

   You get Cohen's kappa per dimension, exact-agreement counts, and the full 3x3 matrices. The output appends to `report.md` and saves as `calibration.json` so the kappa travels with the numbers.

Report kappa exactly as the tool computes it. Use the Landis-Koch adjective ("moderate", "substantial") only as a reading aid. A low kappa means the judge and humans disagree on that dimension; the matrix shows how. Expect unstable kappa below about 30 labeled answers. More labels from a domain expert make the number trustworthy.

The repo ships `domain/eval_calibration_labels.jsonl`: a seed label set
for the demo corpus, labeled by the kit's authors. It is marked
non-expert, and it earns that label: it demonstrates the workflow and pins
the format, nothing more. Domain-expert labels supersede it for any real
claim about judge reliability, and the BioCirV collaboration supplies
those for the flagship deployment.

## Sharing a run with someone who has no terminal

A domain expert asked to sanity-check ten judged answers should not have to clone the repository. `sci-rag eval html` renders a run as one file you can email:

```bash
uv run sci-rag eval html eval_results/<run>
```

It writes `report.html` next to the report, or wherever `--output` points. The page is self-contained: inline styles, no external fonts or scripts, nothing fetched when it opens. That matters because pages that phone home render differently for each reader, and can fail behind a corporate firewall.

It leads with the provenance receipt so a reader who cannot run commands can see which model produced what they are reading. The small-sample and drafted-ground-truth warnings sit next to the metrics in the same places `report.md` puts them. `calibration.json` is included automatically when it sits beside the report.

In an ablation table, cells whose confidence intervals overlap the baseline are shaded; cells that clear the interval are bold. On a small corpus, many cells may be shaded because the data does not establish a difference from the baseline.

## Honesty probes

Include at least one question your corpus cannot answer, tagged `unanswerable`. Retrieval metrics skip it; the answer eval runs it. A healthy system responds "the corpus does not cover this" and the grounding judge scores that honesty a 2. If your probe comes back with a confident invented answer, stop tuning retrieval and fix your answer prompt first. A system that hallucinates confidently is worse than one that retrieves wrong evidence.

## CI checks demo retrieval

`tests/integration/test_eval_smoke.py` runs the retrieval eval on the shipped demo corpus with the offline embedder on every CI run. It uses conservative thresholds (hit@10 at least 0.65) to catch a broken chunker, layer, or seed file before it ships. Copy that pattern for your own corpus: freeze a small fixture, pin thresholds at your current numbers, and fail loudly if anything regresses.

## The improvement loop

1. Establish the baseline: both eval commands, reports saved.
2. Change one thing (chunk size, a prompt, the ontology, a fusion
   weight).
3. Re-run, then let the diff tool do the comparison:

   ```bash
   uv run sci-rag eval diff eval_results/<baseline-run> eval_results/<new-run>
   ```

   It reports which questions moved (improved, regressed, appeared,
   disappeared) and whether each metric delta clears paired-bootstrap
   significance, so a lucky rank flip on one question cannot pass as an
   improvement.
4. Keep the change only if the numbers (and your reading of the judged
   answers) agree it helped.

When two people disagree about a change, the reports give them the same evidence to
inspect: the per-question movement, the uncertainty, and the generated answers.

<div class="srag-checkpoint" markdown>
**Checkpoint: the numbers are citable**

The newest report names a corpus snapshot, a git commit, the answering and grading models, and the enabled layers, and no question carries the `drafted` tag. A number missing any of these cannot be cited in a methods section.
</div>

## Next steps

- Turn a measured improvement into a shipped default: [Methodology](methodology.md)
- See what the same harness produced on the demo corpus: [Benchmarks](benchmarks.md)
- Add a retrieval stage the ablation can measure: [Extend the kit](extend.md)
