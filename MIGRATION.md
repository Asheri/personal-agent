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

## Design baseline installed in-repo

- `docs/superpowers/specs/设计方案-全PC文件记忆系统-spec.md` (spec v1.1) and
  `docs/superpowers/specs/设计方案-全PC文件记忆系统-spec审查.md` (review report): working
  copies of the reviewed PC-Mem design artifacts. The reviewed originals stay outside
  the repository at `C:/Users/12062/OneDrive/Desktop/items/` as the audit baseline.
- Governance: every spec-derived improvement or change requires a secondary review by
  a non-author before merge (AGENTS.md section 5). Spec revisions bump the version and
  are themselves reviewed; history is superseded, never rewritten.

## Deviations from copied sources (recorded, semantics unchanged)

- `plugins/project_mode.py` and `docs/superpowers/specs/2026-10-14-spec-review-report.md`:
  two em-dash (U+2014) punctuations each replaced with a colon or opening quote.
  Reason: `tests/unit/test_docs_style.py::test_no_page_uses_an_em_dash` enforces
  "no em dashes anywhere in repository source". The spec review report already
  violated the repo's own rule before migration; no wording or meaning changed.
- The two installed PC-Mem spec copies above: 6 and 2 em-dash punctuations replaced
  with colons or a semicolon for the same house rule. Pure punctuation, semantics
  unchanged; the originals outside the repository are untouched.
- Upstream `AGENTS.md` (sci-rag-kit operating contract) removed from the repository per
  project decision; the original stays in the source repo at `items/sci-rag-kit/`. Its
  still-binding test/style/docs discipline is folded into AGENTS.md sections 3 and 4.
  `AGENT.md` renamed to `AGENTS.md` as the single entry file (ledger row D10).

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

## Scoped serial follow-up: 2026-10-25 Chinese and model quality

Continue from the document-relations handoff without changing that snapshot.
The v1.6 candidate adds migration 0011, pinned jieba 0.42.1 indexing, Chinese
class/routing cues, and a same-corpus semantic-vector spike. The default demo
profile, fusion weights, embedding providers, and citation-expansion default remain
unchanged. Derived Chinese caches are excluded from corpus exports.

Personal ontology names and endpoint types are explicit contracts. Literal
entity, alias, and relation provenance is enforced across extraction domains.
The scripted English graph fixture now includes its claimed source quotes and
maps the actual numbered passage; its previous fixed passage-1 response could
describe an unrelated almond chunk. Assertions on graph shape and behavior stay.

The user selected controlled model evaluation. Retain all failed trials, source
facts, hashes, exact scores, and raw answers. No result supplies independent
human approval, a blinded field benchmark, or evidence of general KG superiority.
See ADRs 0017/0018, the v1.6 candidate, and the dated handoff for validation and
owned-service/test-data cleanup. This does not adopt a new reviewed baseline.
# Local file parsing follow-up (2026-10-25)

The serial v1.7 candidate adds XLSX, EML/MBOX, code/scripts, text data, and
optional offline OCR, with 41 suffixes in the discovery/parser whitelist.
No schema migration; revision 0011 remains current. Ingest signature format 2
triggers one checked reparse of older sources. See `docs/file-types.md`,
ADR 0019, and the dated candidate and pending review record.

Explicit specification departures: no-ID mailbox content/occurrence keys replace
ordinal identity; code retains full source chunks plus compact metadata rather
than separate compact vectors; mail dates use existing extra metadata. A mailbox
host transaction covers all writes and absent-member chain deletion. Legacy
flattened mailbox rows require an explicit rebuild. Duplicate Message-IDs fail
without partially changing the host. Default domain files remain unchanged.

Archive controlled/failed trials and cleanup receipts under
`.context/file-types-20261025/`. A pure-English marker next to Chinese punctuation
can miss the English keyword route; format acceptance reports both query routes
and their union. Clean printed OCR tests do not establish field accuracy. Group
nonauthor adoption, full browsing, automatic triggers, and final course materials
remain open. This entry supplements historical migration records.
# Core engineering follow-up (2026-10-26)

Candidate v1.8 adds revision 0012 (indexed document dates/access metadata and
universal simple-index backfill) and 0013 (content-free file/refresh event audit).
Backfill uses stored metadata, never opens legacy source paths. Coordinated
schema/application rollback restores the old token policy and removes date/access
or event data; back up retained databases and audit records first.

Browse filters and counts share retrieval scope. Refresh scheduler/hooks/poll
entry points share the existing connection-owned advisory lock. Agent integration
uses a plugin, stdin-based local CLI calls, launchers, and upstream scheduler task
definitions; seed files remain unchanged. External MCP and public manifest reads
now enforce external-safe rights across metadata and alternate paths. This is an
intentional privacy correction from permissive defaults.

See `docs/core-completion.md`, `docs/deploy-pcmem.md`, the engineering matrix,
ADR 0020, and the dated candidate/review. Acceptance does not register a persistent
OS task, run a live model conversation, access a personal corpus, or approve a
merge. Optional P6 research, independent review, and course deliverables remain
separate. Historical migration and candidate records remain unchanged.
