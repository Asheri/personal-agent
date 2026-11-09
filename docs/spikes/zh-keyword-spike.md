# Chinese keyword spike

Candidate evidence dated 2026-10-25. This is a controlled 104-chunk corpus with 24
queries: eight names, eight identifiers, and eight sentences. Facts and queries
were constructed before measurement; labels are provisional and have no human
approval. Source JSON and preregistration hashes are retained with the raw results.

The original gate requires identifier hit@20 >= 0.75, keyword p95 <= 300 ms, and
no worse identifier recall than vector_only. An additional 0.75 gate on names and
sentences prevents accepting the reported empty-Chinese-result defect. This
stronger interpretation is part of the v1.6 candidate awaiting nonauthor review.

## Results

| Method | Names | Identifiers | Sentences | All hit@20 | Warm p95 ms |
|---|---:|---:|---:|---:|---:|
| Previous English FTS | 0/8 | 0/8 | 0/8 | 0.000 | 7.434 |
| B: pg_trgm | 0/8 | 8/8 | 0/8 | 0.333 | 2.565 |
| D: jieba | 8/8 | 8/8 | 8/8 | 1.000 | 8.353 |
| Semantic vector comparator | 8/8 | 8/8 | 8/8 | 1.000 | 40.230 |

Candidate B uses a GIN trigram index and the percent similarity operator.
The C-locale database returns an empty trigram array for the tested Chinese name.
B meets the narrow identifier gate but fails all name and sentence cases; D is
selected to close the Chinese-query defect as well as the numeric identifier gate.

The comparator uses actual Qwen3-Embedding-0.6B Q8_0, last-token pooling, 1024
dimensions, normalized vectors, and the same fixed query instruction before and
after. It does not use a hash embedding or query-entity stub. The official model
revision, download hashes, llama.cpp tag, and commands are retained. The embedding
adapter lives only in the evaluation scripts; application provider defaults are
unchanged. No external API or paid model call is used.

The same database rows, IDs, text, vectors, scope, and queries are used in the
paired runs. `sci-rag eval diff` reports zero vector changes and keyword MRR from
0 to 1. Statistical output on this constructed corpus does not establish field
accuracy or generalization.

## Raw hit matrix

| Query ID | Previous keyword | B | D | Vector |
|---|---:|---:|---:|---:|
| name-01 | 0 | 0 | 1 | 1 |
| identifier-01 | 0 | 1 | 1 | 1 |
| sentence-01 | 0 | 0 | 1 | 1 |
| name-02 | 0 | 0 | 1 | 1 |
| identifier-02 | 0 | 1 | 1 | 1 |
| sentence-02 | 0 | 0 | 1 | 1 |
| name-03 | 0 | 0 | 1 | 1 |
| identifier-03 | 0 | 1 | 1 | 1 |
| sentence-03 | 0 | 0 | 1 | 1 |
| name-04 | 0 | 0 | 1 | 1 |
| identifier-04 | 0 | 1 | 1 | 1 |
| sentence-04 | 0 | 0 | 1 | 1 |
| name-05 | 0 | 0 | 1 | 1 |
| identifier-05 | 0 | 1 | 1 | 1 |
| sentence-05 | 0 | 0 | 1 | 1 |
| name-06 | 0 | 0 | 1 | 1 |
| identifier-06 | 0 | 1 | 1 | 1 |
| sentence-06 | 0 | 0 | 1 | 1 |
| name-07 | 0 | 0 | 1 | 1 |
| identifier-07 | 0 | 1 | 1 | 1 |
| sentence-07 | 0 | 0 | 1 | 1 |
| name-08 | 0 | 0 | 1 | 1 |
| identifier-08 | 0 | 1 | 1 | 1 |
| sentence-08 | 0 | 0 | 1 | 1 |

## Limits and reproduction

Five warm measurements per query provide 120 latency samples per method. This
is a small corpus, with no large-corpus concurrency or service-latency claim.
Tokenizer initialization took about 0.65 seconds separately. All query scopes
are public/current; separate integration cases test hidden sources, unknown
rights, old revisions, limits, and token refresh after changing content.

The dated handoff contains semantic-spike/before-matrix.json, after-matrix.json,
paired retrieval reports and eval-diff.md under its evidence context. Reproduce
with scripts/run_zh_keyword_spike.py on a new explicit loopback _test database,
using the fixed data/demo-personal/zh-keyword-spike.json and evaluation embedding
endpoint. The harness refuses a non-test target. Historical exploratory hash
probe reports are retained but are superseded by the semantic comparison here.

Upstream references: [jieba search mode](https://github.com/fxsjy/jieba),
[PostgreSQL pg_trgm](https://www.postgresql.org/docs/16/pgtrgm.html), and
[Qwen3 Embedding](https://github.com/QwenLM/Qwen3-Embedding).
