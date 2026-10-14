# Retrieval evaluation

This historical report shows the output shape of a retrieval ablation.

> **Historical example.** This report was committed from the demo run at
> `959595e20eacfef752afa30f8bfb6dd1333c6938` on 2026-08-26. Its values describe
> that historical run. See [Benchmarks](../../benchmarks.md) for the current
> reviewed reports and provenance.

Corpus: 5 documents, 34 chunks, 95 entities, 9 communities.
Embedding versions: gemini-embedding-001@1536.

| Config | hit@5 | hit@10 | MRR | questions |
|--------|------:|-------:|----:|----------:|
| full_deep | 1.00 | 1.00 | 0.93 | 9 |
| interactive | 1.00 | 1.00 | 1.00 | 9 |
| vector_only | 1.00 | 1.00 | 1.00 | 9 |
| keyword_only | 0.33 | 0.33 | 0.33 | 9 |
| no_graph | 1.00 | 1.00 | 1.00 | 9 |
| no_hyde | 1.00 | 1.00 | 1.00 | 9 |
| no_community | 1.00 | 1.00 | 0.93 | 9 |

Read this table by comparing rows against `full_deep`: a layer earns
its place when removing it drops hit rate or MRR. Misses by question
are in report.json.

## Missed questions

- `keyword_only`: rice-straw-generated
- `keyword_only`: rice-straw-baled
- `keyword_only`: rice-straw-ash
- `keyword_only`: almond-pruning-yield
- `keyword_only`: biogas-yield-pretreated
- `keyword_only`: chip-moisture-limit
