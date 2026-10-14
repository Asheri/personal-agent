---
title: How it works
description: Follow the pipeline from scientific documents to searchable evidence, cited answers, and evaluation.
---

# How it works

Sci RAG Kit connects scientific documents to cited answers through an end-to-end RAG pipeline.
See how ingestion, rights-aware retrieval, answer generation, and evaluation work together.

## The idea

A language model can answer from what it learned during training. Evidence for this workflow must
come from your corpus. Retrieval-augmented generation (RAG) finds relevant passages first. The answer model sees
those numbered passages and must cite them. If the retrieved sources do not contain an answer, the
kit says so.

For example, a question may ask how much straw a county produces while the source reports
harvested acres and a straw-to-grain ratio. The retrieval pipeline has to connect those different
wordings without losing the numbers or the section that explains them.

## What happens to a document

1. **Parse.** A PDF, HTML page, Markdown file, or text file becomes headings, paragraphs, and
   tables. Tables stay intact so a row keeps its columns and labels.
2. **Chunk.** The parser groups prose into pieces near the configured 800-token target. Each chunk
   keeps its document title and section path, and adjacent prose overlaps at the boundary.
3. **Embed.** An embedding represents each chunk as a vector. Similar meanings can then match even
   when the question and source use different words.
4. **Store.** Postgres holds the chunks, vectors, full-text index, document metadata, and license
   class. A document and its chunks commit in one transaction.
5. **Build the graph.** When LLM provider credentials are available, the kit extracts the entity and
   relationship types declared in the domain ontology. It retains evidence for each relationship
   and summarizes clusters of related entities. This optional layer can bring evidence from several
   documents into the candidate pool.

## What happens to a question

The enabled retrieval layers look for candidate passages in different ways.

| Layer | Finds passages by | Good at |
|---|---|---|
| Vector | closeness of meaning | questions phrased differently from the documents |
| Keyword | exact words and phrases | identifiers, chemical names, units |
| Graph | walking from the concepts in the question to passages that mention related concepts | answers that span documents |
| Community | matching against the cluster summaries | big-picture questions no single passage covers |
| Hypothetical answer | generating a search probe and finding passages near it | bridging question wording and document wording |

The hypothetical passage is a search probe. The kit keeps it out of answers and citations.

Each layer returns a ranked list. Weighted reciprocal rank fusion combines positions because a
cosine distance, a full-text rank, and a graph hop count use different scales. Agreement across
layers can move a passage higher in the final list.

The `interactive` profile enables vector and keyword retrieval. The `deep` profile can use all five
layers for agents, batch jobs, and evaluation. Layers run concurrently where their dependencies
allow. If one times out or fails, its trace reports the failure and the remaining layers continue.

Rights filters apply inside each retrieval query before ranking and limiting. This prevents an
ineligible passage from occupying a bounded candidate slot and then disappearing after the search.
Community summaries disable themselves for scoped requests because they combine evidence before a
request's scope is known.

The answer model receives the highest-ranked passages with stable numbers. Its response maps each
citation number back to the document and chunk that supplied the evidence.

## How the results are measured

Each domain has seed questions with reference evidence. Retrieval evaluation measures whether that
evidence appears and compares layer configurations on the same corpus. Answer evaluation uses two
separate model passes: grounding and citation accuracy are judged against retrieved sources, while
correctness is judged against the reference answer.

Reports record the corpus fingerprint, model identities, and git commit. That provenance identifies
what produced a run. Model-backed scores remain nondeterministic. Use the [evaluation
workflow](evaluation.md) to compare matched runs and the [benchmarks](benchmarks.md) to inspect the
current demo evidence.

## Read next

<div class="srag-rows" markdown>

[<span class="srag-row__title">FAQ</span><span class="srag-row__copy">Short answers to what this is, who it is for, and why each design decision went the way it did.</span>](faq.md){ .srag-row }

[<span class="srag-row__title">Choosing Sci RAG Kit</span><span class="srag-row__copy">How the kit compares with LightRAG, PaperQA2, LlamaIndex, and Microsoft GraphRAG.</span>](choosing-sci-rag-kit.md){ .srag-row }

[<span class="srag-row__title">Architecture</span><span class="srag-row__copy">What each package owns, how storage and concurrency work, and the five places built to be extended.</span>](architecture.md){ .srag-row }

[<span class="srag-row__title">Methodology</span><span class="srag-row__copy">The full specification: chunking, graph extraction, fusion, rights, answering, and evaluation, with the reasoning for each choice.</span>](methodology.md){ .srag-row }

</div>
