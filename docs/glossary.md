---
title: Glossary
description: What each term means in this project.
---

# Glossary

Terms below use their Sci RAG Kit meanings, which may be narrower than their use in the literature.

## Retrieval and answers

**RAG (retrieval-augmented generation)**
: Retrieve passages that bear on a question, then have a model answer only from those passages and cite them. The model writes the prose; the documents supply the facts.

**Chunk**
: A passage of roughly 800 tokens that the kit stores, embeds, ranks, and cites. It retains its document, position, section heading, table flag, vector, and embedding-model version.

**Embedding**
: A vector that places texts with similar meaning near each other, allowing a question to find a passage that uses different words. The default ModelScope embedding is 1024 dimensions and normalized. Fresh Google projects use `gemini-embedding-001` at 1024 dimensions.

**Retrieval layer**
: One method of proposing candidate passages for a question. The kit runs five: vector (embedding similarity), keyword (full-text search), graph (entity traversal), community (topic summaries), and hypothetical answer (HyDE).

**HyDE (hypothetical document embeddings)**
: A short model-written guess at what an answering passage would say. The kit embeds the guess to aim the search but never shows or cites it.

**Fusion**
: The combination of five ranked lists into one. Weighted reciprocal rank fusion adds `weight / (60 + rank)` from each layer that returned a passage, so agreement across layers raises its rank.

**Profile**
: Which retrieval layers run for a request. `interactive` runs vector and keyword only, for a person waiting at a prompt. `deep` runs all five, for agents, batch jobs, and evaluation. `auto` lets a router choose per question.

**Retrieval scope**
: Request limits applied before ranking: license classes, source labels, publication years, authors, journals, excluded DOIs, and retracted papers. Every layer applies the scope inside its own query.

**Reranker**
: An optional second pass that reads the question and the candidate passages and reorders them. Off by default until an evaluation on the corpus shows it helps.

**Stage trace**
: A layer's status (`success`, `empty`, `disabled`, `skipped`, `timeout`, or `error`), duration, and candidate count for one request. Traces contain no query or passage text, so they are safe to log.

## Graph and corpus

**Ontology**
: The entity and relation types declared for a field in `domain/domain.yaml`. The graph builder drops anything outside those declarations, so the ontology controls what the knowledge graph contains.

**Entity**
: A named concept the builder found in the documents, of one of the entity types declared in the ontology, with the surface forms it appeared under and pointers to the chunks that mention it.

**Knowledge graph**
: Entities and the typed, directed relationships between them, stored as ordinary Postgres rows. Each relationship keeps the quoted phrase that stated it and a confidence score.

**Community**
: A cluster of closely connected entities, with a model-written summary and an embedding of that summary. Communities answer big-picture questions no single passage covers.

**Relationship confidence**
: A score on each graph edge: 1.0 for a direct statement, 0.7 for a strong implication, 0.4 for an inference across sentences. Repeated extraction keeps the highest score seen.

**Corpus manifest**
: `data/corpus.jsonl`, one JSON line per document with its path, metadata, source label, and license class.

**License class**
: A document's redistribution rights: `public`, `open_commercial`, `open_noncommercial`, `restricted`, or `unknown`. A request that restricts rights never sees documents outside its list, and `unknown` is excluded unless named.

**Source label**
: Your own grouping for documents, such as `journal_papers` or `agency_reports`, recorded in the manifest and usable as a retrieval filter.

**Corpus campaign**
: The `sci-rag campaign` workflow: find papers by topic or DOI list, resolve their open-access rights, download the PDFs that can be redistributed, and write a manifest.

**Corpus snapshot**
: A named record of the documents held at a moment, including per-document content hashes, one combined digest, counts, model versions, and the Git commit. A snapshot records identity; a backup holds the data.

**Known retraction**
: A document that Crossref reports as retracted, found by `sci-rag corpus enrich`. Answers exclude known retractions by default.

## Evaluation

**Seed question**
: A test question in `domain/eval_seed_questions.jsonl`, with the documents that answer it, distinctive phrases from those passages, and an optional reference answer.

**Drafted tag**
: The `drafted` tag on a seed question a model wrote and nobody has reviewed. Reports say how many questions still carry it.

**Honesty probe**
: A seed question tagged `unanswerable` because the corpus does not answer it. It checks whether the system reports the gap accurately.

**Ablation**
: Scoring retrieval with one layer switched off at a time, to measure what each layer contributes on the corpus.

**hit@k and MRR**
: hit@k is the share of questions with a relevant passage among the top k results. MRR (mean reciprocal rank) averages 1 divided by the rank of the first relevant passage.

**Grader (judge)**
: The model that scores generated answers. It grades grounding, citation accuracy, and completeness without seeing the reference answer, then grades correctness against the reference in a separate pass.

**Calibration**
: Comparing the grader's scores with a person's scores on the same answers, reported as Cohen's kappa per dimension.

**Confidence interval**
: The range around a reported mean from resampling the questions, so a difference between two runs can be read against the noise of a small question set.

**Corpus fingerprint**
: The counts and embedding versions recorded on every evaluation report, so a score stays tied to the corpus that produced it.

## Operations

**Degraded stage**
: A retrieval layer that timed out or failed while the rest of the request continued. Empty, skipped, and disabled are different statuses with different meanings.

**Version stamp**
: The provider, model, and dimension recorded with each stored embedding, so the rows an older model produced can be found and re-embedded after a model change.
