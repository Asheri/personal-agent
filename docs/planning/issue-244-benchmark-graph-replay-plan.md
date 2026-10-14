<!-- Plan doc for issue #244. Excluded from the documentation site (mkdocs
     exclude_docs: planning/); it is a working record, not a user guide. -->

> Authored and approved 2026-09-01.

# Pin published graph counts with a committed benchmark replay artifact

Issue: https://github.com/sustainability-software-lab/sci-rag-kit/issues/244

Delivery unit: one existing issue, one pull request. The workstreams below are
dependency-ordered parts of one atomic change, not independently landable issues.

### Context Alignment

Anchor: issue #244 was filed on 2026-08-31. Against `origin/main` at
`98a40e2`:

- PR #245 landed the interim `GRAPH_COUNT_CAVEAT`, its regression test, and the
  refreshed benchmark numbers after #244 was filed. Issue #244 explicitly assumes
  that interim state, so this is alignment rather than conflicting work.
- Every cited file still exists. No graph replay implementation or competing cache
  issue has landed.
- `domain_digest()` already hashes `domain/domain.yaml` and every prompt.
  Prompt text therefore does not need a second top-level identity field.
- The extractor orders batches by random database document IDs today. Cross-machine
  replay must first use a stable document-content order or exact prompt validation
  will correctly reject the same corpus after re-ingestion.

Classification: Still valid.

Reframed scope: make the synthetic demo benchmark replay one reviewed extraction
artifact across fresh databases, record that fact on the published page, and make
entity and relationship counts exact checks. Do not add a general product cache.

## Context

The published benchmark promised count reproduction within 10 percent. Repeated
credentialed runs over the same recorded inputs produced 83, 72, and 93 entities.
PR #245 made the page honest by calling those counts one stochastic draw. It did
not let another machine reproduce the published graph.

This change records the raw extraction completions for the tracked synthetic CC0
demo corpus, validates every replay input, and passes those completions through the
existing parser and persistence path. The artifact pins model output without
trusting it: replay still runs current JSON parsing, ontology validation, evidence
mapping, and database upserts.

Ordinary product extraction remains unchanged. It is already incremental:
unchanged stamped chunks produce zero model calls. A real corpus moves between
machines through the documented database backup and restore route.

## Approved decisions

1. **Identity:** locate an artifact with corpus digest, effective extraction
   `provider:model`, and domain digest. Validate each recorded call against a
   digest of its exact rendered prompt and generation parameters, plus an explicit
   replay-contract version. Any mismatch is a cache miss and a hard failure in
   strict replay mode.
2. **Storage:** commit the reviewed benchmark artifact under
   `data/demo/graph-replay/`. All ordinary caches stay local and ignored. The
   artifact is a versioned replay fixture, not a local cache.
3. **Modes:** benchmark orchestration has `require`, `refresh`, and `off`.
   `require` makes no model calls and fails on a miss. `refresh` writes a new
   immutable candidate and never overwrites approved evidence. `off` retains
   current live extraction behavior. `graph extract --all` keeps its existing
   merge-oriented meaning.
4. **Scope:** benchmark-only. Add no public `sci-rag` CLI flag, environment
   variable, REST or MCP behavior, database schema, or general user-corpus cache.

## Scope

- Make extraction batch order stable across fresh database IDs.
- Add a benchmark script that records and replays extraction-model completions
  through the existing `LLMClient` and `extract_graph()` seams.
- Define and validate an immutable replay artifact with exact input and output
  provenance.
- Refuse refresh for a non-demo, non-public, or non-pristine target.
- Wire strict replay and deliberate refresh into the benchmark Make targets.
- Carry a graph replay receipt into `scripts/render_benchmarks.py` and the
  generated `docs/benchmarks.md`.
- Remove `GRAPH_COUNT_CAVEAT`; make entity and relationship movement material at
  any nonzero delta while preserving existing tolerances for genuinely stochastic
  metrics.
- Add ADR 0011 with the committed-artifact decision, safety boundary,
  consequences, and reversal conditions.
- Commit one reviewed replay artifact and its new corpus snapshot.
- Prove record-versus-replay equivalence with matched retrieval ablations on the
  same corpus.

## Out of scope

- Caching community summaries, answers, judges, HyDE, reranking, or query routing.
- Pinning judged metrics or changing their tolerance.
- A cache service, object store, database table, Alembic migration, or new
  dependency.
- Product-facing replay flags, configuration, REST endpoints, MCP tools, or
  automatic user-corpus artifact promotion.
- Destructive graph replacement in an existing corpus. Record and strict replay
  require a disposable, pristine graph target.
- Reinterpreting `graph extract --all`; it continues to merge a new extraction
  into existing graph state.

## Architecture and data flow

### Artifact identity

The artifact is JSON with a versioned schema and a stable SHA-256 over its canonical
content. It contains:

- replay schema version and extractor-contract version;
- creation time and source git commit;
- corpus digest over sorted document content hashes;
- effective extraction `provider:model`;
- domain digest;
- batch size and generation parameters;
- an ordered list of exact call-input digests and raw completion strings;
- successful, split, and failed batch counts;
- expected entity and relationship counts;
- a canonical graph-output digest that replaces database IDs with stable document
  content-hash and chunk-index locators.

The call-input digest covers prompt, system text, temperature, JSON mode, maximum
tokens, and call order. The artifact stores no API key and no full prompt. Raw
completions are allowed only because the source is the tracked synthetic CC0 demo.

### Stable batches

`extract_graph()` joins `Document` and orders pending chunks by
`Document.content_hash`, then `Chunk.chunk_index`. Random document and chunk IDs
remain persistence identifiers but no longer determine model-call grouping.

### Replay engine

`scripts/graph_replay.py` owns the benchmark-only interface:

- `refresh` verifies that every document is `source=demo_fixture` with
  `license_class=public`, all target chunks are unstamped, and graph tables are
  empty. It wraps the real extraction client, records each raw completion, applies
  the normal extractor, verifies the resulting canonical graph digest, and
  atomically writes a new content-addressed candidate. Existing artifact paths are
  never replaced.
- `require` loads and fully validates top-level metadata before graph work. It
  does not construct a provider client. A replay `LLMClient` checks every call
  digest, returns the recorded raw completion, rejects missing or unused calls, and
  verifies final counts and graph digest.
- `off` invokes the current live path without reading or writing an artifact.
- No mode falls back from replay to a live provider call. Any failure exits nonzero
  and names whether identity, call sequence, artifact shape, graph precondition, or
  output verification failed. A failed disposable run is discarded, not resumed as
  evidence.

Each successful run writes an ignored graph-provenance receipt for the renderer:
mode, artifact SHA-256, original extraction model, corpus and domain digests,
replayed and extracted call counts, split count, and canonical graph digest.

### Published provenance

`scripts/render_benchmarks.py` requires the graph receipt, checks it against the
retrieval report and corpus counts, and renders one of:

- fully replayed from the named committed artifact;
- freshly extracted into a named candidate artifact.

A mixed or mismatched receipt cannot publish. Entity and relationship counts become
exact comparisons in `--check`; the existing tolerance remains for measurements
that are still stochastic. The page continues to say that judged metrics can move.

## Workstreams

### Workstream 1: Build the fail-closed replay engine  [Tier: T0]

Create the stable batching prerequisite, artifact codec, recording adapter, replay
adapter, and graph-output verification.

**Files:**

- `src/sci_rag/graph/extractor.py` - order extraction batches by document content
  hash and chunk index without changing incremental or `--all` semantics.
- `scripts/graph_replay.py` - add artifact validation, canonical hashing,
  `require|refresh|off` orchestration, recording and replay `LLMClient` adapters,
  pristine-demo checks, and receipt output.
- `tests/unit/test_graph_replay_contract.py` - cover artifact shape, canonical hashes,
  identity drift, immutable writes, mode failures, and zero-provider strict replay.
- `tests/integration/test_graph_replay.py` - prove database ordering,
  record/replay persistence, evidence mapping, and cross-ID equivalence.

**Implementation approach:**

- Write failing unit and integration tests first.
- Reuse `LLMClient.generate()`, `domain_digest()`, `get_session_factory()`,
  `Settings.model_spec_for("extraction")`, and `extract_graph()`.
- Record the raw completion, then let `generate_json()` and
  `parse_extraction()` validate it exactly as a live call is validated.
- Canonicalize graph output by entity names, types, descriptions, aliases, stable
  evidence locators, relationship endpoints, type, evidence, and confidence.
- Refuse refresh unless the database contains only the public `demo_fixture`
  corpus and no pre-existing graph. Refuse require on a non-pristine graph.
- Do not import or construct the real provider client in `require`.
- Do not add a package cache abstraction, new setting, database marker, migration,
  or fallback provider call.

**TDD Contract:**

- Name: `test_record_and_require_replay_survive_fresh_database_ids`
- Tier: integration, because stable SQL ordering and graph persistence are the
  contract.
- File: `tests/integration/test_graph_replay.py`
- Asserts: record on one pristine ingestion, truncate through the disposable test
  fixture, re-ingest in reverse order with new IDs, strict-replay without a real
  model, and obtain identical calls, evidence, counts, and canonical graph digest.
- Red trigger: current batching uses random document IDs and no replay adapter or
  artifact exists.

- Name: `test_require_rejects_identity_drift_without_building_a_model_client`
- Tier: unit.
- File: `tests/unit/test_graph_replay_contract.py`
- Asserts: corpus, model, domain, contract, prompt, or generation-parameter drift
  exits visibly before any provider construction or fallback call.
- Red trigger: no strict replay validator exists.

- Name: `test_refresh_refuses_overwrite_and_nonpristine_or_non_demo_state`
- Tier: integration.
- File: `tests/integration/test_graph_replay.py`
- Asserts: an existing candidate path, stamped chunk, graph row, private license, or
  non-demo source blocks recording without altering approved evidence.
- Red trigger: no immutable refresh path or safety boundary exists.

**Acceptance criteria:**

- [ ] Re-ingestion with new random IDs produces the same ordered extraction prompts.
- [ ] Strict replay makes zero provider calls and consumes every recorded call once.
- [ ] Every approved identity input and exact rendered call is validated.
- [ ] Refresh is atomic, immutable, demo-only, public-only, and pristine-only.
- [ ] The replayed graph matches recorded counts and canonical graph digest.
- [ ] Failures are visible and never fall through to live extraction.

### Workstream 2: Integrate replay with benchmarks and document the decision  [Tier: T1]

Wire the replay engine into the benchmark workflow, published provenance, generated
page checks, project pruning, and ADR.

**Files:**

- `Makefile` - add the approved artifact pointer, make `benchmark` use strict
  replay, and add `benchmark-refresh-graph` for deliberate credentialed recording.
- `scripts/render_benchmarks.py` - require and validate the graph receipt, render
  replay provenance, and make entity and relationship deltas exact failures.
- `tests/unit/test_render_benchmarks.py` - cover receipt agreement, rendered mode,
  and refusal of missing, mixed, or mismatched provenance.
- `tests/unit/test_benchmark_comparison.py` - remove the caveat contract and assert
  zero tolerance for pinned entity and relationship counts.
- `tests/unit/test_benchmark_provenance.py` - prove the renderer cross-checks model,
  domain, corpus, artifact, and output identities.
- `src/sci_rag/scaffold/apply.py` - prune `scripts/graph_replay.py` and
  `benchmark-refresh-graph` when a generated project declines `data/demo/`.
- `tests/unit/test_graph_replay_scaffold.py` - prove demo pruning removes the replay
  artifact, script, target, and all references while demo projects retain them.
- `docs/adr/0011-committed-benchmark-graph-replay.md` - record context, decision,
  consequences, safety rules, and reversal conditions.
- `docs/STYLE.md` - classify ADR 0011 as explanation.
- `mkdocs.yml` - add ADR 0011 to Decision records.

**Implementation approach:**

- Keep `BENCH_GRAPH_REPLAY` as an explicit reviewed path in `Makefile`; do not
  select an artifact by modification time.
- Have refresh print the new candidate path and stop. Updating
  `BENCH_GRAPH_REPLAY` is a reviewed source change.
- Pass a run-specific ignored receipt into `render_benchmarks.py`; require the
  renderer to agree with the eval reports and page counts.
- Replace `GRAPH_COUNT_CAVEAT` with positive provenance text. Keep metric tolerance
  and any still-applicable non-pinned count tolerance.
- Extend the existing demo-pruning target list and `_PRUNED_PHONY`; generated
  projects without the demo must not retain a dead benchmark replay script or target.
- State in ADR 0011 that general caches remain ignored and that committed artifacts
  are limited to reviewed, redistributable benchmark fixtures.
- Reversal conditions: artifact growth becomes material, demo or provider output
  loses redistribution permission, a durable content-addressed artifact service is
  adopted, or measured user demand plus a rights-safe lifecycle justifies a product
  feature.

**TDD Contract:**

- Name: `test_the_renderer_requires_and_names_the_committed_graph_replay`
- Tier: unit.
- File: `tests/unit/test_render_benchmarks.py`
- Asserts: a matching receipt renders artifact identity and replay mode; missing,
  mixed, or mismatched receipts raise `ProvenanceError`.
- Red trigger: the renderer accepts reports with no graph replay receipt.

- Name: `test_pinned_graph_counts_have_zero_tolerance`
- Tier: unit.
- File: `tests/unit/test_benchmark_comparison.py`
- Asserts: any entity or relationship change is material while judged metrics retain
  their declared tolerance.
- Red trigger: current count comparison permits 10 percent movement.

- Name: `test_declining_demo_prunes_graph_replay_surfaces`
- Tier: unit.
- File: `tests/unit/test_graph_replay_scaffold.py`
- Asserts: declining the demo removes the artifact directory, replay script, Make
  targets, PHONY names, and references without disturbing other scripts.
- Red trigger: current pruning knows none of the new replay surfaces.

**Acceptance criteria:**

- [ ] `make benchmark` uses one explicit committed artifact in strict mode.
- [ ] `make benchmark-refresh-graph` produces a new candidate and cannot overwrite
  the approved artifact.
- [ ] The renderer refuses absent, mixed, or inconsistent graph provenance.
- [ ] The page states artifact ID, replay mode, model, and zero live extraction calls.
- [ ] `GRAPH_COUNT_CAVEAT` and its old test are removed.
- [ ] Any entity or relationship delta fails `--check`.
- [ ] Generated projects that decline the demo retain no replay surface.
- [ ] ADR 0011 follows the repository's four-section format and names reversal
  conditions.

### Workstream 3: Capture the reviewed artifact and prove matched behavior  [Tier: T2]

Generate the one credentialed synthetic artifact, compare record and replay on
independent pristine databases, regenerate the benchmark, and preserve receipts.

**Files:**

- `data/demo/graph-replay/<content-addressed-id>.json` - the reviewed extraction
  replay artifact from the synthetic CC0 corpus.
- `data/snapshots/benchmark-<utc-timestamp>.json` - the immutable snapshot for the
  published run.
- `docs/benchmarks.md` - generated page with replay provenance and refreshed,
  evidence-backed numbers.
- `Makefile` - set `BENCH_GRAPH_REPLAY` to the reviewed content-addressed file.

**Implementation approach:**

- Confirm model credentials are explicitly configured before any provider call.
- Name the exact workspace database before use and prove it contains no documents,
  stamped chunks, entities, relationships, or communities. If it is not pristine,
  stop and use another disposable database. Do not delete a development corpus to
  make the precondition true.
- Run `make benchmark-refresh-graph` once against the synthetic demo. Inspect the
  candidate for schema, provenance, absence of credentials or prompt text, source
  boundary, and reasonable size before adding it to Git.
- Save a retrieval ablation from the recorded graph.
- On the independent disposable workspace test database, ingest the same demo and
  run strict replay. Save the second retrieval ablation and compare it with
  `sci-rag eval diff`.
- Run the full benchmark with the approved artifact. Judged answers remain
  stochastic; a material judged move is a finding to explain, not a reason to
  weaken tolerance or force an update.
- Regenerate `docs/benchmarks.md` only from the reviewed reports and commit the new
  snapshot. Keep `eval_results/` ignored; put the two ablation tables and diff
  receipt in the pull request.

**TDD Contract:**

- Name: `recorded_and_replayed_demo_graphs_match_exactly`
- Tier: credentialed verification over two disposable databases, after offline and
  Cloud SQL integration tests prove the behavior.
- File: pull-request eval evidence and generated benchmark artifacts.
- Asserts: identical entity count, relationship count, canonical graph digest, and
  retrieval ablation output for record and strict replay; strict replay reports zero
  live extraction calls.
- Red trigger: the current live extractor produces different graph counts on repeated
  credentialed runs.

**Acceptance criteria:**

- [ ] Only synthetic CC0 `demo_fixture` content appears in the artifact.
- [ ] Artifact metadata matches the committed corpus, model, domain, call inputs,
  contract version, and graph output.
- [ ] Record and replay runs use separately pristine databases and identical corpus
  digests.
- [ ] Record and replay produce identical entities, relationships, graph digest, and
  retrieval ablation results.
- [ ] Strict replay reports zero provider calls.
- [ ] The full benchmark completes with a named snapshot and reviewed source reports.
- [ ] The pull request includes both ablation tables and `sci-rag eval diff` output.
- [ ] No secret, credential, private corpus, local cache, or ignored eval artifact is
  committed.

## Delivery and gating

This is one existing issue and one pull request. No partial workstream lands
independently, so no dark-launch mechanism is required. The public benchmark page,
artifact pointer, replay engine, ADR, and generated artifact become reachable in the
same merge.

## Verification

Run focused offline checks during development:

```bash
uv run pytest tests/unit/test_graph_replay_contract.py \
  tests/unit/test_benchmark_provenance.py \
  tests/unit/test_benchmark_comparison.py \
  tests/unit/test_render_benchmarks.py \
  tests/unit/test_graph_replay_scaffold.py -q
uv run ruff check src tests examples scripts
uv run ruff format --check src tests examples scripts
uv run mypy
```

Run database-backed coverage only through the workspace's disposable Cloud SQL test
database, one invocation at a time:

```bash
"$CONDUCTOR_ROOT_PATH/.conductor/run-cloud-tests.sh" \
  tests/integration/test_graph_replay.py -q
```

Then run repository and documentation parity:

```bash
uv lock --check
make docs
uvx pre-commit run --all-files --show-diff-on-failure
"$CONDUCTOR_ROOT_PATH/.conductor/run-cloud-tests.sh" \
  -q --cov=sci_rag --cov-report=term --cov-fail-under=78
```

The Cloud runner must report database tests as passed. A skip is not evidence. No
`docs-geometry` run is required because no stylesheet changes.

Credentialed verification runs only after the environment is explicitly configured:

1. Record on a named pristine workspace database.
2. Run retrieval ablation A.
3. Strict-replay on the independent disposable workspace test database.
4. Run retrieval ablation B.
5. Run `sci-rag eval diff <A> <B>`; graph counts, graph digest, and retrieval
   results must match exactly.
6. Run two consecutive strict benchmark reproductions from clean state and verify
   identical entity and relationship counts.
7. Run `make benchmark-check` and confirm the published page names replay
   provenance and reports no pinned-count movement.

Review the final diff for artifact size, raw source leakage beyond the CC0 demo,
credential-like fields, generated junk, stale caveat text, and changes outside #244.

## Rollback

- Revert the single pull request.
- Remove the committed artifact and pointer together.
- Restore the honest graph-count caveat if live extraction again supplies published
  counts. Do not hide movement by widening `TOLERANCES`.
- Discard only the named disposable benchmark databases or their contents. Never
  delete or truncate an unrelated development corpus.
- No schema or data migration rollback is required.

## Definition of done

- The four approved decisions are implemented without broadening into a product
  cache.
- Two fresh-database strict replays over the unchanged demo produce identical
  entities and relationships with zero model calls.
- The benchmark page records replay provenance and no longer makes the old
  stochastic graph-count caveat.
- Exact pinned-count checks, offline tests, Cloud SQL integration tests, full CI
  parity, docs build, and matched ablation evidence pass.
- ADR 0011 explains why the artifact is committed, why ordinary caches are not, and
  what would reverse the decision.
- Issue #244 remains the GitHub system of record and closes from the implementing
  pull request.
