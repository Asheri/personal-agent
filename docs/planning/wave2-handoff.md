# Wave 2 handoff: drive v0.3 "Campaigns" to completion

> Written 2026-08-27 at the close of Wave 1 (v0.2 "Credibility", epic #5,
> released as v0.2.0). This document is the execution brief for a fresh
> agent with zero prior context. It contains the mission, the full
> process contract that Wave 1 proved out, the technical map of every
> seam Wave 2 touches, and the negative knowledge (what not to do and
> why). Read it fully before writing anything.

## 0. Orientation (who, what, where)

- **Repo**: `github.com/sustainability-software-lab/sci-rag-kit`,
  **PRIVATE**, a GitHub template repository. Local checkout:
  `~/conductor/repos/sci-rag-kit` (plain clone, `main` branch; if
  missing, clone via SSH `git@github.com:sustainability-software-lab/sci-rag-kit.git`).
- **What it is**: a DIY GraphRAG factory for scientific domains. One
  Postgres database (pgvector + full text + graph-as-rows), five fused
  retrieval layers plus post-fusion rerank and adaptive routing, blind
  two-pass answer judging with kappa calibration, REST + MCP serving,
  fail-closed license scoping. Python 3.11/3.12, `uv`, package
  `sci_rag`, CLI `sci-rag`.
- **Read in this order** before planning: this file; the Wave 2 section
  of `docs/planning/v02-roadmap-plan.md` (the canonical scope source);
  `docs/ROADMAP.md` (public framing); `docs/methodology.md` (design
  rationale and the anti-recommendation list); `docs/architecture.md`.
- **Naming rule**: the LBL flagship domain is **BioCirV** (an early
  draft said "BioServ"; that name must not appear in anything new).
- **No em dashes** in code, docs, commit messages, PR bodies, or issue
  text. Use a period, comma, or colon.
- **Honesty rules** (non-negotiable house law): no fabricated or
  extrapolated numbers anywhere; every published number comes from a
  real run; every retrieval-affecting change ships with an ablation
  config and lands with before/after evidence; small-sample caveats are
  stated, not hidden.

## 1. Mission

Plan and fully execute **Wave 2 (v0.3 "Campaigns")**: the release that
makes the kit specifically better for science than general-purpose RAG
frameworks. Scope, from `docs/planning/v02-roadmap-plan.md` (section
"WAVE 2"), in suggested execution order:

1. **Metadata filters.** Extend `RetrievalScope` with year range,
   author, journal, and DOI excludes; enforce inside every layer's SQL;
   wire through `Retriever.retrieve`, `/v1/query` schemas, MCP tools,
   and the CLI. Needs a migration for a `journal` column + index on
   `documents`.
2. **Retraction and metadata enrichment.** `sci-rag corpus enrich` (or
   similar): Crossref REST (which carries Retraction Watch data) and
   optional Semantic Scholar enrichment into `Document.extra`
   (retraction status, citation count, journal); new
   `RetrievalScope.exclude_retracted`, **default ON for answering**,
   enforced in every layer; `doctor` warns when retracted documents are
   present.
3. **Extraction upgrade: aliases + confidence.** The extraction prompt
   emits entity aliases and a calibrated relationship confidence; the
   extractor parses and stores them. This is pure foundation for items
   5 and 6; the dormant columns already exist (see technical map).
4. **Campaign corpus builder.** `sci-rag campaign build
   --topic ... | --doi-file ...`: OpenAlex/Crossref discovery to a DOI
   list, Unpaywall open-access resolution, download of legal PDFs only,
   and a corpus manifest whose `license_class` derives from OA status
   **failing closed to `unknown`**. `--dry-run` first (shows counts and
   license distribution without downloading). Rate-limited, resumable
   (a partial run picks up where it stopped).
5. **Entity resolution.** `sci-rag graph resolve-entities [--dry-run]`:
   merge duplicate entities by alias match, fuzzy name match, and LLM
   adjudication for the ambiguous middle; write an audit log; keep
   merged entities reachable via `canonical_entity_id`. An ablation
   (`sci-rag eval diff` before/after on the demo corpus) decides
   whether resolution stays recommended.
6. **Confidence-weighted traversal.** The graph stage filters or
   down-weights low-confidence relationships; ablation config
   (`confidence_weighted` vs `full_deep`).
7. **Citation-graph edges.** Extract references (Crossref metadata
   first; GROBID or Docling reference parsing as fallback) into `CITES`
   edges **between documents present in the corpus**; citation
   traversal joins the graph stage; MCP gains
   `get_citations(document_id)`.
8. **Contextual snippet compression** (the PaperQA2 pattern, optional
   flag): per-chunk relevance-scored summarization before answer
   assembly. Landing condition: the judged-answers eval shows quality
   holds (dimension means within CI) while prompt tokens drop
   measurably. If quality drops, the honest outcome is "not adopted,
   evidence recorded" and the flag stays off or is removed.
9. **PRISMA-style screening** (stretch; MAY SLIP): `sci-rag campaign
   screen`: LLM inclusion/exclusion on abstracts with a human-review
   queue for low-confidence rows and PRISMA-aligned counts in the
   report. Decision rule: if this balloons, file it as a follow-up
   issue, note the slip in ROADMAP.md, and do not block the release.
10. **Release wrap.** Benchmark refresh (`make benchmark`) including
    the new ablation configs, CHANGELOG 0.3.0 entry, version bump,
    ROADMAP.md updated (Wave 2 moves to "Shipped"), epic closed with a
    verification comment.

Out of scope, permanently (anti-recommendations recorded in the plan
doc and methodology): Neo4j or any graph-database migration, RAPTOR,
default agentic retrieval loops, index-time contextual embedding,
learned fusion. Wave 3 items (lazy community summaries, extraction
caching, bi-temporal edges, multi-corpus, observability, more parsers,
hierarchical communities) are NOT yours; leave them in ROADMAP.

## 2. Process contract (exactly what worked for Wave 1)

### 2.1 Scaffold before code

1. Do a light drift scan first: this handoff was written 2026-08-27
   against commit `a8f5331` (tag v0.2.0). Verify the files named in the
   technical map still exist; if the repo has moved substantially,
   re-derive rather than assuming.
2. Author the Wave 2 execution plan (this document plus the plan doc's
   Wave 2 section are your inputs; you decide final decomposition and
   dependency order) and commit it under `docs/planning/` (markdown
   direct-push to main is precedented for planning docs; get the SHA
   permalink for issue bodies).
3. Create milestone **"v0.3 Campaigns"**, an epic issue (label `epic`,
   pattern of epic #5: Summary / Context / Scope / Out of Scope /
   Sub-Issues by tier / Dependency Order table / Gating Strategy
   ("none: library repo, features off by default") / Acceptance
   Criteria / References), and one sub-issue per item with **Type /
   Plan doc / Parent epic** headers, an Implementation Approach section
   naming exact files, a TDD Contract, and checkbox acceptance
   criteria. Link them as native sub-issues:
   `SUB_ID=$(gh api repos/<repo>/issues/<n> --jq .id); gh api -X POST
   repos/<repo>/issues/<epic>/sub_issues -F sub_issue_id=$SUB_ID`
   (integer database id with `-F`; milestone flag takes the TITLE
   string; backfill `#?S<n>` placeholders in reverse numeric order so
   S1 does not clobber S10).
4. Post an implementation-start comment on the epic recording the
   drift-check result and the execution order.

### 2.2 Per sub-issue loop (TDD, strictly)

1. Branch from the latest `main` (or stack on the previous unmerged
   branch ONLY when touching the shared hotspots: `cli/main.py`,
   `retrieve/types.py`, `server/schemas.py`, `evals/report.py`,
   `db/models.py`).
2. Write failing tests FIRST; run them; confirm they fail for the right
   reason (missing module, not a typo).
3. Implement minimally; `make check` (ruff + mypy + pytest) must be
   fully green locally before any push. Also run
   `uv run ruff check src tests examples scripts` (the Makefile and CI
   lint skip `scripts/`; keep it clean anyway).
4. Commit with a conventional-commit message whose body says what and
   why; include `Closes #<sub-issue>` in the PR body (auto-closes on
   merge).
5. `git push -u origin <branch>`, `gh pr create --base main` with a PR
   body carrying the evidence (test counts, demo output), then
   IMMEDIATELY `gh pr merge <branch> --squash --auto`. The 5 required
   checks are `checks (3.11)`, `checks (3.12)`, `docker`, `terraform`,
   `docs-links`; auto-merge fires when green (about 5-7 minutes).
6. Comment on the sub-issue that the PR is open and armed.
7. While CI runs, start the next sub-issue stacked on the current
   branch. After the parent squash-merges, restack with
   `git fetch origin && git rebase --onto origin/main <old-parent-sha>
   <branch>` (squash rewrites history; plain `git rebase main`
   duplicates commits). To restack onto a not-yet-merged parent branch
   after IT was rebased: `git rebase --onto <parent-branch>
   <old-parent-sha> <branch>`.
8. Never force-push except `--force-with-lease` on your own PR branch
   after an amend.

### 2.3 Evidence discipline

- Every retrieval-affecting item adds an `AblationConfig` to
  `DEFAULT_ABLATIONS` in `src/sci_rag/evals/retrieval_eval.py`.
- Demonstrations use REAL runs: the pattern that worked is a scratch
  database per demo (`docker exec sci-rag-db psql -U sci_rag -c
  "CREATE DATABASE <name>"`, then `SCI_RAG_DATABASE_URL=...` on the
  command). Offline demos use `SCI_RAG_EMBEDDING_PROVIDER=local-hash
  SCI_RAG_EMBEDDING_DIM=64`; cloud demos use
  `SCI_RAG_GCP_PROJECT=<your-project> SCI_RAG_GCP_LOCATION=us-central1`
  (ADC is configured on this machine; models: gemini-2.5-flash +
  gemini-embedding-001; a full demo-corpus benchmark run costs cents).
  Any other gcloud invocation must pass `--project=<your-project>`
  explicitly. The concrete project id was redacted by #200; this
  repository names no maintained Google Cloud project.
- The release-wrap sub-issue re-runs `make benchmark` (it is the REAL
  pipeline end to end: ingest, graph, snapshot, full ablation, judged
  answers, calibration, re-render `docs/benchmarks.md`) so the page
  carries the new configs with measured numbers.
- Paired claims ("compression keeps quality") are proven with
  `sci-rag eval diff` between two real runs, quoted in the PR body.

### 2.4 Definition of done (the /goal condition)

Wrap the session in this goal condition (or its moral equivalent):

```
sci-rag-kit Wave 2 (v0.3 Campaigns) fully implemented and landed on
main: metadata filters, retraction-aware enrichment with
exclude_retracted default-on for answering, alias+confidence
extraction, campaign builder with fail-closed licensing and dry-run,
entity resolution with audit log, confidence-weighted traversal,
citation edges with MCP get_citations, and snippet compression
(adopted or rejected on judged evidence); PRISMA screening landed or
explicitly slipped with a ROADMAP note; every retrieval-affecting item
has an ablation config and evidence; make check green and all 5 CI
checks green on main; docs/benchmarks.md refreshed via make benchmark;
CHANGELOG 0.3.0 + version bump + ROADMAP updated; a GitHub epic with
native sub-issues tracks the work and ends CLOSED with a verification
comment; BioCirV naming; repo remains private; user-gated items
(CITATION.cff, Zenodo, JOSS, PyPI, hosted demo, flip-public, the
v0.3.0 git tag) NOT executed, only listed; or stop and report after 20
turns.
```

The v0.3.0 TAG is explicitly user-gated: prepare everything (version
bump, CHANGELOG, release notes) and hand the tag decision back.

## 3. Technical map (the seams Wave 2 touches)

### Storage and models (`src/sci_rag/db/models.py`, `migrations/`)

- `Document`: has `doi`, `publication_year`, `authors` (ARRAY),
  `license_class`, `source`, `content_hash` (unique), and **`extra`
  JSONB (empty dict default): enrichment lands here** (retraction
  status, citation count, journal...). A first-class `journal` column
  + index needs **migration 0003** (filters should not query JSONB).
- `KgEntity`: **`aliases` ARRAY exists and is stored but unused**
  (activate in item 3); `document_ids`/`chunk_ids` evidence arrays
  (scrubbed by corpus delete; GC removes evidence-less entities).
  Entity resolution adds `canonical_entity_id` (nullable FK-ish column,
  migration) plus an audit-log table (design it; a JSONL file under
  `data/` was rejected for Wave 1 features because DB state must
  survive redeploys).
- `KgRelationship`: **`confidence` Float exists, default 1.0, unused**
  (activate in items 3 and 6); has `document_id`/`chunk_id` evidence
  pointers and `evidence` text.
- `KgCommunity`: `summary_embedding_version` stamped since 0.2
  (migration 0002 pattern: `ADD COLUMN IF NOT EXISTS` so fresh DBs,
  where 0001's `create_all` already made it, are a no-op. COPY THIS
  PATTERN for 0003+).
- **CITES representation decision** (make it in the planning pass,
  record as an ADR): `KgRelationship` is entity-to-entity, but the
  plan wants document-to-document CITES edges. Options: (a) a new
  `document_citations` table (clean, obvious joins for traversal and
  `get_citations`); (b) synthetic per-document entities. Wave 1's
  instinct: (a). Whatever you choose, `corpus delete` and `graph gc`
  in `src/sci_rag/corpus.py` MUST be extended to clean it up, and the
  every-layer unreachability regression test
  (`tests/integration/test_corpus_delete.py`) must grow a citation
  case.

### Retrieval (`src/sci_rag/retrieve/`)

- `types.py`: `RetrievalScope` (frozen dataclass) + `scope_conditions()`
  build the SQL conditions **every stage applies**. Extending scope =
  add fields + conditions here and they ride into every layer. TRAP:
  `is_unrestricted()` gates the community layer (community summaries
  aggregate across documents pre-scope, so ANY restriction disables
  them); if you add fields and forget `is_unrestricted()`, scoped
  requests will silently keep serving community content. Add a test
  that a year-filtered request disables communities.
  `exclude_retracted` semantics: default OFF at the dataclass level
  but the ANSWER path (`server/service.py` answer flow + `AnswerEngine`
  callers and the answer CLI) constructs its scope with
  `exclude_retracted=True` unless the caller opts out.
- `retriever.py`: orchestrator; stages run concurrently under
  per-stage timeouts with honest `StageTrace`s; rerank is post-fusion;
  `profile="auto"` resolves via `router.py` BEFORE stage planning.
  Citation traversal joins as part of the graph stage (extend
  `stages/graph.py`, whose recursive `_WALK_SQL` + `MAX_HOPS` walk is
  the pattern), not as a sixth independent stage, unless the planning
  pass finds a strong reason.
- `stages/graph.py`: name-matched entities, recursive CTE walk,
  chunk-id collection, scope re-applied at resolution. Confidence
  weighting slots into the walk/order logic here.

### Extraction (`src/sci_rag/graph/extractor.py`, `domain/prompts/entity_extraction.md`)

- Prompt templates use `string.Template` with `$UPPER_CASE` slots (no
  brace escaping needed, JSON examples are safe). The extractor parses
  via `LLMClient.generate_json` -> `parse_json_loosely` (tolerates
  code fences). Emitting aliases + confidence means: prompt change +
  parser change + storing to the existing columns + updating the
  extraction tests (`tests/unit/test_graph_pure.py`,
  `tests/integration/test_graph.py`). Older domain dirs must keep
  working: parse the new fields as OPTIONAL with safe defaults
  (missing aliases -> [], missing confidence -> 1.0), same
  backward-compatibility pattern as the reranker's fallback prompt in
  `retrieve/rerank.py`.

### LLM plumbing (`src/sci_rag/llm/client.py`)

- ALWAYS go through `generate_json` for structured calls: it sets
  temperature 0, JSON mime type, and **thinking_budget=0** (Gemini 2.5
  models think by default and thought tokens eat max_output_tokens;
  this silently broke extraction once and is already handled here, with
  a retry-without-the-knob for models that reject it). `MockLLM`
  replays queued responses and records calls; use it everywhere
  offline.

### Campaigns (new package `src/sci_rag/campaigns/`)

- `httpx` is already a base dependency; build a small shared client
  with: a `mailto`/User-Agent parameter (Crossref and OpenAlex polite
  pools; Unpaywall REQUIRES an email query param), token-bucket rate
  limiting, retry-with-backoff on 429/5xx, and a resumable on-disk
  state file (JSONL of processed DOIs with status) so a killed run
  continues.
- OA-status -> license mapping FAILS CLOSED: only an explicit,
  recognized license signal (e.g. a CC license URL from Unpaywall/
  Crossref) maps to an open class; everything else is `unknown`
  (`src/sci_rag/licensing.py` holds the vocabulary and philosophy).
  Downloads: OA-flagged PDFs only; never scrape publisher paywalls.
- **CI stays offline**: all campaign tests run against recorded
  fixture JSON (commit small representative API responses under
  `tests/fixtures/campaigns/`); anything hitting the live APIs is
  marked with the existing `cloud` pytest marker (skipped by default
  and in CI). For PR evidence, run ONE small live dry-run (10-20 DOIs
  on a CC-licensed topic) locally and paste the output.

### Serving (`src/sci_rag/server/`)

- `schemas.py` (Pydantic contracts; extend `QueryRequest`/
  `AnswerRequest` with the new filter fields), `routers/query.py` and
  `service.py` (pass-through pattern used by `include_rerank` in 0.2),
  `mcp_server.py` (7 tools today; add `get_citations`). MCP SDK 2.x
  gotchas: the class is `MCPServer` (renamed from FastMCP);
  `session_manager.run()` must be driven by the parent lifespan when
  mounted; test the endpoint at `/mcp/` WITH trailing slash (bare
  `/mcp` 307-redirects in the parent router before auth wrappers);
  client results use snake_case (`server_info`, `input_schema`).
- `tests/server/test_api_contracts.py` asserts the full trace-stage
  set; adding a stage or trace kind means updating it (rerank and
  router did).

### Answering (`src/sci_rag/answer/generator.py`)

- Snippet compression hooks between retrieval and prompt assembly:
  optional per-chunk relevance-scored summarization (one batched JSON
  call, MockLLM-testable). It must record enough in the result to
  measure token reduction honestly (before/after token counts via
  `src/sci_rag/ingest/tokens.py` helpers).

### Evals (`src/sci_rag/evals/`)

- `stats.py` (bootstrap CIs, paired tests), `diff.py`, `calibration.py`
  are your measurement toolkit; do not reinvent. `report.py` writers
  state n and CI everywhere. Add ablation configs for: retraction
  filtering (should be neutral on the demo corpus, which has no
  retracted docs; SAY so), entity resolution before/after,
  `confidence_weighted`, compression on/off (answers eval, not
  retrieval).
- Doctor (`src/sci_rag/cli/doctor.py`): add checks for retracted
  documents present, unresolved duplicate entities (cheap heuristic),
  and campaign state files left mid-run.

### Tests infrastructure

- `tests/conftest.py` pins env BEFORE imports (`local-hash`, dim 64,
  test DB on port 5433 database `sci_rag_test`); integration tests
  SKIP cleanly if Postgres is down (`docker compose up -d --wait`
  starts it). `clean_tables` and `local_embedder` fixtures are
  session-loop-scoped.
- **CLI testing rule**: commands that call `asyncio.run` CANNOT be
  invoked via `CliRunner` from async tests (running-loop conflict +
  the cached asyncpg pool binds to one loop). Test them as
  subprocesses: `subprocess.run([sys.executable, "-m",
  "sci_rag.cli.main", ...], env=os.environ.copy(), cwd=repo_root)`
  (pattern: `tests/integration/test_reindex.py`). Sync CliRunner tests
  are fine for pure-file commands (pattern:
  `tests/unit/test_eval_diff.py`).

## 4. Negative knowledge (do NOT relearn these the hard way)

1. An interrupted `uv sync --all-extras` can corrupt the venv (native
   modules half-swapped, e.g. `pydantic_core` missing). Fix:
   `rm -rf .venv && uv sync`. Plain `uv sync` (no extras) matches CI.
2. Squash-merge + stacked branches: always `git rebase --onto` with the
   OLD parent SHA (section 2.2.7). Plain rebase duplicates commits.
3. `ruff` lints notebook cells (`.ipynb`): E402/E401/I001 apply INSIDE
   cells. If you touch `examples/`, run
   `uv run ruff check examples` before pushing; a notebook lint miss
   cost Wave 1 a red CI cycle.
4. `make check`'s lint covers `src tests examples` but NOT `scripts/`;
   CI matches. Check `scripts/` manually when you touch it.
5. Kappa is 0 whenever one rater is constant, even at high exact
   agreement. If you extend the calibration seed labels, include score
   variance, and never "fix" the formula.
6. `EMBEDDING_DIM` is baked into the SQLAlchemy models at import time
   from settings; env must be set before any `sci_rag` import
   (conftest does this; notebooks and scripts must too). pgvector HNSW
   caps at 2000 dims; 1536 is the ceiling-respecting default.
7. Migrations: 0001 runs `Base.metadata.create_all`, so on a FRESH
   database later migrations see the columns already present. Write
   0003+ with `IF NOT EXISTS` / `IF EXISTS` guards (0002 is the
   template). Never edit an existing migration.
8. Community layer disables itself under ANY scope restriction; new
   scope dimensions must preserve that (see `is_unrestricted` trap).
9. `parse_json_loosely` handles fenced JSON; malformed judge/extractor
   responses are recorded failures, never silent zeros. Keep that
   discipline in new parsers (campaign screening, compression scoring).
10. docs-links CI is lychee in offline mode: relative links must
    resolve within the repo; external URLs are not checked. A doc
    linking a file that lands in a LATER PR will fail docs-links on
    the EARLIER PR; sequence doc links with their targets.
11. GitHub sub-issue API wants the integer database `id` via `-F`
    (not issue number, not node_id); `--milestone` wants the title
    string; Discussions categories cannot be created via API (route
    RFCs to Ideas with an "RFC:" title prefix).
12. Direct pushes to `main` are technically possible for the admin
    (branch protection without enforce_admins) and were used ONLY for
    markdown-only planning docs. ALL code goes through PRs. The
    "Bypassed rule violations" push warning on docs pushes is normal.
13. The repo stays PRIVATE. Launch-gated items (CITATION.cff, Zenodo
    DOI, JOSS, PyPI, hosted demo, flip-public, release tags) are
    maintainer decisions: prepare, list, hand back, never execute.
14. Cross-pollination: as Wave 2 items prove out, file adoption issues
    in `sustainability-software-lab/project-pisces-frontend` (Wave 1
    filed #6962 stats/diff and #6963 routing there; Wave 2 candidates
    per the plan doc: snippet compression for KB answers, entity alias
    resolution for the KG, campaign builder for corpus growth).
15. Post progress comments on the epic at meaningful milestones and a
    completion comment with per-criterion verification before closing
    it. The issue thread is the system of record.

## 5. Suggested decomposition (finalize in your own planning pass)

| Tier | Sub-issue | Depends on |
|------|-----------|------------|
| T0 | S1 Metadata filters (scope + migration 0003 journal + API/CLI/MCP wiring) | none |
| T0 | S2 Enrichment + exclude_retracted (Crossref/RW, Document.extra, doctor) | none |
| T0 | S3 Extraction emits aliases + confidence (prompt + parser + storage) | none |
| T1 | S4 Campaign discovery (OpenAlex/Crossref -> DOI list, rate-limited, resumable) | none |
| T1 | S5 Campaign resolution + download + manifest (Unpaywall, fail-closed licensing, dry-run) | S4 |
| T2 | S6 Entity resolution (resolve-entities, audit log, canonical_entity_id, ablation) | S3 |
| T2 | S7 Confidence-weighted traversal (graph stage + ablation) | S3 |
| T2 | S8 Citation edges + traversal + MCP get_citations (+ delete/gc coverage) | S2 (reference metadata) |
| T3 | S9 Snippet compression (flagged, judged-evidence gate) | none (uses S1-free eval) |
| T3 | S10 PRISMA screening (stretch, may slip) | S4, S5 |
| T3 | S11 Release wrap: make benchmark refresh, CHANGELOG 0.3.0, version bump, ROADMAP update, epic verification | all |

Sequential landing in one workspace worked well for Wave 1 (the shared
hotspots make parallel PRs collide); stack only when necessary and
restack promptly.

## 6. Kickoff checklist

1. `cd ~/conductor/repos/sci-rag-kit && git checkout main && git pull`
2. `docker compose up -d --wait && uv sync && make check` (expect all
   green, ~191+ tests; if the venv misbehaves see gotcha 1)
3. Read the four docs in section 0
4. Drift-check the technical map (file existence, `git log --oneline
   -5`)
5. Scaffold (section 2.1), then execute (section 2.2) in dependency
   order, then wrap (section 2.4)
