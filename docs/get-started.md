---
title: Getting started
description: Install Sci RAG Kit, run the demo corpus, then bring in a corpus of your own.
---

# Getting started

Install the kit with `pipx install sci-rag-kit`, then run `sci-rag new` to
create a configured project. Run the bundled demo first, then replace it with
your own documents. If a step fails, open the [Troubleshooting Guide](troubleshooting.md).

<div class="srag-rows" markdown>

[<span class="srag-row__title">Quickstart</span><span class="srag-row__copy">Create a project, start the database, ingest the demo corpus, ask a question, and serve the result. About ten minutes.</span>](quickstart.md){ .srag-row }

[<span class="srag-row__title">Bring your own domain</span><span class="srag-row__copy">Seven commands from a folder of documents to a knowledge base that answers questions about them.</span>](bring-your-own-domain.md){ .srag-row }

[<span class="srag-row__title">Troubleshooting</span><span class="srag-row__copy">Start from the symptom, run `sci-rag doctor`, and follow the fix.</span>](troubleshooting.md){ .srag-row }

</div>

## What the kit sets up

A knowledge base uses one Postgres database and one service. Documents become
passages with vectors for semantic search, full-text entries for keyword
search, and links to the concepts they mention. With LLM provider credentials,
answers include numbered citations to those passages.

The same service handles the command line, REST, and agents over MCP. MCP is
the Model Context Protocol used by tools such as Claude Code to call external
systems. An agent can therefore search and cite the corpus through the same
service as a person at the terminal.

The setup wizard asks for six setup decisions and any LLM provider credentials
you want to use. For a credential-free first pass, choose Offline; ingestion,
retrieval, and retrieval scoring still work. Add credentials later to build the
graph and generate answers.

The generator configures the live template and writes these answers directly
into the project files. The resulting tree contains no placeholders to fill in.

## Project structure

The directory structure below is produced upon running the `sci-rag new` command.

<div class="srag-tree">your-project/
├── domain/                  the field
│   ├── domain.yaml          the concepts and relationships the graph looks for
│   ├── prompts/             the wording sent to the model, one file per job
│   └── eval_seed_questions.jsonl   questions with known answers, for scoring
├── data/
│   ├── raw/                 the source documents
│   ├── corpus.jsonl         one line per document: title, authors, rights
│   └── demo/                five synthetic documents, so the pipeline runs on day one
├── .env                     credentials, database URL, model names
├── src/sci_rag/             the pipeline; rarely opened in a normal project
├── migrations/              database tables, applied by make setup
├── tests/                   runs offline; database tests use a disposable database
├── infra/terraform/         optional Google Cloud deployment
└── docs/                    this site</div>

`domain/domain.yaml` names the entity types in the field, such as `Membrane`
or `Contaminant`, and their relationships, such as `REMOVES` or
`SUFFERS_FROM`. The graph builder extracts only what this file declares.
`data/corpus.jsonl` records each document's citation metadata and
redistribution rights. `domain/eval_seed_questions.jsonl` holds the questions
used for scoring; each one needs expert review.

[Architecture](architecture.md) explains what each package under `src/sci_rag/` owns, for projects that change the pipeline itself.

## Recommended path

1. Run the [quickstart](quickstart.md). Offline mode gives a credential-free first pass. AI Studio enables the model-backed steps with the shortest local setup.
2. Follow [Bring your own domain](bring-your-own-domain.md) with a corpus you can inspect and defend. The drafting commands write the first version of every domain file.
3. Run [Evaluate your pipeline](evaluation.md) before changing any retrieval setting. Its table shows what each retrieval layer contributes on the corpus at hand.
4. When the corpus should grow beyond what is on disk, [Run a corpus campaign](campaigns.md) finds papers by topic or DOI list and checks their rights.

Still deciding whether this is the right tool? Read the [FAQ](faq.md) and
[Choosing Sci RAG Kit](choosing-sci-rag-kit.md). If Postgres, credentials, or
parsing get in the way, run `uv run sci-rag doctor` before following the
[Troubleshooting Guide](troubleshooting.md#troubleshooting-guide).
