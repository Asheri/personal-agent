---
title: Quickstart
description: Create a project, start the database, ingest the demo corpus, ask a question, and serve the result.
---

# Quickstart

In about 10 minutes, you will turn the bundled demo corpus into a knowledge base
served over REST and MCP. Add LLM provider credentials to generate a cited answer.
Once the demo works, replace it with your own documents.

<div class="srag-meta-strip">
  <div><strong>You'll build</strong>A served knowledge base over the demo corpus</div>
  <div><strong>You'll need</strong>Python, pipx, uv, and a way to run PostgreSQL</div>
  <div><strong>Time</strong>About 10 minutes</div>
  <div><strong>Credentials</strong>Optional; the answer step needs LLM provider credentials</div>
  <div><strong>Tested with</strong>v0.5</div>
</div>

## Before you start

| Requirement | Why | Check |
|---|---|---|
| Python 3.11 or 3.12 | The supported runtime | `python --version` |
| [pipx](https://pipx.pypa.io/) | Installs the setup wizard in its own environment | `pipx --version` |
| [uv](https://docs.astral.sh/uv/) | Installs the project's dependencies and runs its commands | `uv --version` |
| Docker, or a PostgreSQL 16 through 18 server with pgvector | The database everything lives in | `docker --version` |
| Generation credential | The graph and generated answers | Default: `SCI_RAG_DEEPSEEK_API_KEY`; Google is an alternative |

Docker is the simplest way to get a database with the pgvector extension on a laptop, which is why the kit defaults to it. Without Docker, [Configure Postgres backend](run-postgres.md) covers a conda-forge server, a system server such as Postgres.app, and the optional Cloud SQL development helper.

## 1. Create the project

### The setup wizard

The setup wizard runs from whatever directory holds projects and writes a configured, git-initialized project directory there, with the first commit already made.

```console title="Terminal"
$ pipx install sci-rag-kit
$ sci-rag new
```

Choose **Quick**. It asks for six setup decisions: the project name, a one-line
description, contact email, environment manager, credential mode, and source
of the first documents. It then asks for the LLM provider credentials you want
to use and applies the shipped defaults for the remaining settings.

Choose **Offline** when you do not want LLM provider credentials yet. Retrieval
works without one; add a credential later for the graph and generated
answers. Choose **Advanced** when you need to set models, parsing, reranking,
infrastructure, or licensing yourself.

The environment-manager menu preselects the first supported environment manager found on `PATH`. That preselection does not change what `--defaults` or an answers file would choose. If `SCI_RAG_GOOGLE_API_KEY` or `GOOGLE_API_KEY` is already set in your shell, the setup wizard offers to reuse it without displaying its value. Any key you type is masked. Pass `--no-tty` for plain numbered prompts.

The setup wizard checks the credential with one small model request before it downloads the template. A failed check offers recovery choices and keeps the answers given so far. When the setup wizard finishes, change into the new directory and continue at step 3. Step 2 covers changing the credential mode it wrote.

### Other entrypoints

To read the kit before creating a project, clone it and run the demo from the clone:

```console title="Terminal"
$ git clone https://github.com/sustainability-software-lab/sci-rag-kit.git
$ cd sci-rag-kit
```

The other routes start from the same tree:

- GitHub's **Use this template** button creates a repository under the signed-in account.
- `sci-rag init` configures an existing checkout. It asks the same Quick or Advanced questions and skips the credential check.
- The included dev container installs the project and starts Postgres. In GitHub Codespaces, continue at step 2 after it opens.

## 2. Choose a credential mode

The setup wizard created `.env` with owner-only mode `0600` and wrote the chosen mode into it. Skip to step 3 unless that choice needs to change.

From a clone or the GitHub template, create the file yourself. The second command matters: the file is about to hold a credential, and `cp` alone leaves it readable by every account on the machine.

```console
$ cp .env.example .env
$ chmod 600 .env
```

On Windows, reset the copied ACL before removing inheritance so no unrelated
explicit access rule survives:

```powershell
Copy-Item -Force .env.example .env
icacls .env /reset
icacls .env /inheritance:r /grant:r "$($env:USERNAME):(F)"
```

The default credential mode is DeepSeek. Set `SCI_RAG_DEEPSEEK_API_KEY` to
your key; `SCI_RAG_DEEPSEEK_BASE_URL` defaults to
`https://api.deepseek.com`. Google is an alternative path: selecting it also
sets `SCI_RAG_LLM_PROVIDER=google`. Setting only `SCI_RAG_GOOGLE_API_KEY`
while the provider remains `deepseek` does not switch generation. Choose
Offline for a credential-free retrieval pass.

=== "AI Studio"

    One key with no manual Google Cloud setup, plus real embeddings and
    answers. Create a key at [Google AI Studio](https://aistudio.google.com/apikey),
    then set:

    ```dotenv title="~/.env"
    SCI_RAG_GOOGLE_API_KEY=your-key-here
    SCI_RAG_LLM_PROVIDER=google
    SCI_RAG_LLM_MODEL=gemini-3.6-flash
    SCI_RAG_EMBEDDING_PROVIDER=google
    SCI_RAG_EMBEDDING_MODEL=gemini-embedding-001
    SCI_RAG_EMBEDDING_DIM=1024
    ```

=== "Vertex AI"

    The same models, billed through an existing Google Cloud project. Authenticate once, then set the project:

    ```console
    $ gcloud auth application-default login
    ```

    ```dotenv title="~/.env"
    SCI_RAG_GCP_PROJECT=your-project-id
    SCI_RAG_LLM_PROVIDER=google
    SCI_RAG_LLM_MODEL=gemini-3.6-flash
    SCI_RAG_EMBEDDING_PROVIDER=google
    SCI_RAG_EMBEDDING_MODEL=gemini-embedding-001
    SCI_RAG_EMBEDDING_DIM=1024
    ```

=== "Offline"

    No model at all. The kit uses a built-in embedder based on lexical word matching:

    ```dotenv title="~/.env"
    SCI_RAG_EMBEDDING_PROVIDER=local-hash
    ```

    Parsing, chunking, storage, retrieval, and retrieval scoring work. The graph, generated answers, and graded answers wait until a credential is added.

## 3. Install the project and create the database tables

```console title="Terminal"
$ make setup
```

`make setup` starts the selected database backend, runs
`uv sync --extra modelscope-embedding --extra openai`, and creates the tables,
in that order. Docker is the template default and listens on host port `5433`,
a port chosen so it does not collide with a system PostgreSQL on the usual
5432. Projects generated with pixi or conda start a bundled server instead,
and any project can point at a PostgreSQL 16 through 18 server you already
run.

If port `5433` is already taken, often by another Sci RAG Kit project, change the `ports` entry in `docker-compose.yml` to `"5434:5432"` and set the same port in `SCI_RAG_DATABASE_URL`. [Troubleshooting](troubleshooting.md#docker) has the full recovery.

**Expected output**

```text
Database schema is up to date.
```

<div class="srag-checkpoint" markdown>
**Checkpoint: the foundation is healthy**

Run `uv run sci-rag doctor`. Configuration, domain, database, and schema report healthy. An empty corpus, and a missing credential in Offline mode, are informational at this point.
</div>

## 4. Ingest the demo corpus

```console
$ make demo
```

This ingests five short synthetic documents about agricultural residues, runs one retrieval to show what comes back, and scores retrieval against the bundled test questions. The documents were written for the kit: their numbers are plausible but fictional, which keeps the demo free of any rights question while still exercising every part of the pipeline.

**Expected output**

```text
Ingestion report
5 ingested, 0 skipped, 0 failed.

vector     success     ...
keyword    success     ...
graph      disabled    ...
```

`graph disabled` is expected here. The retrieval that `make demo` runs uses
the fast profile, which leaves the model-dependent layers off. Step 6 turns
them on.

<div class="srag-checkpoint" markdown>
**Checkpoint: the evidence is visible**

The retrieval table shows each result's title, the section it came from, its license class, the layers that found it, and an excerpt. The stage table says, for each layer, whether it succeeded, found nothing, was disabled, or failed.
</div>

## 5. Ask a question

With a credential:

```console
$ uv run sci-rag answer "How much rice straw was generated in the Colusa Basin in 2023?"
```

The expected answer for the demo corpus is approximately 302,000 dry tons, citing the synthetic resource assessment. Read the cited passage as well as the number: the citation is the part that makes the answer checkable, and it is the habit worth forming before a real corpus arrives.

In Offline mode this command retrieves normally, then declines to answer and names the credential to set. It does not invent an answer, which is the same behavior a credentialed run shows when the corpus holds nothing relevant.

If the stage table shows `timeout` for vector, graph, or HyDE, the model call was slow. A timeout says nothing about whether the corpus contains data. Raise `SCI_RAG_PROVIDER_CALL_TIMEOUT_S` in `.env` (60 seconds by default) and run the command again.

## 6. Build the graph and take the deep path (optional)

With a credential:

```console
$ make demo-cloud
```

This extracts the demo domain's concepts and relationships from every chunk and summarizes the clusters they form, which is the work the graph layer needs before it can contribute. It then asks a question whose answer spans several documents and scores retrieval with each layer switched off in turn, so the report shows what each one is worth on this corpus. Reports land under `eval_results/`.

<div class="srag-checkpoint" markdown>
**Checkpoint: the graph produced evidence**

Open the newest report under `eval_results/`. It names the corpus, the models,
the enabled layers, and a score per layer configuration. On this five-document
demo, most rows score the same. Use your own evaluation set to measure how the
layers behave on your corpus.
</div>

## 7. Serve it to people and agents

```console
$ uv run sci-rag serve
```

One process serves:

- the interactive API reference at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- a description of the corpus at [http://127.0.0.1:8000/v1/corpus-manifest](http://127.0.0.1:8000/v1/corpus-manifest)
- agent tools over MCP at `http://127.0.0.1:8000/mcp`

Try retrieval over REST:

```console
$ curl -s -X POST http://127.0.0.1:8000/v1/query \
    -H 'Content-Type: application/json' \
    -d '{"query": "rice straw availability", "top_k": 3}'
```

Connect a local agent such as Claude Code:

```console
$ claude mcp add demo-corpus -- uv run --directory "$(pwd)" sci-rag mcp
```

Ask the agent a question and tell it to use `demo-corpus`. A `search_corpus` or `answer_question` tool call should appear in its transcript. Discard an answer with no tool call because it came from the agent's memory without consulting the corpus.

<div class="srag-checkpoint" markdown>
**Checkpoint: each interface reaches the same service**

One Postgres database holds the documents, their chunks and vectors, the full-text index, and, after step 6, the concept graph. One service answers the command line, REST clients, and agents the same way. The reports under `eval_results/` record how it did on known questions.
</div>

## Next steps

- Replace the demo with a real corpus: [Bring your own domain](bring-your-own-domain.md)
- Something did not match this page: [Troubleshooting](troubleshooting.md)
- Understand what just happened: [How it works](learn.md)
- Put the service where other people can reach it: [Deploy on Google Cloud](deploy-gcp.md)
