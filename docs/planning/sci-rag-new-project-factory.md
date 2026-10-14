<!-- Plan doc for epic #59. Excluded from the documentation site (mkdocs
     exclude_docs: planning/); it is a working record, not a user guide. -->

# sci-rag-new: a ccds-style interactive project factory

Authored 2026-08-27. Tracked as epic
[#59](https://github.com/sustainability-software-lab/sci-rag-kit/issues/59),
implemented across
[#60](https://github.com/sustainability-software-lab/sci-rag-kit/issues/60),
[#61](https://github.com/sustainability-software-lab/sci-rag-kit/issues/61),
[#62](https://github.com/sustainability-software-lab/sci-rag-kit/issues/62), and
[#63](https://github.com/sustainability-software-lab/sci-rag-kit/issues/63).

## Context

Cookiecutter Data Science puts a Quick Start front and center on its docs homepage:
`pipx install cookiecutter-data-science`, then run `ccds` from a parent directory and
answer a short Q&A. No directory to create first, no files to hand-edit -- the tool is
the factory.

Sci RAG Kit today has no equivalent. Onboarding is "click **Use this template** on
GitHub → clone → `cp .env.example .env` → `make setup` → read
`docs/bring-your-own-domain.md` (200 lines, 7 manual steps) → hand-edit
`domain/domain.yaml`". The only automation is `scripts/init_domain.py`, which sets a
name and description and blanks the seed questions. Everything that actually makes a
project *yours* -- the ontology, credential mode, corpus source, parser and reranker
choices -- is manual.

The outcome we want: `pipx install sci-rag-kit` → `sci-rag-new` → answer ~18 questions →
a configured, git-initialized, ready-to-run project directory -- including a project wired
for the user's own environment manager (uv, **pixi**, conda, or venv+pip), not just uv --
with the same transcript shown as an animated terminal on the docs homepage.

### This does not overturn ADR 0004

ADR 0004 rejected cookiecutter because *"the template itself is dead code: it cannot be
browsed, cannot run, and cannot be CI-tested as-is."* It then explicitly anticipated
this work: *"A cookiecutter wrapper could be generated mechanically later if a
downstream community wants one; nothing in this decision blocks it."*

The design honors that. There are **no Jinja placeholders and no `{{ }}` directories.**
The template remains the runnable, CI-tested repo. `sci-rag-new` is a **post-fetch
applier**: it downloads the real repo at a pinned tag, then rewrites config files in
place. The wizard's logic lives in `src/sci_rag/scaffold/`, is unit-tested by the
existing CI job, and is reachable two ways:

| Invocation | Where it runs | Use |
|---|---|---|
| `sci-rag-new` | parent directory, from a pipx/uvx install | new project (the ccds UX) |
| `sci-rag init` | inside an already-cloned repo | template users, re-running the wizard |

Both call the same `run_wizard()`. `scripts/init_domain.py` becomes a thin shim that
delegates to it (keep the path working; it is referenced in `docs/bring-your-own-domain.md`).

---

## The Q&A session

The target transcript -- this is both the UX spec and the docs example:

```console
$ sci-rag-new
project_name (My Scientific KB): Membrane Materials KB
repo_name (membrane-materials-kb):
description (A short description of your domain.): Membrane chemistry and performance for water treatment
author_name (Your name, lab, or organization): Berkeley Lab
contact_email (Sent to OpenAlex, Crossref, and Unpaywall): you@lbl.gov
python_version (3.12):
Select environment_manager
1 - uv
2 - pixi
3 - conda
4 - venv+pip
Choose from [1/2/3/4] (1): 2
Select dependency_file
1 - pyproject.toml
2 - pixi.toml
Choose from [1/2] (1):
Select credentials
1 - google_ai_studio
2 - vertex_ai
3 - offline
Choose from [1/2/3] (1): 1
Select embedding_provider
1 - google
2 - local-hash
Choose from [1/2] (1):
llm_model (gemini-2.5-flash):
embedding_model (gemini-embedding-001):
embedding_dim (1536):
Select ontology
1 - draft_with_llm
2 - keep_demo_example
3 - blank
Choose from [1/2/3] (1): 1

  Drafting an ontology for "Membrane chemistry and performance for water treatment"...

  Entity types      Membrane, Material, Contaminant, Process, Property, Application,
                    Organization, Standard
  Relation types    MADE_OF, REMOVES, HAS_PROPERTY, USED_IN, REQUIRES, COMPARED_WITH
  Query classes     performance, fabrication, fouling, application

  Accept this ontology? [y/n/redraft] (y):

Select corpus_source
1 - local_files
2 - openalex_topic
3 - doi_list
4 - demo_only
Choose from [1/2/3/4] (1): 2
openalex_topic: polyamide membrane fouling
max_results (100): 250
Select pdf_parser
1 - pypdf
2 - docling
Choose from [1/2] (1): 2
Select reranker
1 - none
2 - llm
3 - local_cross_encoder
Choose from [1/2/3] (1):
Select include_terraform
1 - Yes
2 - No
Choose from [1/2] (1): 2
Select include_demo_corpus
1 - Yes
2 - No
Choose from [1/2] (1): 2
Select open_source_license
1 - BSD-3-Clause
2 - MIT
3 - Apache-2.0
4 - No license file
Choose from [1/2/3/4] (1):
Select initialize_git
1 - Yes
2 - No
Choose from [1/2] (1):

Fetching sci-rag-kit v0.2.0...
Writing membrane-materials-kb/

  domain/domain.yaml     8 entity types, 6 relation types, 4 query classes
  domain/eval_seed_questions.jsonl   guided blank
  .env                   google_ai_studio, gemini-2.5-flash, gemini-embedding-001
  pyproject.toml         name, description, extras: docling, [tool.pixi] tables
  pixi.lock              (created on first `pixi install`)
  Makefile               commands prefixed with `pixi run`
  .github/workflows/     prefix-dev/setup-pixi@v0
  Dockerfile             pixi base image
  data/campaigns/        openalex topic "polyamide membrane fouling"
  LICENSE                BSD-3-Clause
  README.md              rewritten opening
  removed                infra/terraform/, data/demo/
  git                    initialized, 1 commit

Done. Membrane Materials KB is yours. Next:

  cd membrane-materials-kb
  pixi run setup
  pixi run sci-rag doctor
  pixi run corpus      # sci-rag campaign build --topic "polyamide membrane fouling"
```

Question order mirrors ccds: identity → credentials/models → domain → corpus → stack
choices → licensing/git. Every question has a default; pressing Enter through the whole
session yields a working offline demo project.

---

## Implementation

### New package: `src/sci_rag/scaffold/`

Naming matches the repo's existing domain-noun modules (`ingest`, `embed`, `graph`,
`campaigns`). Every module must **lazy-import** heavy deps so `sci-rag-new` starts fast;
nothing here may import `sci_rag.db`, `sci_rag.server`, or `sci_rag.llm` at module scope.

| Module | Responsibility |
|---|---|
| `questions.py` | Declarative `Question` list -- prompt text, default, choices, validator, and which answers gate it. Single source of truth for the wizard **and** the docs transcript test. |
| `answers.py` | `ProjectAnswers` pydantic model. Validates the full answer set (e.g. `credentials=offline` forces `embedding_provider=local-hash`). |
| `wizard.py` | `run_wizard()` -- drives `questions.py` over Rich prompts, returns `ProjectAnswers`. Supports `--defaults` (non-interactive) and `--answers-file answers.yaml` for CI and reproducible generation. |
| `fetch.py` | Downloads the template tarball from GitHub at tag `v{version}` (`importlib.metadata.version("sci-rag-kit")`), extracts to the target dir. `--ref` overrides the tag; `--template-path` uses a local checkout (needed for tests and for `sci-rag init`). Uses `httpx`, already a direct dep -- no `git` binary required. |
| `apply.py` | The appliers, each a pure `(ProjectAnswers, Path) -> list[str]` returning a change log: `domain.yaml`, `.env`, `pyproject.toml`, `README.md`, seed questions, corpus scaffold, pruning, `LICENSE`, `Makefile` target. |
| `runners.py` | One `RunnerProfile` per environment manager -- the single place any manager-specific string lives. See the section below. |
| `ontology.py` | LLM-drafted ontology. Lazily imports `sci_rag.llm.client`, renders a new `domain/prompts/ontology_draft.md`, parses the response into `DomainConfig` (reusing `EntityTypeSpec`/`RelationTypeSpec`/`QueryClassSpec` from `src/sci_rag/domain.py`) so a malformed draft fails validation rather than writing junk YAML. Offers accept / reject / redraft. |
| `licenses.py` | BSD-3-Clause, MIT, Apache-2.0 texts + author/year substitution. |

### Writers -- what each answer actually changes

- **`domain/domain.yaml`** -- built by serializing a `DomainConfig` (from `src/sci_rag/domain.py:86`), so the output is validated by the same model `load_domain()` reads. `retrieval.reranker.enabled/adapter` come from the reranker answer.
- **`.env`** -- generated from the answered credential/model choices, preserving the section comments of `.env.example`. Also writes `SCI_RAG_CAMPAIGN_MAILTO` from `contact_email`.
- **`pyproject.toml`** -- `name`, `description`, and `[project.optional-dependencies]` selection driven by the parser/reranker answers (`docling`, `rerank`, `tokenizers` already exist at `pyproject.toml:40-47`).
- **Corpus scaffold** (the "maximal" choice):
  - `local_files` → `data/raw/.gitkeep` + a `data/corpus.jsonl` whose only content is `#` comment lines showing the field shape. Safe: `load_manifest()` skips blank and `#` lines (`src/sci_rag/ingest/manifest.py:53`).
  - `openalex_topic` → a `make corpus` target prefilled with `sci-rag campaign build --topic "<topic>" --max-results <n>`.
  - `doi_list` → `data/dois.txt` with a commented header + a `make corpus` target using `--doi-file data/dois.txt`.
  - `demo_only` → keeps `data/demo/` and leaves `make demo` as the next step.
- **Pruning** -- `infra/terraform/`, `data/demo/`, `examples/` removed when declined. Removing `infra/terraform/` must also drop the `terraform` job from `.github/workflows/ci.yml`, or the generated repo's first CI run fails.
- **Git** -- `git init`, `git add -A`, one commit. Never touches the user's existing repo when run via `sci-rag init`.

### Dependency managers -- the largest piece of this work

The kit is uv-wired in **five** places, and every one of them has to agree or the
generated project is broken on first run:

| Surface | Current uv form | File |
|---|---|---|
| Task commands | `uv sync`, `uv run sci-rag …` | `Makefile` (all targets) |
| CI | `astral-sh/setup-uv@v7`, `uv sync`, `uv run pytest/mypy` | `.github/workflows/ci.yml:38-51` |
| Container | uv-based install | `Dockerfile` |
| Dev container | uv bootstrap | `.devcontainer/` |
| Docs | `uv run …` in every example | `docs/quickstart.md`, `README.md`, `docs/cli.md` |

So `runners.py` defines one `RunnerProfile` per manager and **every one of those five
surfaces is rendered from it**. Nothing else in the scaffold may hardcode a manager name.

| Field | uv | pixi | conda | venv+pip |
|---|---|---|---|---|
| `run_prefix` | `uv run` | `pixi run` | `conda run -n <slug>` | `` (activated venv) |
| `sync_command` | `uv sync` | `pixi install` | `conda env create -f environment.yml` | `python -m venv .venv && pip install -e ".[dev]"` |
| `manifest` | `pyproject.toml` (`[dependency-groups]`) | `pyproject.toml` `[tool.pixi]` **or** `pixi.toml` | `environment.yml` | `requirements.txt` + `requirements-dev.txt` |
| `lockfile` | `uv.lock` | `pixi.lock` | none | none |
| `ci_setup` | `astral-sh/setup-uv@v7` | `prefix-dev/setup-pixi@v0` | `conda-incubator/setup-miniconda@v3` | `actions/setup-python@v5` |

**Which managers, and why these four**

- **uv** -- default; the status quo and what upstream CI runs.
- **pixi** -- required for the UW-SSEC collaborators. It is also the best *technical* fit
  of the alternatives: conda-forge **and** PyPI in one manifest, a multi-platform
  `pixi.lock` (genuinely useful for reproducible science), and native `pixi run` tasks
  that map one-to-one onto the existing Makefile targets.
- **conda / mamba** -- still the default in a lot of academic and national-lab
  environments; `environment.yml` is what many institutional setups expect.
- **venv + pip** -- the universal fallback for HPC, air-gapped, and locked-down images
  where neither uv nor pixi can be installed.

**Deliberately excluded:** poetry, pipenv, hatch. Poetry and pipenv both fight
PEP 735 `[dependency-groups]`, which this project already uses (`pyproject.toml:56-69`);
hatch adds little given hatchling is already only the *build* backend. Each extra manager
multiplies the generated-project test matrix, so these stay out until someone asks. Adding
one later is a new `RunnerProfile`, not a redesign.

**Two things to settle during implementation**

1. *pixi tasks vs Makefile.* Recommend keeping `make` as the portable entry point for all
   four managers (it already is), **and additionally** emitting `[tool.pixi.tasks]`
   mirroring the targets, so `pixi run setup` / `pixi run demo` work natively. Generated
   docs show the chosen manager's idiom.
2. *A Docker-free database for pixi.* pixi can install `postgresql` from conda-forge,
   which would let pixi users skip the Docker requirement in `docs/quickstart.md`. That
   is a real draw for exactly the audience asking for pixi -- **but it depends on
   `pgvector` being available on conda-forge for macOS ARM and Linux x86, which I have
   not verified.** Treat it as an opportunity to confirm early, not a commitment; if it
   does not hold, pixi users keep using `docker compose` like everyone else.

Also add a `python_version` question (default `3.12`, limited to `3.11`/`3.12` to match
`requires-python = ">=3.11"` and the classifiers at `pyproject.toml:9-16`). conda and pixi
both need an explicit Python pin in their manifests, so this stops being optional.

### One real bug this exposes

`Settings` uses pydantic-settings with `env_file=".env"` (`src/sci_rag/config.py:22-27`),
which reads `.env` but **does not export into `os.environ`**. So Typer's
`envvar="SCI_RAG_CAMPAIGN_MAILTO"` on `campaign discover`/`campaign build`, and the
`os.environ.get("OPENALEX_API_KEY")` lookup in `campaign_discover`, cannot see values
written to `.env` today. Writing `SCI_RAG_CAMPAIGN_MAILTO` into `.env` would silently do
nothing.

Fix with a ~10-line `_load_dotenv_into_environ()` in `src/sci_rag/cli/main.py`, called
once at startup, which sets only keys **not already** in `os.environ` (real env vars keep
precedence). No new dependency. Small, independently testable, and it makes `.env` behave
the way the docs already imply.

### CLI wiring

```toml
[project.scripts]
sci-rag = "sci_rag.cli.main:app"
sci-rag-new = "sci_rag.cli.new:main"
```

Plus `sci-rag init` registered in `src/sci_rag/cli/main.py` alongside the existing
`app.add_typer(...)` groups.

---

## Packaging and release

Publishing to PyPI is new to this repo -- there is no release workflow today, only
`ci.yml` and `docs-deploy.yml`.

1. Reserve `sci-rag-kit` on PyPI and configure **Trusted Publishing** (OIDC, no long-lived token).
2. Add `.github/workflows/release.yml`: on tag `v*`, `uv build` → `pypa/gh-action-pypi-publish`. Gate on the existing `ci` workflow passing.
3. Publish to **TestPyPI first** and verify `pipx install --index-url ... sci-rag-kit && sci-rag-new --defaults` end to end.
4. Document the release steps in `docs/VERSIONING.md`.

**Tradeoff to accept knowingly:** `pipx install sci-rag-kit` pulls the full runtime --
fastapi, uvicorn, asyncpg, sqlalchemy, alembic, pgvector, google-genai, mcp, pypdf -- a
heavy install for what is mostly a generator. Justified because the same install also
gives the user `sci-rag` itself, and pipx isolates it. The lazy-import discipline above
keeps *startup* fast even though *install* is not. (`uvx sci-rag-kit sci-rag-new` works
the same way with no persistent install.)

**Version pinning:** `sci-rag-new` fetches the template at the tag matching its own
installed version, so a given generator release always produces the same project.

---

## Docs

### Homepage (`docs/index.md`)

Replace the existing `#quickstart` console block (`docs/index.md:81-86`, currently
`git clone … && make setup`) with the two-line install + run, and add an animated
terminal:

```console
$ pipx install sci-rag-kit
$ sci-rag-new
```

- Record a real session with `asciinema rec` → commit `docs/assets/casts/sci-rag-new.cast`.
- Vendor `asciinema-player` v3 (JS + CSS) into `docs/assets/vendor/`; add an
  `extra_javascript:` key to `mkdocs.yml` (only `extra_css:` exists today, at line 145)
  and register the CSS in the existing list. Vendoring -- not CDN -- keeps the docs build
  hermetic and the lychee link-check job green.
- Keep the **full static transcript visible below the player** in an `## Example`
  section, exactly as the ccds page does. It is copy-pasteable, survives no-JS, and is
  the artifact CI can assert against.
- Add a `make cast` target documenting how to re-record when the questions change.
- Theme the player with the existing `srag-*` tokens in `docs/stylesheets/tokens.css`
  so light/dark match the rest of the site.

### Prose that must change

- **`docs/index.md:165`** currently reads *"Sci RAG Kit is not a code generator."* Reword
  to draw the real distinction: it specializes one working repository rather than
  rendering placeholders -- the generator configures, it does not template.
- **`docs/index.md:48`** -- "install by template or clone" → mention `pipx`.
- **`docs/quickstart.md` step 1** -- lead with `sci-rag-new`, keep clone/template as alternatives.
- **`docs/bring-your-own-domain.md`** -- reframe as "what the wizard asked you, and how to change your answers later."
- **New `docs/adr/0006-interactive-project-generator.md`** -- records that this *implements*
  ADR 0004's escape hatch: post-fetch applier, no placeholders, wizard is CI-tested code,
  package name stays `sci_rag`. Add to `mkdocs.yml` nav under Decision records.

---

## Verification

1. `make lint && make typecheck` -- note `make lint` covers `src tests examples scripts`.
2. `uv run pytest` -- CI enforces `--cov-fail-under=78`, so the new modules need real tests:
   - `apply.py` writers as table-driven unit tests (answers in → file content out).
   - Generated `domain.yaml` round-trips through `load_domain()` for all three ontology modes.
   - Generated `data/corpus.jsonl` parses through `load_manifest()`.
   - Full non-interactive generation against a `--template-path` local checkout, asserting
     pruning, license text, and that no `{{` survives anywhere.
   - The docs transcript matches `questions.py` (guards against the homepage going stale).
   - `ontology.py` against a stubbed LLM client, including a malformed-response rejection.
   - **Runner coherence, once per profile:** generate with each of the four managers and
     assert no other manager's command survives anywhere in the tree -- e.g. a pixi project
     contains no `uv run` in its `Makefile`, `ci.yml`, `Dockerfile`, `README.md`, or
     `docs/`. This is the cheap test that catches the whole class of "five surfaces
     disagree" bugs.
3. `make docs-reference` -- regenerates `docs/cli.md` from the Typer app so `sci-rag init` appears.
4. `make docs` -- builds as CI does; confirms the player assets and nav entry resolve.
5. **End-to-end, the real proof:** from `/tmp`, `uvx --from . sci-rag-new` with a scripted
   answer file → `cd` into the result → run the profile's sync command → `sci-rag doctor`
   reports healthy → the offline demo passes. Then repeat with `credentials=google_ai_studio`
   and confirm the LLM-drafted ontology validates and `sci-rag answer` returns a cited answer.
6. **Generated-project matrix in CI:** a job that generates a project per environment
   manager and runs lint + typecheck + the offline demo inside it. pixi and conda installs
   are slow and network-heavy, so run **uv on every PR** and the full four-way matrix
   **nightly / on release tags** rather than per-push. Do this before advertising pixi
   support in the docs -- an untested manager option is worse than no option.
7. Re-record the cast only after the questions are final.

## Suggested sequencing

Land in four PRs rather than one -- the packaging and multi-manager changes are each
independently risky:

1. **Wizard + `sci-rag init`** (in-repo, fully testable, no distribution change) -- includes
   the `.env`→`os.environ` fix. Ships with the `uv` profile only, so `runners.py` exists
   but has one entry.
2. **Environment managers** -- `runners.py` gains pixi, conda, and venv+pip; the Makefile,
   CI, Dockerfile, devcontainer, and docs renderers land together with the runner-coherence
   tests and the nightly matrix job. Confirm the conda-forge `pgvector` question here.
3. **`sci-rag-new` + fetch + PyPI release workflow** (TestPyPI first).
4. **Docs, homepage cast, ADR 0006.**

Splitting 1 and 2 matters: the wizard is a self-contained feature, whereas rendering five
surfaces per manager is where the real risk lives, and it deserves its own review and its
own test matrix.
