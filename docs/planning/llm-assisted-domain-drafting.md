<!-- Plan doc for epic #98. Excluded from the documentation site (mkdocs
     exclude_docs: planning/); it is a working record, not a user guide. -->

> Authored 2026-08-27.

# LLM-assisted generation for every user-authored domain file

## Context

Going from the sci-rag-kit template to a working domain RAG requires a scientist to
hand-author four files. Today only one of them has any LLM assistance:

| Artifact | Who writes it now | LLM path today |
|---|---|---|
| `domain/domain.yaml` (ontology) | user, 50–200 lines | **partial**: `sci-rag init` / `sci-rag-new` wizard offers `draft_with_llm`, but only once, at project creation, from a one-sentence description, interactive-only, before any documents exist |
| `data/corpus.jsonl` (corpus manifest) | user, one line per document | **only for OpenAlex/DOI corpora** via `sci-rag campaign build`. Local PDFs in `data/raw/` get nothing but `discover_folder()`, which defaults every field |
| `domain/eval_seed_questions.jsonl` | user, 10–20 questions × 6 fields | **none**: the single biggest manual lift |
| `domain/prompts/*.md` | user, light edits | **none** |
| `domain/eval_calibration_labels.jsonl` | user (human labels) | none, and correctly so: see Non-goals |

The gap is visible in the repo's own instructions. `scripts/init_domain.py:91-103` and
`src/sci_rag/cli/init.py:124-133` both end by telling the user to go hand-write these
files, and `docs/bring-your-own-domain.md` steps 2, 3, 4 and 6 are each "here is the
schema, now type it out."

**Outcome:** every one of those artifacts gets three lanes: generate with the
configured LLM, generate with *any* LLM via copy-paste (no API key needed), or write it
by hand exactly as today: with the same validation on all three. Users supply the
minimum viable input; the kit derives the rest from what already exists on disk and in
the database.

## Design

### The three lanes

Every drafter exposes the same shape, which is what gives users both paths:

- **Lane A: `sci-rag draft <thing>`** (default): gather context automatically, call the
  configured LLM, validate through the same pydantic model the loader uses, write a
  `.proposed` file for review.
- **Lane B: `--print-prompt` / `--from-file`**, on **every** drafter: `--print-prompt`
  emits the fully rendered, corpus-grounded prompt on stdout. The user pastes it into
  ChatGPT/Claude/anything and feeds the reply back with `--from-file reply.json`.
  Identical validation and identical output. This is the path for a scientist with no
  credentials, and it costs almost nothing because prompt rendering is already a separate
  function (`scaffold/ontology.py:render_prompt`).
- **Lane C: by hand**: unchanged. The docs keep the full schema for every file.

Lane B is what makes the manual and LLM paths one system rather than two: the same
prompt, the same validator, the same file written. Enforce that with a test asserting
`--from-file` on a captured Lane A response produces byte-identical output.

### Minimum viable input

No drafter interrogates the user for facts the repo already holds:

| Command | Asks the user | Derives itself |
|---|---|---|
| `draft ontology` | nothing | `name` + `description` from `domain.yaml`; samples real chunks from the ingested corpus, or files from `data/raw/` |
| `draft manifest` | nothing (folder defaults to `data/raw`) | filename + first ~2 pages of each document via the existing parsers |
| `draft questions` | nothing | the ontology, plus real chunks and document titles from the corpus |
| `draft prompts` | nothing | the current prompt file + the ontology |

Where an answer genuinely cannot be derived, reuse the existing `Question` dataclass and
wizard I/O (`scaffold/questions.py`, `scaffold/wizard.py`) rather than inventing a second
prompting style.

### Invariants this must respect

From `AGENTS.md` "Architecture invariants": these shape the design, not decorate it:

- **Domain specialization stays out of Python.** Every new drafting prompt is a
  `domain/prompts/*.md` file with `$UPPER_CASE` slots, like `ontology_draft.md`. No
  inline prompt strings.
- **Model output is untrusted.** Everything parses through `DomainConfig`,
  `CorpusEntry`, or `SeedQuestion` before it is written.
- **Fail closed on rights.** `license_class` is never inferred by a model.
- **Scientific honesty.** Model-drafted ground truth is not expert ground truth and must
  be labelled as such.
- **Keep one `unanswerable` honesty probe** in any generated seed set.

## Work

### 1. New module `src/sci_rag/draft/`

Sibling to `src/sci_rag/scaffold/`, one module per artifact, each with a
`render_prompt()` / `draft_*()` / `verify_*()` trio mirroring `scaffold/ontology.py`.

- `draft/__init__.py`
- `draft/ontology.py`: corpus-grounded ontology drafting and refinement
- `draft/manifest.py`: per-document metadata extraction
- `draft/questions.py`: seed-question drafting + grounding verification
- `draft/prompts.py`: prompt-template rewriting with a hard allowlist
- `draft/sampling.py`: shared "give me N representative chunks / raw files" helper,
  used by ontology and questions

Reuse, do not reimplement: `sci_rag.llm.get_llm` / `parse_json_loosely`,
`sci_rag.domain.load_domain` + `DomainConfig`, `sci_rag.ingest.manifest.discover_folder` +
`CorpusEntry`, `sci_rag.ingest.parsers`, `sci_rag.evals.seeds.SeedQuestion`,
`sci_rag.scaffold.ontology.draft_ontology`.

### 2. New prompts in `domain/prompts/`

- `ontology_from_corpus.md`: slots `$DOMAIN_NAME`, `$DESCRIPTION`, `$EXISTING_ONTOLOGY`,
  `$PASSAGES`. Asks which types actually appear in the field's own vocabulary, and for a
  refinement it returns additions/removals with reasons rather than a blind rewrite.
- `manifest_metadata.md`: slots `$FILENAME`, `$HEAD_TEXT`, `$SOURCE_BUCKETS`. Returns
  title/authors/year/doi/journal/source, plus any license statement found **verbatim** in
  the text.
- `seed_questions.md`: slots `$DOMAIN_NAME`, `$ENTITY_TYPES`, `$QUERY_CLASSES`,
  `$PASSAGES`, `$COUNT`. Requires quoting evidence phrases verbatim from the supplied
  passages, at least one multi-hop question, and exactly one `unanswerable` probe.
- `prompt_localization.md`: slots `$PROMPT_NAME`, `$CURRENT_TEXT`, `$DOMAIN_NAME`,
  `$ENTITY_TYPES`, `$REQUIRED_SLOTS`.

### 3. New CLI group `sci-rag draft` in `src/sci_rag/cli/main.py`

Registered like the existing `campaign_app` / `corpus_app` groups.

**`draft ontology`**: closes the loop `docs/bring-your-own-domain.md:184-187` describes
("near zero entities means the ontology and the corpus are talking past each other") but
gives no assisted fix for.
- `--from-corpus` (default when a corpus is ingested) / `--refine` (feed the existing
  ontology in and ask for deltas) / `--cold` (description only, today's wizard behaviour).
- Preserves the existing `retrieval:` and `compression:` blocks: those are tuned
  numbers, not domain semantics. Writes `domain/domain.yaml.proposed` + a summary diff;
  `--apply` writes in place.

**`draft manifest`**: the local-files path `campaign build` does not cover.
- Runs `discover_folder()`, extracts each document's head, batches per-document metadata
  calls, and proposes 3–6 shared `source` buckets across the batch (matching the docs'
  own advice) rather than one per document.
- **`license_class` is never guessed.** Every row fails closed to `unknown`. A license
  statement the model found verbatim goes to `license_source` as evidence only; the
  command prints "N documents need a rights decision" and points at
  `docs/evidence-and-rights.md`.
- Composes with the existing `sci-rag corpus enrich` for DOI-bearing documents.

**`draft questions`**: the biggest lift, and the one where grounding makes generation
trustworthy rather than plausible.
- **Prefers the ingested corpus, falls back to reading `data/raw/` directly** through the
  existing parsers when nothing is ingested, so the command works before `make setup`.
  The source of passages is recorded in the run summary either way.
- Samples chunks across documents and query classes via `draft/sampling.py`.
- **Verification happens in Python, not in the model.** Every `evidence_phrase` must
  appear verbatim in a passage belonging to a document named in `reference_titles`; every
  `reference_title` must resolve to a real document. Failing rows are dropped and
  reported, with one optional repair round.
- **Provenance is mandatory**: each drafted row carries a `drafted` tag, and the file
  header states these are model-drafted and awaiting expert review. Removing the tag is
  how a domain expert signs off on a question.

**`draft prompts`**: narrow by construction.
- Touches only `entity_extraction.md` and `answer.md`.
- Hard-coded refusal list for `judge_grounding.md`, `judge_correctness.md`,
  `snippet_compression.md`, `ontology_draft.md`. The judge blindness rules are
  load-bearing (`AGENTS.md:216-218`).
- Re-renders the rewritten template against dummy slot values and rejects it if any
  required `$SLOT` was lost.

### 4. Drafted ground truth is visible in eval reports

`src/sci_rag/evals/report.py` already has the exact pattern: `small_n_warning()` (line 28)
returns warning lines spliced into the generated markdown when a sample is too small to
support conclusions. Add a sibling beside it:

- `drafted_questions_warning(drafted: int, total: int) -> list[str]`: spliced into both
  `retrieval_markdown()` and `answers_markdown()` when any seed question still carries the
  `drafted` tag, saying plainly that N of M questions are model-drafted and unreviewed, so
  the metrics are provisional.
- `retrieval_payload()` and `answers_payload()` gain a `"ground_truth": {"drafted": N,
  "reviewed": M}` block, so the JSON keeps the same receipt the markdown shows.

This is the honesty invariant made operational rather than aspirational: nobody can quote
a number from a report grounded in unreviewed ground truth without seeing that fact next
to it.

### 5. Domain coherence checks in `sci-rag doctor`

`src/sci_rag/cli/doctor.py` already has the `Check` model and verifies the domain profile
loads and prompts exist (`_PROMPT_FILES`, line 24). Add checks that close the loop:

- ontology is non-trivial (≥3 entity types), names unique, relations SCREAMING_SNAKE
- seed questions parse, ids unique, at least one `unanswerable`
- when a corpus is ingested: evidence phrases present, reference titles resolve
- how many seed questions are still tagged `drafted` (unreviewed)
- manifest paths exist; count of `unknown` license rows

### 6. Docs and project structure

- **`docs/bring-your-own-domain.md`**: rewrite steps 2, 3, 4 and 6 as
  *Generate it* / *Write it yourself* tab pairs (`pymdownx.tabbed` is already enabled in
  `mkdocs.yml`). Generate-it goes first as the recommended path; the hand-written schema
  stays complete underneath.
- **New `docs/llm-assisted-setup.md`** under Guides: the three lanes, the copy-paste
  path for users with no API key, the review discipline, and the honesty rules for
  drafted ground truth. Register in `mkdocs.yml` `nav:` under `- Guides:`.
- **`scripts/init_domain.py:91-103`** and **`src/sci_rag/cli/init.py:124-133`**: the two
  next-steps blocks that today say "go hand-write four files" become
  `sci-rag draft ...` invocations, with the manual route named as the alternative.
- **`domain/README.md`**: point at the drafters.
- **`docs/cli.md`**: document the new group.
- **One new wizard question** in `scaffold/questions.py`, gated on non-offline projects:
  offer to run the drafters at the end of `sci-rag init`.
- **`AGENTS.md`**: a short section so a user who points Claude Code or Cursor at their
  generated repo is told to run `sci-rag draft ... --print-prompt` rather than
  hand-writing YAML.

### 7. Tests

Follow existing conventions (`tmp_path` scratch projects, `MockLLM` from
`llm/client.py`, round-trip through the real pydantic models):

- `tests/unit/test_draft_ontology.py`: cold, corpus-grounded, refine; malformed model
  output rejected; `retrieval:` block preserved
- `tests/unit/test_draft_manifest.py`: **`license_class` stays `unknown` even when the
  model asserts a permissive one**; paths validated
- `tests/unit/test_draft_questions.py`: ungrounded evidence phrases dropped; the
  `unanswerable` probe survives; `drafted` provenance tag applied
- `tests/unit/test_draft_prompts.py`: judge prompts refused; required slots preserved
- `tests/unit/test_draft_cli.py`: `--print-prompt` / `--from-file` round-trip produces
  byte-identical output to the direct call
- extend `tests/unit/test_cli_help.py` for registration and
  `tests/integration/test_doctor.py` for the new checks

## Delivery: three stacked PRs

Each is independently shippable and carries its own docs, per the repo's documentation
discipline. Squash auto-merge at green CI, no tracking issue, matching this repo's
existing workflow.

**PR 1: the drafting seam, and seed questions.**
`src/sci_rag/draft/` (`__init__`, `sampling`, and the shared Lane A/B plumbing),
`draft questions` with grounding verification, `domain/prompts/seed_questions.md`, the
`drafted` provenance tag, the eval-report warning and `ground_truth` payload block
(section 4), tests, a `docs/cli.md` entry, and the new `docs/llm-assisted-setup.md` page
that introduces the three lanes. This PR establishes the pattern every later drafter
copies, and delivers the single biggest manual lift on its own.

**PR 2: corpus manifest and ontology.**
`draft manifest` (fail-closed rights) and `draft ontology` (`--from-corpus`, `--refine`,
`--cold`), `domain/prompts/manifest_metadata.md` and `ontology_from_corpus.md`, tests,
`docs/cli.md` additions.

**PR 3: prompt localization, doctor, and the tutorial rewrite.**
`draft prompts` with the judge-prompt refusal list, the `sci-rag doctor` domain-coherence
checks (section 5), the `bring-your-own-domain.md` tab restructure, the two next-steps
blocks in `scripts/init_domain.py` and `src/sci_rag/cli/init.py`, `domain/README.md`, the
new wizard question, and the `AGENTS.md` section.

## Non-goals

- **`domain/eval_calibration_labels.jsonl` stays hand-labelled.** Its entire purpose is
  to be the human ground truth that calibrates the LLM judge; generating it with an LLM
  would be circular and would defeat the measurement. `AGENTS.md:288` requires labels be
  described honestly as expert or non-expert.
- No changes to retrieval, fusion weights, chunking, or the judge prompts.

## Verification

```bash
# offline, no credentials: MockLLM covers the drafters
uv run pytest tests/unit -k draft
uv run pytest tests/unit/test_cli_help.py tests/unit/test_docs_code_snippets.py

# database-free fallback: drafting from data/raw before anything is ingested
uv run sci-rag draft questions --count 5 --dry-run

# end-to-end against the demo corpus
make setup && make demo
uv run sci-rag draft ontology --from-corpus --dry-run
uv run sci-rag draft questions --count 10 --dry-run
uv run sci-rag draft manifest --folder data/demo/fixture --dry-run
uv run sci-rag doctor          # new domain-coherence rows appear

# lane B, no API key
uv run sci-rag draft questions --print-prompt > /tmp/p.txt   # paste into any assistant
uv run sci-rag draft questions --from-file /tmp/reply.json --dry-run

# docs
uv run mkdocs build --strict
uv run pytest tests/docs
```

Then confirm the honesty path end to end: apply the drafted questions, run a real eval,
and check the report says out loud that its ground truth is unreviewed.

```bash
uv run sci-rag draft questions --count 10 --apply
uv run sci-rag eval retrieval --ablation
grep -r "model-drafted" eval_results/   # the warning is in the generated markdown
```

Finally, remove the `drafted` tag from one question by hand and re-run to confirm the
counts move: that is the expert sign-off loop working.
