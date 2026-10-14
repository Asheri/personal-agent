# Changelog

Notable changes to sci-rag-kit. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) once past 1.0.

## [Unreleased]

### Changed

- **Generated conda projects and their compatibility harness now use
  setup-miniconda v4.** Both surfaces use the action's canonical
  `auto-activate` input.

## [0.5.0] - 2026-09-03

The release where the documented Google Cloud deployment was run end to end for
the first time, and `sci-rag build` takes a folder of documents to a queryable
knowledge base in one command.

Qualifying that deployment is what produced the fixes below. Four defects had
already shipped, and none of them was reachable by an offline test: a private
Cloud Run service could not authenticate at all, a deployed graph build
reported success and wrote nothing, `terraform destroy` left the Cloud SQL
instance running, and the prerequisite list omitted an API its own steps call.

### Added

- **`sci-rag build`** takes a folder or a manifest to a queryable knowledge
  base in one command: ingest, then graph extraction and community summaries.
  Without LLM provider credentials, or with `--no-graph`, it stops after ingestion
  and says so; vector and keyword retrieval already work at that point.
  Re-running only processes new chunks.

### Changed

- **The three documentation pages retired in this release keep answering at
  their old addresses.** `tour/`, `llm-assisted-setup/`, and `api-clients/`
  forward to the sections that absorbed them. The map lives in `mkdocs.yml`
  under `extra.redirects` and is applied by a small build hook, with no new
  dependency; a target that the build did not produce fails `make docs`.
- **Plain-mode wizard prompts show the question in words.** With `--no-tty`,
  piped input, or a dumb terminal, the wizard printed only the field name
  (`project_name (My Scientific KB):`). It now prints the same question the
  arrow-key menus ask above that line, and each menu choice carries its
  one-line explanation. The field line itself is unchanged, so scripts and
  the homepage transcript still parse it.
- **`sci-rag --help` groups commands by stage** (start here, build your
  knowledge base, ask questions, measure quality, serve, maintain) so the six
  commands a new project needs are not lost among the maintenance ones. Help
  strings were rewritten in plain words: no undefined "HyDE", "fused",
  "ablation", "tombstone", or "fail-closed" in a one-line summary.
- **The wizard's completion report now prints a path that works**: `make
  setup` before `sci-rag doctor`, where to put your documents, `sci-rag build`,
  and `sci-rag answer`. It used to skip the database step and never reached an
  answer.
- **`sci-rag ingest`, `graph extract`, and `graph communities` report a
  missing credential in one line** instead of a traceback, and `stats` checks
  the database connection before querying.
- **`sci-rag corpus enrich --mailto`** reads `SCI_RAG_CAMPAIGN_MAILTO` like
  the campaign commands do, so the address the wizard wrote is used.
- **Documentation rewritten for readability and trimmed to essentials.** Every
  reader-facing page was line-edited or rewritten in a plain, direct register:
  shorter sentences, terms defined where they are used, no aphorisms, each
  rule stated once on its home page, prose centered on what the kit does
  rather than on the reader, with the imperative kept for the steps, and a
  final pass that elaborates each concept with what it means for a project
  and varies sentence rhythm, in the register of Stripe's and
  cookiecutter-data-science's documentation. The rights page folded into the
  methodology (section 7) with a redirect; the FAQ answers at decision-plus-
  reason length; the domain tutorial leads with the recipe and moved its field
  semantics to the generated configuration reference, which now documents the
  corpus manifest and seed-question row formats from the source models.
- **Documentation restructured for people new to retrieval systems.** The
  README opens with what the kit does and a seven-command recipe. The site's
  Get started section is now Quickstart, Bring your own domain, and
  Troubleshooting, in that order; the Learn section became How it works and
  opens with a plain-language walkthrough of what happens to a document and
  to a question. Bring your own domain absorbed the LLM-assisted setup guide
  and leads with the recipe; the repository tour folded into Get started and
  Architecture; the typed-client guide became a section of the API reference.
  Three pages fewer, and every remaining page explains a term where it is
  first used.


### Fixed

- **A private Cloud Run deployment could not authenticate at all.** Cloud Run's
  frontend requires a Google identity token in `Authorization`, which is why
  the deploy guide tells you to send the kit key in `X-API-Key`. The server
  preferred `Authorization`, read the identity token as the kit key, and
  answered every authenticated request with `401 invalid_key`. No header
  combination worked. `X-API-Key` now wins when both are present: it is the
  caller naming the credential it means, while `Authorization` may have been
  set by the infrastructure in front of the app. Clients that send only
  `Authorization: Bearer <key>` are unaffected.
- **A deployed graph build reported success and wrote nothing.** The Terraform
  module set the app's `SCI_RAG_GCP_LOCATION` to the deployment region, but the
  default generation model is served from `global`. Every extraction batch
  returned `404`, the job exited without surfacing it, and `stats` showed zero
  entities against a fully ingested corpus. The module now exposes
  `model_location`, defaulting to `global`, separate from the `region` that
  places infrastructure.
- **`terraform destroy` could strand the Cloud SQL instance.** Deleting a Cloud
  Run service returns before its instances stop holding Postgres sessions, so
  the `DROP DATABASE` that followed raced them and failed. Terraform had
  already removed everything else, leaving the most expensive resource running
  behind an error that named the database rather than the survivor. Deleting
  the instance removes its databases and roles anyway, so that separate drop
  was redundant; it is gone.
- **The deploy guide's prerequisites missed `storage.googleapis.com`**, which
  the corpus staging step needs, so a reader starting from an empty project
  failed partway. The guide also pointed at a bare `terraform destroy` that
  contradicted its own reviewed teardown, ran `terraform init -upgrade` in a
  way that rewrote the tracked lockfile, and did not mention that Terraform
  reads `deletion_protection`, `force_destroy`, and `deletion_policy` from
  stored state rather than from the variables passed to a destroy.
- **`docs/extend.md` said `us-central1` "serves Gemini."** It does not serve
  the kit's own default generation model, which answers only from `global`.

## [0.4.1] - 2026-08-31

A fix release, driven by qualifying the documented routes against real
credentials for the first time. The headline is that a reader creating a new
Google AI Studio key could not get an answer out of v0.4.0 at all.

### Fixed

- **The default generation model was refused for every newly issued AI Studio
  key.** `gemini-2.5-flash` shipped as the default and returns `404 ... no
  longer available to new users`, along with the rest of the 2.5 family.
  Because `extraction_model` and `judge_model` inherit `llm_model` when unset,
  one dead default took out generation, graph extraction, HyDE, community
  summaries, and the judge together. Embedding was unaffected. The default is
  now `gemini-3.6-flash`, verified live on both the AI Studio and Vertex
  credential paths.

  **Who this affected.** Only new credentials. An established Google Cloud
  project still answers `gemini-2.5-flash` through Vertex, which is why the
  default survived this long: the people who set it were not new users.

  **If you pinned the old model,** nothing changes. `SCI_RAG_LLM_MODEL` in your
  `.env` still wins. If you relied on the default and compare metrics across
  this release, rerun your evaluation rather than comparing numbers produced by
  two different models. Closes #248.

- **JSON-mode calls failed outright against Gemini 3.x models.** Structured
  output disables thinking with `thinking_budget=0`, which those models reject
  with a bare "Request contains an invalid argument". A fallback for exactly
  this case existed but matched on the word "thinking", which that message
  never contains, so it never fired. It now keys on the request being refused
  rather than on the provider's wording, while rate limits and server errors
  still propagate.

- **`X-Request-ID` was missing from error responses.** The header is added on
  the way out, so any problem response built after an unhandled exception had
  already unwound past that layer carried none, including every
  `internal_error`. The body quoted a `request_id` the caller could not read
  off the response, on exactly the response whose `detail` sends the reader to
  the logs to quote it. Every problem response now carries the header,
  whichever layer built it, and `docs/api.md` states the contract. Closes #192.

### Added

- **`sci-rag eval html RUN_DIR`** renders an evaluation run as one
  self-contained HTML page, for sharing with a collaborator who will never open
  a terminal. Inline styles and nothing fetched when the page opens, so it
  renders the same for the recipient as for you. It leads with the provenance
  receipt, carries the small-sample and drafted-ground-truth warnings next to
  the metrics, picks up `calibration.json` when it sits beside the report, and
  shades ablation cells whose confidence intervals overlap the baseline. Closes
  #36.

### Changed

- **The published benchmark numbers were republished, and the claim above them
  corrected.** The page promised reproduction within 0.1 on a metric and 10% on
  a count. Two reruns from identical recorded inputs moved the entity count 13%
  down and 12% up, so `temperature: 0.0` does not make graph extraction
  deterministic. The numbers are refreshed from their source reports and the
  page now names the graph counts as the known exception, to be read as one
  draw from a distribution. Closes #240.

- `sci-rag corpus snapshot` writes a trailing newline, so a fresh snapshot is
  committable as produced rather than failing the repository's own
  end-of-file hook.


## [0.4.0] - 2026-08-30

Everything below was unreleased until this version. The headline is that
`sci-rag new` reaches PyPI: published v0.3.0 had no `new` subcommand, so the
first two commands in the README, the homepage, and the quickstart ended at
`No such command 'new'`. The release workflow now runs that exact pair from a
clean pipx home before publishing, so a release that cannot open the wizard
fails before it reaches an index.

This version also closes the P0 documentation route audit, whose findings are
recorded under the sections below.


### Breaking

- An answers file may no longer request `ontology: draft_with_llm`. Every
  answers-file run is noninteractive, and drafting an ontology means reading
  what the model proposed and accepting or redrafting it, so the value was
  accepted and then replaced with `keep_demo_example`: generation exited 0 and
  produced the worked demo ontology rather than the draft the file asked for.
  It is now refused before anything is generated, with a message naming the
  alternatives.

  **Migration.** Write `ontology: keep_demo_example` or `ontology: blank` in
  the answers file, then draft into the generated project with
  `sci-rag draft ontology --from-corpus`. For automation with no terminal and
  no model call, that command's `--print-prompt` and `--from-file` pair runs
  the same validation. Interactive `sci-rag new` and `sci-rag init` are
  unchanged, and `--defaults` now selects `keep_demo_example` outright instead
  of announcing a skipped draft it was never going to attempt. Closes #164.

### Changed

- Database setup documentation now treats `make setup` as selected-backend
  dispatch, keeps Docker as the template and CI-parity default, and separates
  Cloud SQL operator provisioning from per-workspace startup and shared
  lifecycle controls. Generated-project documentation regions now follow the
  Cloud helper and development Terraform files that survive pruning, and the
  generated-project workflow covers pruned, helper-only, and fully retained
  shapes for every environment manager without contacting Google Cloud.
- Project setup now offers Quick and Advanced paths. Quick asks for six setup
  decisions, plus the credential value required by that mode, and defaults the
  remaining fields. Advanced asks every applicable question. Supported
  terminals use labeled arrow-key menus, while non-TTY sessions, `NO_COLOR`,
  `TERM=dumb`, and `--no-tty` use the same validated plain numbered fallback.
  The first supported environment manager found on `PATH` is preselected only
  in an interactive terminal, and an existing environment key can be reused
  without displaying its value. Reproducible defaults and answers files do not
  inspect the machine.
- `sci-rag new` and `sci-rag init` now use a shared completion report, so both
  routes end with the same files, commands, and domain-drafting guidance.
- Contextual compression is on again in the shipped demo domain, at
  `relevance_floor: 0.0`, and the model default floor moves from `0.3` to
  `0.0` to match. A floor sweep found the floor, not the summarizer, is what
  breaks the paired judged-answer gate: at 0.15 and above, groundedness and
  citation accuracy fall off their ceiling because the answer loses evidence
  it needed. At 0.0, where every source is summarized and none dropped, three
  independent paired runs held every judged dimension while median prompt
  tokens fell by a quarter. Summarizing a source is safe here; discarding one
  is not. Closes #90.

### Added

- `sci-rag new`, the main project-generation command under the existing CLI.
  The standalone `sci-rag-new` executable remains a compatibility entry point.
  Both reach the same generator and release-pinned template fetch.
- A bounded new-project credential preflight before template download, with
  retry, an AI Studio switch, and a continue-without-a-model path that keeps
  the selected credential mode and the worked example ontology. Entered keys
  stay out of output and model representations; generated `.env` files use
  mode `0600`. `--no-preflight` skips the preliminary request explicitly.
- An opt-in Cloud SQL development backend with one development database and
  one disposable test database per workspace, a workspace-owned Auth Proxy,
  explicit pause/resume cost controls, a separate dev-only Terraform module,
  and scaffold support across all four environment managers. Docker remains
  the default. The existing local helper now also documents system PostgreSQL
  and Postgres.app as a zero-cost, low-latency path.
- HTML ingestion. `.html` and `.htm` files parse through the standard library
  (no new dependency) into the same block model the Markdown route produces,
  so folder discovery, manifests, the chunker, and the manifest linter pick
  them up unaided. Page chrome (`nav`, `header`, `footer`, `aside`, scripts,
  styles) is dropped, because a corpus of pages that share a sidebar would
  otherwise make the sidebar its most repeated text. Headings become section
  paths, `<table>` becomes one intact pipe-table block so it stays an
  `is_table` chunk, and the first `<h1>` becomes the title rather than a
  duplicate heading, with `<title>` as the fallback once the site name is
  stripped off it.
- `sci-rag profile`: where retrieval time goes. Replays the seed questions
  against interactive, deep, and auto, and aggregates the per-stage durations
  every request already records into p50/p95 per stage, with a verdict naming
  the slowest stage and what `auto` routed to. `--json` for tracking over time.
  Two caveats are reported rather than left to the reader: stages run
  concurrently so the column does not sum to the request, and the
  query-embedding cache is disabled while profiling so replays measure
  retrieval rather than the cache. A stage the profile switched off is counted
  but never reported as a degradation.
- `sci_rag.evals.stats.percentile` is public, since the profiler reports latency
  percentiles from the same implementation.
- `sci-rag corpus license-report`: the corpus's rights posture, counted. License
  classes already gate retrieval, but nothing summarized them. Counts by class
  by document and by chunk (rights are declared per document, retrieval returns
  chunks, and the two percentages differ), every class in the taxonomy listed
  even at zero, and every `unknown` document named with the source bucket it
  came from. `--json` for machine-readable output; `--strict` exits 1 when
  anything is undeclared, so it can be a CI gate. Without `--strict` it always
  exits 0: a report that breaks the build is a report nobody runs.
- `sci_rag.licensing.UNKNOWN_CLASS`, naming the value the fail-closed rule is
  keyed on.
- `sci-rag draft seed-from-answers QUESTIONS.txt`: turn questions you already
  have into draft seed rows. `draft questions` invents the questions; this
  takes yours, one per line, answers each one, and proposes ground truth from
  the evidence that answer cited. Nothing is taken on the model's word: an
  evidence phrase is kept only when it appears verbatim in both the answer and
  a chunk that answer cited, and every finished row is checked against the same
  relevance predicate the evaluation uses, so a row that would score zero
  against its own evidence is dropped with a reason. Rows carry the existing
  `drafted` tag, so they travel through the honesty plumbing every other
  drafter's output does.
- `sci-rag corpus export OUTDIR`: write documents, chunks, entities, and
  relationships to one file per table, as JSONL (no extra dependency) or
  Parquet (`uv sync --extra export`). Chunk embeddings are omitted unless
  `--include-embeddings`. `--license` takes the same fail-closed allowlist
  retrieval takes, because an export is a redistribution and the copy that
  leaves the database is the one nobody re-checks. The graph gets a stricter
  rule than the rows, since it aggregates: an entity survives a scope only if
  every document it was extracted from survived, and a relationship only if
  its own document and both endpoints did. Communities are never exported,
  for the same reason the community retrieval layer disables itself under any
  scope. Replaces the DuckDB one-liner that `docs/operations.md` used to
  sketch, which had no notion of rights at all.
- `sci-rag manifest lint PATH`: check a corpus manifest before ingesting it.
  Reports every problem at once with line numbers, rather than one per failed
  document partway through a run: missing files, duplicate paths, unparseable
  file types, entries with no title, malformed JSON, bad field types, and
  misspelled keys the loader would silently ignore (a warning, not a failure).
  It is strict about `license_class` because ingestion cannot be: an
  unrecognized value normalizes to `unknown` and is then scoped as unsafe, so
  a mistyped license quietly removes a document from results. Exit 0 when
  clean, 1 when not.
- `sci-rag draft questions`: an assisted first pass at
  `domain/eval_seed_questions.jsonl`, grounded in the documents you already
  have. It prefers the ingested corpus and falls back to reading `data/raw/`
  through the same parsers, so it works before `make setup`. Every quoted
  evidence phrase is verified in Python against a passage belonging to a
  document the question names; rows that fail are dropped and reported by id
  and reason, with one repair round. A run proposes
  `eval_seed_questions.jsonl.proposed`; `--apply` appends to the seed file
  and never displaces a question a human wrote.
- Two lanes on every drafter. `--print-prompt` writes the fully rendered,
  corpus-grounded prompt to stdout for local use or an approved assistant,
  and `--from-file` reads the reply back through identical validation, so the
  drafters work with no API key and no provider account. Printed prompts can
  contain sampled corpus passages, so rights and privacy rules still apply.
- `domain/prompts/seed_questions.md`: the prompt behind that draft, with
  `$DOMAIN_NAME`, `$ENTITY_TYPES`, `$QUERY_CLASSES`, `$PASSAGES`, `$COUNT`,
  and `$REJECTED` slots.
- The `drafted` tag on seed questions, and the honesty plumbing behind it.
  `sci-rag eval retrieval` and `sci-rag eval answers` now warn in the
  generated Markdown when any question behind the numbers is still
  model-drafted, and both report payloads carry
  `"ground_truth": {"drafted": N, "reviewed": M}`. Removing the tag is the
  expert sign-off; nothing in the kit removes it for you.
- `docs/llm-assisted-setup.md`: the three lanes, the copy-paste path, the
  review discipline, and the honesty rules for drafted ground truth.
- `sci-rag draft manifest`: reads title, authors, year, DOI, journal, and a
  source bucket off each document's opening pages, through the same parsers
  ingestion uses, and proposes `data/corpus.jsonl.proposed`. Source buckets are
  chosen across the whole batch rather than one per file. **`license_class` is
  never guessed**: every drafted row is written `unknown`, the command reports
  how many documents need a rights decision, and a license sentence is kept in
  `license_source` as evidence only, and only when it appears verbatim in the
  document.
- `sci-rag draft ontology`: `--from-corpus` redrafts the ontology from real
  passages, `--refine` asks only for additions and removals with a reason for
  each, and `--cold` is the wizard's description-only draft on its own. The
  tuned `retrieval:` and `compression:` blocks are carried over untouched, and
  a refinement that would leave no entity type is rejected. Writes
  `domain/domain.yaml.proposed` with a summary diff; `--apply` writes in place.
- `domain/prompts/manifest_metadata.md` and `domain/prompts/ontology_from_corpus.md`.
- `sci-rag draft prompts`: rewords `entity_extraction.md` or `answer.md` for your
  field while keeping the job identical. The rewrite is re-rendered against dummy
  values and rejected if a required `$SLOT` went missing, if one was invented, or
  if the template will not render. `judge_grounding.md`, `judge_correctness.md`,
  `snippet_compression.md`, and `ontology_draft.md` are refused by name, each with
  a reason. New prompt `domain/prompts/prompt_localization.md`.
- Domain-coherence rows in `sci-rag doctor`: ontology size, unique names and
  SCREAMING_SNAKE relations; seed questions that cite nothing and seed sets with no
  `unanswerable` probe; how many questions are still tagged `drafted`; whether every
  reference title resolves to an ingested document; and manifest paths that no longer
  exist plus a count of rows with unknown rights.
- One new `sci-rag init` question, `draft_domain_files`, asked only when the project
  has credentials. It decides whether the next-steps block leads with the drafters or
  with the hand-written route.

### Changed

- `docs/bring-your-own-domain.md` steps 2, 3, 4 and 6 are now *Generate it* /
  *Write it yourself* tab pairs. The generated route goes first; the full schema for
  every file stays underneath, unchanged.
- The next-steps blocks in `scripts/init_domain.py` and `sci-rag init` name
  `sci-rag draft ...` instead of telling you to go hand-write four files.
- `AGENTS.md` tells a coding agent pointed at a generated project to run
  `sci-rag draft ... --print-prompt` rather than authoring domain YAML from scratch.
- The rendered-geometry guard ignores zero-height wrappers. Two inactive tab panels
  in a row sit at the same point, which it read as a zero-pixel gap between blocks a
  reader can never see at the same time.

### Fixed

These close findings from the 2026-08-29 end-to-end documentation route audit.

- `SCI_RAG_DB_BACKEND` dispatches to the backend it names in generated pixi and
  conda projects. Bundling a conda-forge PostgreSQL server used to replace the
  Docker recipes outright, so both `docker` and `local` started the same
  loopback cluster with trust authentication while the Makefile still declared
  `SCI_RAG_DB_BACKEND ?= docker`. Bundling a server now changes only the
  declared default, which those projects set to `local`. An explicit `docker`
  reaches the Compose service, `local` reaches `scripts/local_postgres.py`, and
  a retained Cloud helper still answers `cloud` alone. Tests read the effective
  command out of `make -n` for every retained backend across all four
  environment managers. Closes #180.
- Generating with `--template-path` no longer copies a checkout's ignored state
  into the new project. The copy boundary is what the repository tracks, which
  is the same content the download route already produces, so credentials under
  `.cloudsql/`, agent files under `.context/`, a filled in `.env`, Terraform
  state, and the corpus under `data/raw/` cannot cross. A directory git knows
  nothing about falls back to a fail closed rule. See ADR 0010. Closes #153.
- `.dockerignore` and `.gcloudignore` bound what `docker build .` and
  `gcloud builds submit .` hand to a builder. Both exclude everything and
  re-admit only the documented build inputs, so the same local state stays
  local. Measured on the previous main, 433 files reached the Docker context
  and 429 were uploaded to Cloud Build; both are now 145. Closes #179.
- Bytecode no longer reaches either build context. `__pycache__` lives inside
  the admitted directories, so an allowlist alone could not exclude it, and a
  build from a working checkout carried the developer's `.pyc` files into the
  image. A working checkout and a clean export now produce the same context.
  Closes #196.
- Two API keys that share their first six characters no longer share a rate
  limit bucket. Accounting uses an opaque identity derived from the whole
  token under a per process salt, while the human readable label stays
  truncated. Error envelopes, status codes, and `Retry-After` are unchanged.
  Closes #169.
- The public `dev-database` Terraform module no longer defaults `project_id`
  and `instance_name` to maintained infrastructure. Both are required inputs,
  so Terraform stops at input validation before it can plan a change against
  an instance the reader never named. `docs/run-postgres.md` now shows the
  saved plan and the review step before the apply. Closes #171.
- The clone and GitHub template routes create `.env` with owner-only mode
  `0600`. `cp` inherits the public example's mode, so the file was readable by
  every account on the machine before the reader pasted a key into it. Closes
  #183.
- The local backup runbook defines its connection string before using it.
  `pg_dump "$SCI_RAG_DATABASE_URL_SYNC"` read a name nothing in the repository
  sets, so it passed an empty argument, or aborted under `set -u`. The page
  now derives the libpq URL from `.env` without putting a password in shell
  history. Closes #158.
- Database dumps are written to an ignored `backups/` directory instead of the
  repository root, and `.dump` is ignored everywhere. A dump holds every source
  and chunk, so for a private corpus it was one `git add .` from publication.
  The restore drill reads from the same directory. Closes #160.
- The backup runbook calls its output a custom-format archive, which is what
  `--format=custom` produces and what the `pg_restore` drill below it reads. It
  had been labelled plain-format, so a reader who believed the label would have
  reached for `psql` and found the file unreadable. Closes #161.
- `sci-rag embed reindex` refuses a dimension change it can actually see.
  The guard compared the embedder's width against `db.models.EMBEDDING_DIM`,
  and both came from `SCI_RAG_EMBEDDING_DIM`, so changing that setting moved
  both sides at once and the command reported a normal plan against a column
  that could not hold the vectors it was about to make. It now reads the width
  off the live pgvector columns, and `--apply` refuses before any embedding
  call or write. Closes #175.
- `docs/extend.md` and `docs/faq.md` name `sci-rag embed reindex` instead of
  `sci-rag embed plan`, which never existed, and both say that planning is the
  default and `--apply` is the separate mutating step. A new guard walks the
  real command tree and fails when a documented command does not resolve.
  Closes #159.
- `make benchmark` binds the two judged-answer reports to their roles from
  each report's own `config.compression` rather than from directory
  modification time. Calibration writes into the uncompressed run, so the old
  `ls -td` selectors handed the compressed report in as the ordinary one and
  the published page reversed the compression columns, showed 1318 to 1318 as
  0 percent lower, still claimed the gate held, and dropped calibration. The
  renderer now refuses a reversed, duplicated, or unlabelled pair, and the
  gate cannot claim a hold when prompt tokens do not fall. Closes #178.
- A generated uv project passes `uv lock --check` without user edits. The
  applier renamed the package, raised the Python floor, and dropped unselected
  extras, then kept the template's lockfile, so an untouched project failed its
  own consistency check with exit 2. The lock is now relocked offline against
  the generated metadata, which is purely subtractive: on a measured project it
  removed 91 packages, retained 112, and changed the pinned version of none of
  them. If uv cannot be run during generation the lock is removed and the
  report says so, as the other three managers already do. Closes #170.
- A generated project's `.python-version` matches the Python the reader
  selected. It stayed at the template's `3.12` while the package metadata, the
  CI matrix, and both Docker stages moved to `3.11`, so pyenv and `uv python`
  produced a different interpreter from everything else. mypy's
  `python_version` follows the selection now too, and a coherence test reads
  every generated pin for every manager and every supported version and
  requires them to agree. Closes #163.
- The no-credential drafting example repeats `--count 10` on both halves of the
  `--print-prompt` and `--from-file` pair. The page says to keep the selectors
  steady across the pair and then omitted one, which worked only because ten is
  also the default. A guard now compares the selectors in every paired example.
  Closes #173.
- Choosing `Apache-2.0` generates the full canonical Apache License 2.0 text
  rather than a nineteen-line notice pointing at it. The other two offered
  licenses always shipped complete, so one menu entry meant something different
  from the other two. The text is the SPDX copy, cross-checked against the
  independent one shipped by `packaging`, and a test pins it by hash. Apache's
  own appendix says the copyright belongs in a `NOTICE` file rather than in the
  license, so generation prints that guidance instead of editing the text.
  Closes #165.
- The no-placeholder claim in `docs/faq.md` and ADR 0007 describes what is
  actually enforced. It said a test proves a generated project contains no bare
  double brace, while containing that token four times itself; a real generated
  project has seven, including valid BibTeX and ADR 0004's deliberate
  illustration of the syntax this project refuses. The guard now runs against a
  real generated tree for every environment manager, where the old one ran
  against a five-file fixture with nothing capable of violating it, and accepts
  three contexts by content rather than by filename. Closes #166.
- A generated pixi project with a standalone `pixi.toml` builds its Dockerfile.
  The builder copied only `pyproject.toml` and `README.md` before running
  `pixi install`, so the manifest defining the workspace stayed on the host. The
  Dockerfile now copies whichever manifest shape the project uses, before the
  source so the dependency layer still caches, and container CI builds both
  shapes. Closes #162.
- A generated project's `.dockerignore` and `.gcloudignore` admit the manifest
  its own Dockerfile copies. The fail-closed allowlist added with the build
  context fix was uv's, so pixi projects excluded `pixi.toml`, conda projects
  excluded `environment.yml`, and venv + pip projects excluded
  `requirements.txt`: the documented container route could not build for three
  of the four managers. The allowlist is now derived from the rendered
  Dockerfile, so a template that copies something new admits it in the same
  change.
- A generated project with a standalone `pixi.toml` resolves. The manifest
  declared `default = { features = ["dev"] }` and defined no such feature,
  because pixi only maps `[dependency-groups] dev` to a feature of that name
  when `pyproject.toml` is its manifest. `pixi install` refused the file
  outright. The standalone shape now spells out the feature tables, with a test
  holding them in step with `[dependency-groups]`, and container CI builds both
  manifest shapes. Closes #215, and with it #162.

## [0.3.0] - 2026-08-28

The "Campaigns" release: the kit gets the parts that make it better for
science than a general-purpose RAG framework, plus an interactive project
factory so starting one is two commands instead of a seven-step tutorial.

Two features ship switched off, on purpose. Contextual compression cut
median prompt tokens by 70% but every judged dimension moved down, so its
paired gate did not hold (#90). Entity resolution finds nothing to merge on
the demo corpus, so its ablation cannot be measured here. Both are in
`docs/benchmarks.md` with the numbers.


### Added

- `sci-rag init`: an interactive setup wizard that specializes a checkout
  for your own domain. Asks about the project, credentials and models,
  ontology, corpus source, PDF parser, reranker, license, and stack, then
  writes `domain/domain.yaml`, `.env`, `pyproject.toml`, the `Makefile`,
  `README.md`, and the corpus scaffold. `--defaults` and `--answers-file`
  make generation reproducible; `--dry-run` previews it. The ontology can
  be drafted by the configured model and is validated against
  `DomainConfig` before anything is written, so a malformed draft is
  rejected rather than saved as unusable YAML.
- `domain/prompts/ontology_draft.md`: the prompt behind that draft.
- Multi-provider generation. `SCI_RAG_LLM_MODEL` and friends now accept a
  `provider:model` spec selecting `google`, `anthropic` (Claude on Vertex AI
  or the direct API), or `openai-compatible` (Vertex Model Garden partner
  models such as Grok, Llama, Mistral, and DeepSeek; also OpenAI and
  self-hosted vLLM/Ollama). New `anthropic` and `openai` extras; the SDKs are
  imported lazily so a Google-only install carries neither. See ADR 0006 for
  why the adapters are hand-written and why embeddings stay Google-only.
- `SCI_RAG_JUDGE_MODEL`, so the evaluation judge can run on a different
  provider than the generator. Answer eval reports now record which model
  answered and which graded, making cross-provider judging auditable.
- `sci-rag doctor` reports the resolved spec per role and checks credentials
  for each generation provider in use.

- Environment manager choice in the wizard: pixi, conda, and venv+pip
  alongside uv. One `RunnerProfile` renders all five uv-wired surfaces
  (task commands, CI, Dockerfile, dev container, docs), writes whatever
  manifest that manager needs (`[tool.pixi]` tables or `pixi.toml`,
  `environment.yml`, `requirements.txt` plus `requirements-dev.txt`), and
  is the only place a manager-specific string lives.
- `generated-projects.yml`: a CI matrix that generates a project per
  manager and runs that project's own lint, typecheck, and offline demo.
  uv runs on every pull request; all four run nightly, on release tags,
  and on any pull request that changes what a generated project looks
  like.

- `sci-rag-new`: the project factory as its own entry point. Runs from a
  parent directory with nothing cloned, fetches the template at the tag
  matching its own installed version, then applies the wizard's answers.
  `--template-path` generates from a local checkout with no network, and
  `--ref` overrides the tag. The LLM ontology draft is offered here and in
  `sci-rag init`, with accept, reject, and redraft.
- `.github/workflows/release.yml`: tag-driven publishing to TestPyPI and
  then PyPI over Trusted Publishing, gated on the `ci` workflow having
  passed for the tagged commit and on the tag matching the packaged
  version. The one-time maintainer setup is in `docs/VERSIONING.md`.

- The documentation homepage leads with `pipx install sci-rag-kit` and
  `sci-rag-new`, and shows the session in a player. The transcript below
  it is generated by driving the real wizard (`make cast`), so it cannot
  drift from the questions; `make docs` fails when it is stale. The
  asciinema player is vendored under `docs/assets/vendor/`, not loaded
  from a CDN, which keeps the docs build hermetic and the offline link
  check honest.
- `docs/adr/0007-interactive-project-generator.md`: why the generator is
  a post-fetch applier rather than a template renderer, and how that
  implements the escape hatch ADR 0004 left open instead of overturning
  it.

- A Docker-free database for pixi and conda projects. Those two managers
  read conda-forge, which ships the PostgreSQL server and pgvector as
  ordinary packages, so their generated manifests declare
  `postgresql >=16,<19` and `pgvector`, and their `make setup` starts that
  server instead of a container. `scripts/local_postgres.py` drives
  `initdb` and `pg_ctl` against a project-local `.pgdata/`, producing a
  database the unmodified `.env.example` already points at. uv and
  venv+pip keep Docker: PyPI ships no server, and a manager that cannot
  take the path does not advertise it.
- `.github/workflows/docker-free-postgres.yml`: the integration and server
  suites against a conda-forge server on linux-64 and osx-arm64, failing
  if the suite skips rather than runs. With `ci.yml` on PostgreSQL 16 and
  this on 18, both ends of the supported range are tested.
- `docs/adr/0008-supported-postgresql-versions.md`: why the project
  supports a range instead of moving everyone to one major.

### Changed

- Supported PostgreSQL versions are now stated and tested: **16 through
  18**. Nothing moves. Compose and the CI service stay on the
  `pgvector/pgvector:pg16` image, and no existing database needs a
  migration. The schema uses no pgvector feature newer than 0.5 and no
  version-specific SQL, so the 16 in this repository was three container
  image tags rather than a requirement.

- Generated projects no longer carry the kit's own onboarding. The pipx
  instructions, the recorded session, the vendored player, and the
  renderer that keeps it current are all removed, along with their
  entries in `mkdocs.yml` and the `Makefile`, so a generated project's
  documentation still builds.
- `docs/bring-your-own-domain.md` opens with what the wizard asked and
  where each answer landed, then keeps the by-hand walkthrough for
  people who want to know what it chose for them.
- `docs/tour.md`, `docs/deploy-gcp.md`, `README.md`, and
  `docs/benchmarks.md` say which pieces the wizard can decline, instead
  of describing directories a generated project may not have.
- `.env` now reaches the process environment. pydantic-settings reads it
  into `Settings` but never exported it, so Typer's `envvar=` lookups and
  the `OPENALEX_API_KEY` read in `sci-rag campaign discover` could not see
  values placed there. A real environment variable still wins over the
  file.
- `scripts/init_domain.py` is now a thin shim over `sci_rag.scaffold`, so
  it and the wizard cannot disagree about what a seed-question reset looks
  like. Its command line, dry-run behavior, and output are unchanged.

- A bare model id still resolves to `SCI_RAG_LLM_PROVIDER` (default `google`),
  so existing configurations keep working unchanged.
- `GoogleLLM` moved from `sci_rag.llm.client` to `sci_rag.llm.google`, matching
  the layout of `sci_rag.embed`. `sci_rag.llm` re-exports it as before.
- Retry policy is shared across providers in `retry_async()`, and status-code
  detection no longer matches a code embedded in a longer number.

### Fixed

- `sci-rag doctor` no longer reports FAIL for a project that runs offline on
  purpose. A project with the local-hash embedder, no credentials anywhere,
  and the shipped generation defaults now sees warnings that name the
  unavailable features, and exits 0. Reaching for a model still fails: a
  Google embedder without credentials, or a deliberately named generation
  model such as `anthropic:claude-opus-5` with no key behind it, reports FAIL
  as before. The generated-project matrix gates on `doctor` again.
- `sci-rag doctor` prints its table when the configured embedder cannot be
  built. It looked up the embedder to report embedding-version drift, so a
  Google embedder without credentials aborted the whole command with a
  traceback, hiding the credentials row that explained the cause.
- `sci-rag doctor --probe` no longer warns on a healthy setup. Its generation
  probe capped output at 10 tokens, which reasoning models spend on thought
  before writing anything, so a working provider looked like it returned
  nothing.
- The Vertex Model Garden endpoint is now derived correctly for the `global`
  location, which is served by an unprefixed host. Grok is offered *only*
  globally, so the previous URL made it unreachable.
- The OpenAI-compatible adapter closes its response stream, returning the
  connection to the pool when a consumer stops early.
- `sci-rag init` no longer rewrites the commented examples in `.env.example`
  with the answers it collected. Only the first assignment of a key is the
  setting; substituting the later illustrative ones turned worked examples
  into confidently wrong advice and emitted the same key several times.


## [0.3.0a1] - 2026-08-28

A packaging pre-release. No behavior of its own: it exists to establish
Trusted Publishing to TestPyPI and PyPI and to reserve the `sci-rag-kit`
name on both, using a version number that can be burned without cost if
the publishing path turns out to be wrong.

The changes it carries are the ones listed under Unreleased above. The
real 0.3.0, with the Wave 2 benchmark refresh, is #49.

## [0.2.0] - 2026-08-27

The "Credibility" release: the gaps between what the methodology
document promised and what the code did are closed, and the launch
package (roadmap, governance, comparison, benchmarks) is in place.

### Added

- Post-fusion reranker stage: `Reranker` protocol with an LLM adapter
  (default, zero new dependencies) and a local cross-encoder adapter
  behind the new `rerank` extra; per-request `include_rerank`
  overrides on the retriever and `/v1/query`; honest `rerank` stage
  traces with fused-order fallback on any failure. Off by default
  pending ablation evidence.
- Eval statistics: bootstrap 95% confidence intervals on every
  reported mean (question-level resampling, stdlib only,
  deterministic), small-sample warnings below 10 questions, paired
  bootstrap comparisons, and nDCG@10 alongside hit@k/MRR.
- `sci-rag eval diff`: per-question rank moves (improved, regressed,
  appeared, disappeared) and paired metric deltas with significance
  between any two eval runs; answers-mode dimension diffs.
- `sci-rag eval calibrate`: Cohen's kappa per judge dimension against
  human labels, agreement matrices, calibration sections appended to
  answers reports; ships a non-expert seed label set for the demo
  corpus (`domain/eval_calibration_labels.jsonl`).
- `sci-rag embed reindex`: find and re-embed rows stamped by retired
  embedder versions, batch-committed and idempotent; refuses
  cross-dimension reindexes; community summaries now carry embedding
  version stamps (migration 0002).
- `sci-rag corpus delete` + `sci-rag graph gc`: transactional document
  deletion that scrubs graph evidence arrays, drops evidenced
  relationships and affected communities, and a garbage-collection
  sweep for evidence-less entities and dangling pointers; regression
  test proves deleted content unreachable through every retrieval
  layer.
- `sci-rag corpus snapshot`: named, immutable corpus fingerprints
  (counts, per-document content hashes, embedding versions, git
  commit, corpus digest); eval runs record the snapshot name via
  `--snapshot`.
- Adaptive routing: `--profile auto` resolves per query through
  transparent heuristics (multi-hop, overview, lookup cues) with
  reasons, an optional ambiguity-only LLM fallback, a router trace,
  and `--explain-routing`; default profile unchanged pending the
  published ablation.
- `docs/benchmarks.md`: measured demo-corpus results (all ablation
  configs including rerank and routing, judged answers, judge
  calibration) with confidence intervals, corpus snapshot, commit and
  model ids, reproducible via `make benchmark`.
- `docs/operations.md`: backup/restore runbook (pg_dump, Cloud SQL,
  restore drill, Parquet export note).
- Launch package: `docs/ROADMAP.md` (waves 2-3, UW SSEC collaboration
  points, BioCirV flagship, launch-gated decisions),
  `docs/VERSIONING.md` (0.x rules, 1.0 criteria),
  `docs/GOVERNANCE.md`, `docs/choosing-sci-rag-kit.md` (honest
  comparison), `ADOPTERS.md`, and a runnable
  `examples/bring_your_own_domain.ipynb` (verified offline).
- Doctor: embedding-version staleness and graph-hygiene checks.

### Changed

- Retrieval eval reports state n and a 95% CI everywhere a mean
  appears; retrieval tables gained an nDCG@10 column.
- `/v1/query` accepts `profile: "auto"` and `include_rerank`.

## [0.1.0a0] - 2026-08-26

First working release of the template.

### Added

- Ingestion: Docling/pypdf/Markdown parsing, structure-aware chunking
  (section breadcrumbs, intact tables, 800/150 token defaults),
  content-hash deduplication, per-document license classes, JSONL corpus
  manifests.
- Storage: single-Postgres schema (Alembic) with pgvector HNSW and
  full-text GIN indexes; embedding version stamping.
- Embeddings: Google `gemini-embedding-001` at 1536 dimensions
  (Matryoshka, re-normalized) via AI Studio key or Vertex AI; a
  deterministic offline hash embedder for tests and dry runs.
- Knowledge graph: ontology-constrained LLM extraction with evidence
  provenance, incremental stamping, deterministic label-propagation
  communities with LLM summaries.
- Retrieval: five layers (vector, keyword, graph traversal, community
  summaries, HyDE) with weighted RRF fusion, interactive/deep profiles,
  per-stage timeouts and traces, fail-closed license/source/exclusion
  scoping inside every layer.
- Answering: numbered inline citations, refusal when nothing is in
  scope, streaming events.
- Evaluation: seed questions, hit@k/MRR with seven ablation configs, a
  two-pass blind judge (grounding never sees the reference answer),
  fingerprint-stamped JSON and Markdown reports, a CI smoke eval.
- Serving: FastAPI `/v1` (SSE answers, RFC 9457 errors, request ids,
  scoped API keys with rate limits, BYO LLM key) and an MCP server with
  seven tools and two resources, over streamable HTTP and stdio.
- Operations: `sci-rag doctor`, docker-compose Postgres, Dockerfile,
  validated Terraform for Cloud SQL + Cloud Run, GitHub Actions CI.
- Template ergonomics: `domain/` specialization surface,
  `scripts/init_domain.py`, offline synthetic demo corpus with seed
  questions and committed real-model eval reports, full documentation
  suite with ADRs.
