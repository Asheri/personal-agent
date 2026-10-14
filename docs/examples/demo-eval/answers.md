# Answer evaluation (blind judge)

This historical report shows the output shape of a completed answer evaluation.

> **Historical example.** This report was committed from the demo run at
> `959595e20eacfef752afa30f8bfb6dd1333c6938` on 2026-08-26. Its values describe
> that historical run. See [Benchmarks](../../benchmarks.md) for the current
> reviewed reports and provenance.

Corpus: 5 documents, 34 chunks.

Scores are 0 to 2 per dimension. The grounding judge never sees the
reference answer; correctness is graded in a separate reference-only pass.

| Metric | Mean |
|--------|-----:|
| groundedness | 2.00 |
| citation_accuracy | 2.00 |
| completeness | 2.00 |
| correctness | 1.60 |
| graded / total | 10 / 10 |

## Per question

| Question | grounded | citations | complete | correct | note |
|----------|---------:|----------:|---------:|--------:|------|
| rice-straw-generated | 2 | 2 | 2 | 2 |  |
| rice-straw-baled | 2 | 2 | 2 | 1 |  |
| rice-straw-ash | 2 | 2 | 2 | 2 |  |
| almond-pruning-yield | 2 | 2 | 2 | 1 |  |
| biogas-yield-pretreated | 2 | 2 | 2 | 1 |  |
| chipping-cost | 2 | 2 | 2 | 1 |  |
| chip-moisture-limit | 2 | 2 | 2 | 2 |  |
| ruc-payment | 2 | 2 | 2 | 2 |  |
| digester-siting | 2 | 2 | 2 | 2 |  |
| switchgrass-honesty | 2 | 2 | 2 | 2 | honesty probe |
