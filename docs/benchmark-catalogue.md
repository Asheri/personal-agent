# Benchmark catalogue

Which public benchmark to run for the graph-versus-retrieval question, what each
one exercises, and what it costs before anybody starts. A benchmark is chosen
for the question it can answer, not for its size.

## What a public benchmark can and cannot test here

Can: retrieval across documents, multi-hop evidence assembly, whether an answer
is supported by what was retrieved, and whether the graph layer changes any of
that.

Cannot: version chains, project ownership, timeline browsing, incremental
refresh, or file-type parsing. Every one of those needs a personal corpus, so a
benchmark result and the own-corpus experiment answer different halves of the
report.

## Candidates

Sizes are the published ones. GPU time is an estimate for the whole run on one
A100-80GB with a 7B AWQ model served by vLLM; see the cost model below for the
assumptions and for why 32B is roughly three times more.

| Dataset | Size | Question shapes | License | What it tests | GPU |
|---|---|---|---:|---|---:|
| **MultiHop-RAG** | 609 articles, 2,556 questions | inference, comparison, temporal, null | ODC-BY | 2 to 4 documents per answer, with publisher and date metadata | **≈1.2 h** |
| **HotpotQA** (distractor dev) | 7,405 questions, ~74k paragraphs | bridge, comparison | CC BY-SA 4.0 | Classic multi-hop QA; most published numbers to compare against | ≈5.5 h |
| **MuSiQue** (dev) | 2,417 questions, ~50k paragraphs | 2 to 4 hop, six compositions | CC BY 4.0 | Harder to shortcut than HotpotQA; the intermediate entity is rarely in the question | ≈2.7 h |
| **2WikiMultiHopQA** (dev) | 12,576 questions, ~30k paragraphs | bridge, comparison, compositional, inference | Apache-2.0 | Supporting facts come from Wikidata triples, so the graph has a fair chance | ≈5.8 h |
| **DocRED** (dev) | 1,000 documents, 96 relation types | relation extraction | MIT | Document-level extraction with published F1; needs an ontology mapping | ≈0.1 h |
| **CMeIE** | ~22k sentences, 44 relation types | relation extraction | research use | Chinese extraction, closer to `domain-personal` | ≈0.4 h |
| **LongMemEval-S** | 500 questions, histories up to 115k tokens | single-session, multi-session, temporal, preference | MIT | Long-term memory; the corpus is dialogue, so identity and version logic do not apply | ≈14 h |
| **LoCoMo** | 50 long conversations | multi-hop, temporal, adversarial | research use | Memory over conversations; same caveat as above | ≈0.8 h |
| **BEIR / SciFact** | 18 datasets, 1,409 claims | retrieval only | mixed | Retrieval generality; no generation, so nearly no GPU | ≈0 |

Reading of the table:

- **MultiHop-RAG is the cheapest run that still says something.** It is small
  enough to build a graph over, its questions need two to four documents, and
  its `null` questions give the refusal probe for free. Start here.
- **2WikiMultiHopQA is the one to reach for if the graph shows nothing.**
  Its evidence is literally triples, so a null result there is a stronger
  statement about the graph than a null result on news prose.
- **DocRED or CMeIE is for the extraction chapter**, not the retrieval one.
  They buy an external F1, at the price of mapping 96 or 44 relation types onto
  the ontology (map eight to ten; do not map them all).
- **LongMemEval is expensive for the wrong reason**: extraction over 57M tokens
  of dialogue costs 14 GPU-hours while the questions are mostly single-fact
  recall. Run it only if the report wants a long-memory number, and consider
  indexing without a graph first.

## The cost model

```
tokens_in   = corpus_tokens + questions × conditions × context_tokens
tokens_out  = corpus_tokens × 2  (extraction)  +  questions × conditions × 600
gpu_hours   = tokens_in / 12_000 / 3600 + tokens_out / 2_500 / 3600
```

Constants, measured rather than assumed where possible:

| Constant | Value | Where it comes from |
|---|---|---|
| prompts per question-run | ~1,545 tokens | 1/4 sample probe, SiliconFlow, `--sources 5` |
| output per question-run | ~600 tokens | answer plus two judge calls |
| A100 prefill | ~12,000 tok/s | vLLM, 7B AWQ, batch 32 |
| A100 decode | ~2,500 tok/s | same |
| 32B instead of 7B | ×3 | compute and weights both roughly quadruple, throughput about a third |
| per question-run wall clock over an API | ~20 s at concurrency 8 | measured; four sequential calls per run |

A run also spends time outside the GPU: parsing, embedding, and retrieval. On
this laptop that is minutes; on a rented box the CPU is slower per core but
there are more of them, so budget one extra hour for a fresh environment and
the model download.

## What the committed run covers

A 1/4 stratified sample of MultiHop-RAG: 639 questions × 3 conditions = 1,917
question-runs, paired n=639. The conditions are `plain` (no retrieval), `rag`
(vector and keyword), and `kg` (every layer).

Why a sample and not the whole set: the measured provider ceiling is 50,000
tokens per minute, which is about 23 question-runs per minute, so the full
7,668 runs take roughly 5.5 hours. A quarter takes about 1.4 and leaves the
paired test enough power. The sampling is stratified by question type with a
fixed seed, and the report states it.

## Running a larger evaluation on an A100

The runner does not care where the model lives: it goes through any
OpenAI-compatible endpoint. A GPU changes the constants, not the commands.

```bash
# 1. Serve a model. AWQ keeps a 7B inside 24 GB; a 32B needs about 20 GB.
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ \
  --max-model-len 8192 --gpu-memory-utilization 0.9 --max-num-seqs 64

# 2. Point the project at it.
export SCI_RAG_LLM_PROVIDER=openai-compatible
export SCI_RAG_OPENAI_BASE_URL=http://127.0.0.1:8000/v1
export SCI_RAG_OPENAI_API_KEY=dummy        # vLLM ignores the value
export SCI_RAG_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ
export SCI_RAG_EMBEDDING_PROVIDER=modelscope
export SCI_RAG_EMBEDDING_DIM=1024

# 3. Corpus, then graph, then the three conditions at full size.
uv run python scripts/run_benchmark_eval.py \
  --dataset ~/data/MultiHopRAG --corpus-dir "$PCMEM_DATA_DIR/multihop" --dry-run
uv run sci-rag ingest --manifest "$PCMEM_DATA_DIR/multihop/manifest.jsonl"
uv run sci-rag graph extract && uv run sci-rag graph communities
uv run python scripts/run_benchmark_eval.py \
  --dataset ~/data/MultiHopRAG --corpus-dir "$PCMEM_DATA_DIR/multihop" \
  --limit 0 --sources 5 --concurrency 32 --output .context/benchmark-full
```

`--limit 0` means every question, and `--concurrency 32` saturates one A100.
With a hosted API, keep it at 8 to 12 instead: the ceiling there is tokens per
minute, not the GPU.

| Run | Question-runs | API at 23/min | One A100 | Cost on SiliconFlow |
|---|---:|---:|---:|---:|
| 1/4 sample (committed) | 1,917 | ≈1.4 h | ≈3 min | ≈¥8 |
| 1/2 sample | 3,834 | ≈2.8 h | ≈6 min | ≈¥12 |
| Full set | 7,668 | ≈5.5 h | ≈12 min | ≈¥21 |

The GPU column excludes extraction, which is the bigger half on a small corpus:
0.39 GPU-hours for MultiHop-RAG, against 0.79 for every answer and judge call.

## Local embedding, measured

Qwen3-Embedding-0.6B on an M5 Pro through MPS, 1,024 dimensions:

| Batch | Throughput |
|---|---:|
| 128 chunks (25,600 tokens) | 6,439 tok/s |
| 200 chunks (40,000 tokens) | 6,159 tok/s |

The MultiHop-RAG corpus is about 1.58M tokens of text, so one pass costs roughly
4 to 5 minutes, and the first call (model download and load) is a one-off 153
seconds. A query embedding is tens of milliseconds, which does not register
against a 20-second question run.

Two consequences worth remembering: embedding never competes for the provider's
token budget, because that budget is for chat completions, and a local embedder
is what makes a private corpus possible at all.
