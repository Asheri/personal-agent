# Measured results for this candidate

Every number below comes from a run recorded under `.context/`, which is
ignored by git and stays local. A clone cannot re-derive these counts; it can
re-run the commands, and the rows say which command produced each one.

The candidate is not an approved release. Each stage has a dated spec and an
unassigned review template in `docs/superpowers/specs/`.

## Test suites

| Check | Host | Result | Receipt |
|---|---|---|---|
| `pytest tests/unit -q` as delivered | Windows, no database | 1,736 collected: 1,690 passed, 7 failed, 39 skipped | `.context/core-completion-20261026/unit-release.xml` |
| the same suite in a git checkout | macOS, Python 3.12 | 1,735 passed, 13 skipped, 0 failed | re-run on this branch, 2026-11-09 |
| `pytest tests/integration tests/server -q` | Windows, throwaway PostgreSQL 16 with pgvector | 279 passed, 0 failed, 0 skipped | `.context/core-completion-20261026/integration-release.xml` |
| the same integration and server suite | macOS, PostgreSQL 17 with pgvector 0.8.7 | 279 passed, 0 failed | re-run on this branch, 2026-11-09 |
| `pytest tests/docs -q` | Windows, no site build | 34 collected: 20 passed, 14 skipped | `.context/core-completion-20261026/docs-final.xml` |

One more Windows assumption lived in the integration fixtures: relative links
are resolved only when the source path is absolute by the host's own rules, and
a literal `d:\records\...` is not absolute on POSIX. Those fixtures now build
their paths from a platform-appropriate base.

The seven failures in the delivered tree were **not** product defects. Each one
calls `git ls-files`, `git check-ignore`, or `git diff HEAD`, and the handoff
tree had no `.git` directory. In a checkout they pass, which is why the second
row reports zero failures. The suite also grew by 31 tests on this branch
(the cross-platform runner and the Agent contract).

## Retrieval at a language boundary

A constructed 24-query test: eight identifier queries, eight mixed queries and
eight name queries, each with three expected documents, over 24 single-sentence
fixtures.

| Bucket | Before | After |
|---|---|---|
| identifier | 0.333 | 1.000 |
| mixed | 0.667 | 1.000 |
| name | 1.000 | 1.000 |
| warm p95 | 2.985 ms | 3.417 ms |

Receipts: `.context/core-completion-20261026/keyword-spike/{before,after}.json`.
These are **target-document recall**, not hit@k. The paired `eval diff` over the
same corpus reports a delta of exactly 0.000 on hit@5, hit@10, MRR and nDCG@10,
because three expected documents already fit inside top-5. Do not quote the two
measurements as one.

## Refresh cost

100 generated files, `local-hash` embeddings, one disposable database.

| Run | Time |
|---|---|
| first refresh | 2,794.5 ms |
| unchanged refresh 1 | 581.6 ms |
| unchanged refresh 2 | 473.2 ms |
| unchanged refresh 3 | 506.0 ms |

Repeat embeddings during the unchanged refreshes: **0**. Receipt:
`.context/core-completion-20261026/poll-cost.json`. A deterministic embedder at
100 files says nothing about semantic embedding cost or a large directory.

## Extraction and answers on a controlled corpus

Qwen2.5-7B-Instruct Q4_K_M for generation, Qwen3-Embedding-0.6B at 1024
dimensions for retrieval, 20 constructed cases plus 8 controls, batch size 1.

| Measure | Result |
|---|---|
| Entities, 120 expected | precision 1.00, recall 1.00, F1 1.00 |
| Relations, 100 expected | precision 1.00, recall 0.95, F1 0.974 |
| Project ownership, 20 positive cases | 20 of 20 |
| Mechanical answer checks, 8 questions | 8 of 8 for the RAG configuration, 8 of 8 with the graph stage on |

Receipt: `.context/chinese-quality-20261025/quality/summary.json`. Earlier
trials are kept beside it: relation F1 was 0.221 in the first attempt and 0.083
in the second, which is the honest shape of this work.

Two limits belong with the table. The corpus states its facts in one sentence
template with the names swapped, so F1 1.00 measures the pipeline, not field
accuracy. The answer checks are string tests (required terms, forbidden terms,
resolvable citation numbers, expected cited project, refusal cue), so 8 of 8 is
not a correctness judgment, and the two configurations answering identically is
the expected outcome at this size.

## Upstream Agent protocols

The acceptance run exercises the pinned GenericAgent hook bus, dispatch loop and
scheduler against a controlled handler and a three-file corpus, then checks that
no private body, path or query reached the memory files.

| Measure | Result |
|---|---|
| Install twice, identical seed hashes | passed |
| First clean run on macOS (2026-11-09), same assertions | passed |
| Three trigger channels (`poll`, `hooks`, `scheduler`) | passed |
| Three confirmed tasks create an L3 procedure, a fresh router reuses it | passed |
| Private pointer leaks | 0 |

That run used a controlled handler, not a live model conversation. See
[Agent integration](agent-integration.md) for what it needs and why
GenericAgent is not vendored.

## Larger runs

[The benchmark catalogue](benchmark-catalogue.md) lists the public benchmarks
this project can run, what each one exercises, and the GPU-hours each costs, so
a reader with an A100 can go past the sample size used here.

## Not measured

No representative personal corpus, no live Agent conversation, no native OCR
re-run after its runtime was removed, no large-directory or concurrent latency
measurement, no handwriting benchmark, and no P6 narrative or multimodal
research. Those absences are declared, not implied by the tables above.
