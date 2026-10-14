# Migration ledger: personal-agent (step 1)

Date: 2026-10-14. Sources are read-only references; this repository is the
single working home going forward.

## Migrated from sci-rag-kit (knowledge base base)

Source: `C:/Users/12062/OneDrive/Desktop/items/sci-rag-kit` (main worktree).

- Full working tree copied: `src/sci_rag/`, `tests/`, `migrations/`, `scripts/`,
  `domain/`, `data/demo/`, `data/snapshots/`, `examples/`, `docs/`, `infra/`,
  `alembic.ini`, `pyproject.toml`, `uv.lock`, `Makefile`, `Dockerfile`,
  `docker-compose.yml`, `mkdocs.yml`, `.github/`, `.pre-commit-config.yaml`,
  `.gitignore`, `.dockerignore`, `.python-version`, and the root docs.
- **Excluded on purpose**: `.git/` (fresh history here), `.venv/`, `.worktrees/`,
  `site/`, `backups/` contents (the tracked `backups/.gitkeep` marker is kept:
  `test_docs_backup_runbook` requires the directory in a fresh checkout),
  `data/raw/` (331 MB of downloaded papers), `data/interim/`,
  `data/processed/`, all `__pycache__`/`.pyc`, and `.env` (**contains local
  credentials; never copy, never commit**). `.env.example` is included.
- Package name and CLI kept as `sci_rag` / `sci-rag`: the fork keeps upstream
  import and contract stability for now. Renaming is a later, explicit change.

## Migrated from GenericAgent (memory face)

Source: `C:/Users/12062/OneDrive/Desktop/items/GenericAgent`.

- `plugins/hooks.py`, `plugins/project_mode.py` (standalone plugin bus, copied
  verbatim), plus a new `plugins/__init__.py`.
- `memory/memory_management_sop.md` (L0 meta SOP, verbatim) and the memory
  templates `insight_fixed_structure*.txt`, `global_mem_insight_template*.txt`.
- Nothing else from GenericAgent is vendored. The agent runtime itself stays an
  external GenericAgent instance; this repo holds only what the memory face
  needs (spec 4.7: zero changes to GenericAgent seed code).

## Specialized for this project (new files)

- `domain-personal/` (spec 4.2): personal file space ontology (12 entity types,
  11 relations), personal query classes, specialized extraction prompt, draft
  project inference and tag extraction prompts. Activated with
  `SCI_RAG_DOMAIN_DIR=domain-personal`; the shipped `domain/` demo profile stays
  untouched as the test baseline.
- `memory/global_mem_insight.txt` (L1 index seed), `memory/global_mem.txt`
  (L2 facts seed), `memory/pcmem_sop.md` (L3 knowledge base usage SOP).
- `plugins/pcmem_router.py`: memory router skeleton on the hook bus (spec 4.7
  trigger map; injections land in later phases).

## Deviations from copied sources (recorded, semantics unchanged)

- `plugins/project_mode.py` and `docs/superpowers/specs/2026-10-14-spec-review-report.md`:
  two em-dash (U+2014) punctuations each replaced with a colon or opening quote.
  Reason: `tests/unit/test_docs_style.py::test_no_page_uses_an_em_dash` enforces
  "no em dashes anywhere in repository source". The spec review report already
  violated the repo's own rule before migration; no wording or meaning changed.

## Not migrated (deliberate, pending phases)

| Item | Why | Where it lands |
| --- | --- | --- |
| `feature/incremental-reconcile` branch (reconcile.py, fingerprint.py, 21 files) | It is a merge with semantic conflicts (ADR 0012 clash, version chain rewrite), not a copy | Spec P0 clean-up |
| `data/raw/` corpus (331 MB) | Private/local downloads; rebuild per-machine | local only |
| `.env` | Credentials stay on the source machine | copy manually if needed |
| GenericAgent core runtime (agentmain/llmcore/ga/frontends) | Runs as an external instance; vendoring is not needed for the memory face | out of scope |
| `docs/cli.md`, `docs/configuration.md`, `docs/benchmarks.md` regeneration | Generated pages; regenerate on this host with the backslash-normalization procedure only | later doc pass |

## Verification performed at migration time

See the step 1 handoff message for exact commands and results (offline unit
suite, CLI smoke, plugin import, domain load). Anything not run is listed
there as not verified.
