---
title: Bring your own domain
description: Turn a folder of documents into a knowledge base that answers questions about them, with the field's concepts in the graph and its own test questions scoring the result.
---

# Bring your own domain

Turn your documents into a knowledge base and score retrieval against reviewed questions.
Add LLM provider credentials to build the domain's concept graph and generate cited answers.
Source files and the manifest stay under `data/`; concepts, prompts, and questions stay under
`domain/`. No Python edits are required.

<div class="srag-meta-strip">
  <div><strong>You'll build</strong>A knowledge base over a corpus of your own</div>
  <div><strong>You'll need</strong>Documents on disk and a finished quickstart</div>
  <div><strong>Time</strong>Depends on corpus size and review</div>
  <div><strong>Credentials</strong>Needed for the graph and cited answers; every other step has an offline route</div>
  <div><strong>Tested with</strong>v0.5</div>
</div>

The worked example throughout is a group that studies membrane materials for water treatment and has 60 PDFs of papers, theses, and technical reports.

The main path uses seven commands:

```console title="Terminal"
$ uv run sci-rag draft manifest --folder data/raw      # 1. describe the documents
$ uv run sci-rag manifest lint data/corpus.jsonl        # 2. check the description
$ uv run sci-rag draft ontology --folder data/raw       # 3. name your concepts
$ uv run sci-rag build --manifest data/corpus.jsonl     # 4. ingest, then build the graph
$ uv run sci-rag draft questions --count 10             # 5. draft test questions
$ uv run sci-rag eval retrieval --ablation              # 6. measure
$ uv run sci-rag answer "a question in your field"      # 7. ask (needs LLM provider credentials)
```

Three commands draft a file for review: the manifest, ontology, and question
set. Each drafter also works without a configured model. `--print-prompt`
prints the prompt, and `--from-file reply.json` validates a saved reply.
[Drafting with a model](#drafting-with-a-model) covers the available routes
and the disclosure check required before sending sampled passages elsewhere.

## Before you start

| Requirement | Why | Check |
|---|---|---|
| A finished [quickstart](quickstart.md) | The database and its tables must exist first | `uv run sci-rag doctor` |
| The documents under `data/raw/` | Every step reads them | `ls data/raw \| wc -l` |
| LLM provider credentials, for two steps | The graph and the cited answer need them; ingestion, retrieval, and retrieval scoring do not | `uv run sci-rag doctor --probe` |
| A domain expert | Step 5 needs questions somebody can vouch for | |

There are two end states.

**With LLM provider credentials** the tutorial ends with the corpus ingested, a knowledge graph over the field's concepts, retrieval scored against its own questions, judged answers, and a cited answer to a question in the field.

**Without one** it ends with the corpus ingested, the concepts and questions written and validated, and retrieval scored against those questions. Four commands need a credential: `graph extract`, `graph communities`, `eval answers`, and `sci-rag answer`. [Offline: what you can prove without a model](#offline-what-you-can-prove-without-a-model) lists the route in one place.

## Step 0: run the setup wizard

A project created by `sci-rag new` already contains its setup decisions and
defaults. Skip to step 1.

In a checkout cloned or created from the GitHub template, run the same setup wizard in place:

```bash
uv run sci-rag init --advanced
```

Advanced asks every applicable question. Run `uv run sci-rag init` without a
mode to choose between Quick and Advanced. `--quick` takes the short path
with defaults for the rest. `--no-tty` gives plain numbered prompts,
`--dry-run` shows what setup would change without writing, and `--defaults`
answers every question with the shipped default.

Unlike `sci-rag new`, `sci-rag init` does not run the live credential check. It uses the key or project entered as given. Run `uv run sci-rag doctor --probe` afterward to confirm the provider accepts it.

Setup writes ordinary files, and nothing regenerates them later. Re-run it to change several answers at once, or edit the files directly:

| Setup area | Where to review it |
|---|---|
| Project name, description | `domain/domain.yaml`, `pyproject.toml`, `README.md` |
| Credentials, models, embedding dimension | `.env`; a dimension change needs a migration and re-embedding |
| Ontology | `domain/domain.yaml`; step 3 |
| Corpus source | `data/corpus.jsonl`, `data/dois.txt`, or a `make corpus` target; steps 1 and 2 |
| PDF parser, reranker | `pyproject.toml` extras, `domain/domain.yaml` |
| Environment manager | `Makefile`, CI, `Dockerfile`, dev container, docs |
| Infrastructure, demo, license, Git | Ordinary project files |

## Step 1: collect your documents

Put PDFs, HTML pages, Markdown, or plain-text files in `data/raw/`.

- Choose documents that contain answers. Reviews, reports, and characterization papers hold more retrievable facts than commentary and slide decks.
- Know each document's redistribution rights. The system quotes these documents back to people. A public-domain or CC BY document is fine anywhere. A paywalled PDF you legitimately hold is fine for your own instance, but mark it `restricted` so it never appears on a service you share.
- Start with a corpus small enough to inspect and defend. A curated set plus
  the evaluation step gives clearer feedback than an unreviewed dump.

For a first pass with no manifest, `uv run sci-rag build data/raw` ingests the
folder, marks every document `unknown` for rights, and builds the graph when a
credential is present. Use this route for a first spike only.

A document is ingested once. A later manifest for the same file is skipped as
a duplicate, so its rights and metadata are not added. To start over, remove
the documents with `sci-rag corpus delete` and ingest from the manifest.

## Step 2: describe your documents

The manifest, `data/corpus.jsonl`, has one JSON line per document, and it is where two things the kit cannot guess come from: the metadata a citation needs, and whether the document's text may be redistributed.

Draft it, then review it:

```bash title="Terminal"
uv run sci-rag draft manifest --folder data/raw
```

The drafter reads each document's opening pages through the same parsers ingestion uses and proposes a title, authors, year, DOI, journal, and a shared source label per document. Typing sixty of those by hand is how a manifest ends up with three spellings of one journal, so the draft is worth having even when every row needs a correction. Review `data/corpus.jsonl.proposed`, then move it into place, or re-run with `--apply`.

Every drafted row says `license_class: unknown`, and the command reports how many documents need a rights decision. Retrieval treats `unknown` as unsafe: those documents stay reachable from your own terminal and drop out of any request that restricts rights. When the drafter finds a license sentence in the document, it quotes the sentence into `license_source` for you to read.

For a handful of documents, write the file by hand:

```jsonl title="data/corpus.jsonl"
{"path": "raw/lee-2021-fouling-review.pdf", "title": "Membrane Fouling Mechanisms: A Review", "authors": ["Lee, S.", "Park, J."], "year": 2021, "doi": "10.1000/example", "license_class": "open_commercial", "source": "journal_papers"}
{"path": "raw/epa-membrane-guidance.pdf", "title": "EPA Membrane Filtration Guidance Manual", "authors": ["US EPA"], "year": 2005, "license_class": "public", "source": "agency_reports"}
{"path": "raw/chen-thesis.pdf", "title": "Chen PhD Thesis", "year": 2023, "license_class": "restricted", "source": "theses"}
```

`path` is relative to the manifest file and is the only required field.
`license_class` is one of `public`, `open_commercial`,
`open_noncommercial`, `restricted`, or `unknown`; aliases such as `CC-BY`
and `cc0` are understood. `source` is your own grouping label and becomes a
retrieval filter. Use labels that readers can apply consistently. The
[configuration reference](configuration.md#datacorpusjsonl) describes every
field.

Check the file before ingesting it:

```bash
uv run sci-rag manifest lint data/corpus.jsonl
```

The linter reports every problem at once with line numbers: missing files, paths listed twice, unsupported file types, entries with no title, and misspelled keys the loader would ignore. It is strict about `license_class` because ingestion is not: a mistyped value such as `CC-BY-NC-ND-4.0` is normalized to `unknown` without an error, which removes the document from results you expected it in.

<div class="srag-checkpoint" markdown>
**Checkpoint: the manifest is clean and the rights are decided**

`manifest lint` reports no problems. No row still says `license_class: unknown` unless that is intended. The count the linter prints is the number of rights decisions still owed.
</div>

## Step 3: name your concepts

`domain/domain.yaml` declares the field's entity and relation types. Together,
they form the ontology. The graph builder extracts only what the ontology
declares, so a concept without a matching type is invisible to the graph even
when the documents mention it often. Replace the shipped agricultural types
with your own.

Draft it from the documents, then edit:

```bash title="Terminal"
uv run sci-rag draft ontology --folder data/raw
```

Review `domain/domain.yaml.proposed`, or re-run with `--apply`. After ingestion, drop `--folder` and the drafter samples the corpus in the database. For an ontology that is mostly right already, `--refine` has the model propose only additions and removals, with a reason for each removal. `--cold` drafts from the description alone. The tuned `retrieval:` and `compression:` blocks carry over unchanged in every case.

This file gets edited by hand in every project. Filled in for the worked example:

```yaml title="domain/domain.yaml"
name: "Membrane Materials KB"
description: >
  Membrane chemistry, fouling behavior, and separation performance for
  water treatment applications.

entity_types:
  - name: Membrane
    description: "A membrane type or product (thin-film composite, ceramic UF)"
  - name: Material
    description: "A polymer, ceramic, or coating material (polyamide, PVDF, graphene oxide)"
  - name: Contaminant
    description: "A species being removed (NaCl, boron, PFAS, natural organic matter)"
  - name: FoulingMechanism
    description: "A fouling mode (scaling, biofouling, organic adsorption)"
  - name: Process
    description: "A treatment process or operation (reverse osmosis, backwashing)"
  - name: PerformanceMetric
    description: "A measured performance quantity (flux, rejection, permeability)"
  - name: Treatment
    description: "A cleaning or surface modification (chlorination, zwitterionic coating)"

relation_types:
  - name: MADE_OF
    description: "Membrane is made of material"
  - name: REMOVES
    description: "Membrane or process removes contaminant"
  - name: SUFFERS_FROM
    description: "Membrane or material suffers from fouling mechanism"
  - name: MITIGATED_BY
    description: "Fouling mechanism is mitigated by treatment"
  - name: MEASURED_AT
    description: "Metric measured at a condition or value"
  - name: IMPROVES
    description: "Treatment or material improves a performance metric"
```

Use these checks while editing:

- Start from the entity types produced by the drafter, then use evaluation to
  decide whether to combine or split them. Ask what column headings an expert
  would use to organize a spreadsheet of the field's facts.
- Write each description as a prompt. The extraction model sees it verbatim, and concrete examples in parentheses do more than abstract phrasing.
- Make each relation read as a sentence: "polyamide SUFFERS_FROM chlorine degradation".

Update `query_classes` in the same file with the kinds of questions users
ask. Give each one trigger keywords and a one-line description of a useful
answering passage. These steer the retrieval layer that writes a hypothetical
answer and searches for similar text.

## Step 4: build the knowledge base

One command ingests the manifest and then builds the graph:

```bash
uv run sci-rag build --manifest data/corpus.jsonl
```

Ingestion parses each document, splits it into chunks that keep their section headings and tables intact, embeds the chunks, and stores everything in Postgres in one transaction per document. This part runs on any embedding setup, including the offline one, so a corpus can be loaded and inspected before any model is involved.

The graph needs a model. The builder reads every chunk, extracts entities and relationships from the ontology, clusters related entities, and writes a summary of each cluster. Without a credential, `build` says so and stops after ingestion. Vector and keyword retrieval work at that point. The two graph steps are also available on their own, which is how you add the graph later or rebuild it after changing the ontology:

!!! note "Needs LLM provider credentials"

    ```bash
    uv run sci-rag graph extract
    uv run sci-rag graph communities
    ```

    Without a credential these exit 1 at the model boundary. Skip them and continue; nothing later in this tutorial depends on the graph except the graph's own checkpoint.

Then look at what the database holds:

```bash
uv run sci-rag stats
uv run sci-rag retrieve "a question in your field" --profile interactive
```

<div class="srag-checkpoint" markdown>
**Checkpoint: the corpus and the graph both look like the field**

`sci-rag stats` after ingest: documents produced chunks, and the license
classes match the manifest.

`sci-rag retrieve` with a question from the field: the top chunks are recognizable, and the stage table names the layer that found each one.

`sci-rag stats` after the graph built: entities and relationships are present.
Inspect a sample because counts alone cannot establish graph quality. If the extracted
concepts do not represent the field, return to step 3, redraft with
`--refine`, and run `graph extract` again.

Offline, the first two readings are the checkpoint. There are no entities to count.
</div>

## Step 5: write seed questions, then measure

`domain/eval_seed_questions.jsonl` needs 10 to 20 questions a domain expert can vouch for. Every retrieval and answer score is computed against them, which makes this the most important manual step in the tutorial: a question set nobody stands behind produces numbers nobody can act on.

Draft the first ten, then sign off on each one:

```bash title="Terminal"
uv run sci-rag draft questions --count 10
```

The drafter samples passages from the corpus, asks the model for questions grounded in them, and then verifies in Python that every quoted evidence phrase appears in a passage from a document the question names. Rows that fail are dropped and reported.

Every drafted row carries a `drafted` tag. While any remain, `sci-rag eval retrieval` and `sci-rag eval answers` state in their reports that the ground truth is unreviewed. Read each question, check it against the document it cites, and delete the tag. That deletion is the sign-off; nothing removes the tag for you.

When real questions from users already exist, `uv run sci-rag draft seed-from-answers questions.txt` takes one question per line, answers each, and proposes the reference answer and evidence phrases from what the answer cited. It keeps a phrase only when it appears verbatim in both the answer and the source. These rows arrive tagged `drafted` too.

Hand-written questions go in the same file, one JSON object per line:

```jsonl title="domain/eval_seed_questions.jsonl"
{"id": "pfas-rejection", "question": "What PFAS rejection does a polyamide RO membrane achieve?", "reference_answer": "Above 99 percent for long-chain PFAS at typical seawater RO conditions, per Lee 2021.", "reference_titles": ["Membrane Fouling Mechanisms: A Review"], "evidence_phrases": ["99", "long-chain PFAS"], "tags": ["performance"]}
```

Choose evidence phrases distinctive enough that finding them means finding the answer; numbers with units work best. Include one or two questions whose answers span documents. Include one question the corpus cannot answer, tagged `unanswerable`, to check that the system reports the gap. The [configuration reference](configuration.md#domaineval_seed_questionsjsonl) describes every field.

Then measure:

```bash
uv run sci-rag eval retrieval --ablation
```

This runs offline. It scores retrieval against the seed questions and prints one row per layer configuration, which shows what each layer contributes on this corpus and, over time, whether a change to the ontology or the corpus made retrieval better or worse. Grading generated answers is a second pass and needs a model:

!!! note "Needs LLM provider credentials"

    ```bash
    uv run sci-rag eval answers
    ```

Compare every row against `full_deep`, the row with every layer on. If `no_graph` matches `full_deep`, the measured graph contribution is zero. That usually points to the ontology, sometimes to a small corpus. Edit the ontology or the corpus, run again, and compare. [Evaluate your pipeline](evaluation.md) explains every column.

## Step 6: adjust the prompts (optional)

The prompts in `domain/prompts/` are short Markdown files. For most fields only two are worth touching:

- `entity_extraction.md`: keep the rules and change the example JSON names to the field's own, so the model sees the expected register.
- `answer.md`: add domain-specific answer norms, such as "always report flux in LMH" or "state the test conditions with every rejection value".

A model can reword them for the field while keeping the job identical:

```bash title="Terminal"
uv run sci-rag draft prompts entity_extraction
uv run sci-rag draft prompts answer
```

Every `$SLOT` has to survive, so the rewrite is rendered against dummy values before it is written. These two prompts are the only ones the command touches. The judge prompts, the compression prompt, and the drafting prompt are refused by name, because rewording them would change what the scores mean.

Prompt wording moves every downstream number. Run `sci-rag eval retrieval --ablation` again after a rewrite and compare.

## Step 7: ask, then serve

With a credential, ask a question in the field. Ask one the corpus cannot answer as well; the response should say so.

!!! note "Needs LLM provider credentials"

    ```bash
    uv run sci-rag answer "a question in your field"
    ```

Serve the same thing to people and agents:

```bash
uv run sci-rag serve
```

Before anyone else connects, set API keys in `.env` (see `.env.example`) and decide what an outside caller may see. A public or semi-public endpoint should pin callers to `{"license_classes": ["public", "open_commercial"]}` so `restricted` and `unknown` documents stay internal. [REST, MCP, and Python API](api.md) covers keys, scopes, and the agent tools. [Deploy on Google Cloud](deploy-gcp.md) covers Cloud Run.

<div class="srag-checkpoint" markdown>
**Checkpoint: the knowledge base is real**

Offline, ask a question in the field through `POST /v1/query`. The response names documents from the manifest, with the license class it declared and the retrieval layer that found each one.

With a credential, the same question through `POST /v1/answer` or `sci-rag answer` returns numbered citations to those documents.
</div>

## Drafting with a model

Three of the steps above draft a file: the manifest, the ontology, and the seed questions. `sci-rag new` and `sci-rag init` can also draft the ontology from a one-sentence description before any document exists; that draft is a first guess to replace in step 3.
Only `sci-rag new` checks the credential with a small live request first. `sci-rag init` uses the key or project entered as given.

Every drafter offers the same three routes to the same validated file.

=== "Generate it"

    The configured model drafts the file. The reply is validated through the same model the loader uses, so a draft is never something the kit would later refuse to load.

    ```bash title="Terminal"
    uv run sci-rag draft questions --count 10
    ```

=== "Use an approved assistant"

    `--print-prompt` writes the rendered prompt, including sampled corpus
    passages, to standard output. Before sending that output to an assistant,
    confirm that the documents' rights, privacy requirements, the provider's
    terms, and your institution's policy allow the disclosure. If they do not,
    use an approved provider or write the file yourself. Save the permitted
    reply and feed it back through validation.

    ```bash title="Terminal"
    uv run sci-rag draft questions --count 10 --print-prompt > prompt.txt
    # send prompt.txt only to an approved assistant; save the JSON reply as reply.json
    uv run sci-rag draft questions --count 10 --from-file reply.json
    ```

    Pass the same `--count` and `--folder` values to both commands. They decide which passages are sampled, and the reply is validated against the passages the assistant saw.

=== "Write it yourself"

    Every file format is shown above, and a drafter never touches a hand-written file.

Four rules hold for every drafter:

- Nothing is overwritten. A run writes `<file>.proposed` and prints a summary; moving it into place is a deliberate step. `--apply` skips the proposal, and for seed questions it appends, never replaces. `--dry-run` writes nothing.
- Rights are never guessed. Every drafted manifest row says `unknown`.
- Drafted questions stay labeled until a person removes the `drafted` tag. The evaluation reports repeat the label until then.
- `domain/eval_calibration_labels.jsonl` is never drafted. It holds human scores used to check the model grader, and generating it with a model would remove the only independent measurement.

`sci-rag doctor` reports on the domain files beside its usual checks: whether the ontology is large enough to extract against, whether every answerable question cites a document that exists, how many questions still carry the `drafted` tag, and how many manifest rows have no rights decision. Run it after changing anything in `domain/`.

## Offline: what you can prove without a model

Set `SCI_RAG_EMBEDDING_PROVIDER=local-hash` in `.env`, then run the route in
order. The `--print-prompt` commands below still include sampled corpus text;
answer locally or apply the disclosure check above before sending it to a
provider.

```bash
uv run sci-rag draft manifest --folder data/raw --print-prompt   # answer it yourself
uv run sci-rag draft manifest --folder data/raw --from-file reply.json --apply
uv run sci-rag manifest lint data/corpus.jsonl
uv run sci-rag draft ontology --folder data/raw --print-prompt
uv run sci-rag draft ontology --folder data/raw --from-file reply.json --apply
uv run sci-rag build --manifest data/corpus.jsonl
uv run sci-rag stats
uv run sci-rag retrieve "a question in your field" --profile interactive
uv run sci-rag draft questions --count 10 --print-prompt
uv run sci-rag draft questions --count 10 --from-file reply.json --apply
uv run sci-rag eval retrieval --ablation
uv run sci-rag serve
```

The offline embedder uses lexical word matching. Its retrieval scores establish a baseline for this corpus. A credentialed run uses a different embedding method and needs its own measurement. The offline route excludes the knowledge graph, community summaries, graded answers, and generated cited answers.

## The improvement loop

After adding or correcting documents, run `build` again; it processes only
new content. Then run the two evaluation commands and read the diffs. When the
system misses a user question, add it as a seed question before changing the
pipeline so the fix is measured and the question is retained.

## Next steps

- Read the evaluation table before changing a retrieval setting: [Evaluate your pipeline](evaluation.md)
- Grow the corpus from a topic or a DOI list: [Run a corpus campaign](campaigns.md)
- See what a license class does to retrieval: [Scope precedes ranking](methodology.md#7-scope-precedes-ranking)
- Put the service where the group can reach it: [Deploy on Google Cloud](deploy-gcp.md)
