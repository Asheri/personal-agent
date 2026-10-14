# Sci RAG Kit documentation route audit

Audit run: `20260829T163016Z-151`
Audited source: `origin/main` at `3d400a005db7b40afede4cc7cceddcd3ef708603`
Initial workspace snapshot: `f520b78cc0781d9cc868483af2a9b04477bb0565`
Tracking epic: [Epic #151: Documentation route audit](https://github.com/sustainability-software-lab/sci-rag-kit/issues/151)
Audit date: 2026-08-29

**Content type:** repository-wide adversarial documentation audit
**Reader need:** determine whether every public setup, tutorial, reference, operations, provider, database, API, benchmark, and deployment route works as documented
**Completion status:** complete
**Verification status:** complete with named blocked routes
**Readiness:** Blocked

This closeout report records the completed source, execution, scientific-integrity, issue, and cleanup checks. All audit-owned runtime resources were removed, the disposable `/tmp` tree was removed, and the redacted evidence pack was retained outside version control for operator review. Pull-request landing evidence is reported separately because a document cannot prove its own merge.

The run began at `f520b78`. During execution, `origin/main` advanced through PR #152 to `3d400a0`. Later phases used current-main archives, and the final static, API, generation, benchmark, issue, and matrix reconciliations target `3d400a0`. Findings captured before that transition retain the initial SHA in their linked reproduction evidence; the intervening change did not invalidate them.

## Executive result

The public documentation is not ready to publish unchanged. Six blocker findings affect credential and local-state disclosure, the released generator path, the generated demo path, database backup safety, and benchmark scientific integrity. Twenty-two major findings affect procedure completion, recovery, configuration fidelity, provider freshness, deployment safety, and generated-project coherence. Three minor findings concern format accuracy and command-pair consistency.

Strong surfaces should be preserved during repair: the current CLI reference is broadly synchronized, strict MkDocs and link checks pass, retrieval fails closed on scope, REST and MCP share the tested service behavior, offline refusal remains honest, Terraform can be operated safely with explicit overrides and saved-plan review, and the benchmark target records enough evidence to expose its own scientific defects.

## Coverage

The extractor produced 144 unique documentation blocks in exact source order:

| Category | Count | Treatment |
| --- | ---: | --- |
| Public executable | 85 | Executed, found defective, or blocked with a named reason |
| Public reference or configuration example | 53 | Interface-checked, but not counted as independent commands |
| Historical planning | 5 | Excluded from the published site |
| Vendored asset | 1 | Excluded from product documentation coverage |

The matrix also contains 48 explicit persona, provider, database, API, generation, infrastructure, and cleanup branches. After reconciling the public clone, owner-only environment-file finding, exact local PostgreSQL wrappers, Persona 03, Persona 06, live Docling, and final cleanup receipts, the strict matrix checker reported 56 PASS, 49 FINDING, 28 BLOCKED, 59 N/A, and zero PENDING across 192 rows. The remaining blocked rows are named below rather than inferred as passes.

### Honest blocked routes

- A real accepted Google AI Studio key was not supplied. Synthetic malformed, rejected, network-failure, retry, continue, no-preflight, and no-TTY branches passed, but they do not prove provider acceptance.
- Live Anthropic and OpenAI-compatible adapter success was blocked by the active Google Cloud project's partner-model API authorization. The retired Grok route and wrong-region diagnostic defects have independent evidence and do not rely on that authorization failure.
- The exact Advanced uv, PostgreSQL 16, Vertex, and local-files persona passed. The venv plus pip persona completed dependency installation and then reproduced F-003 at exact Docker setup. First-time full Pixi materialization and its exact DOI persona remained package-fetch blocked; the Conda AI Studio persona remained credential blocked.
- Direct model-backed drafting commands were not treated as passing when only their documented print-prompt and from-file alternatives ran.
- TestPyPI installation lacked a concrete release version. Interactive Claude MCP registration was not changed because it would mutate operator configuration.
- Production Google Cloud service enablement, Artifact Registry creation, root Terraform apply, Cloud Run jobs, service secrets, and a deployed service smoke test had no isolated authorized production target. The root Terraform plan and the isolated development-database apply and destroy were tested separately.
- Cloud SQL backup creation was not run against the shared development instance. A local custom-format backup and verified restore passed in an isolated database.
- A distinct live `internal_error` REST response was not induced because no safe documented trigger exists without fault injection.
- The full Docling extra and exact replacement-ingest command passed on a one-page control in 179.193 seconds. A separate 13-page scientific PDF remained CPU-active but exceeded the 1,800-second stress bound with zero database mutation, so this report makes no large-document timing claim.
- Audit containers, images, databases, local servers, Terraform resources, ports, and the `/tmp` scratch tree were cleaned. Shared Cloud SQL and sibling proxies were intentionally not stopped.

## Environment

Sensitive values were excluded or redacted in the phase receipts used for this report. No credential values, database URLs, private keys, email addresses, Terraform state values, or local user paths are included here.

| Component | Audited value |
| --- | --- |
| Operating system | macOS 26.5.2, Apple silicon |
| Python | 3.12.8 |
| uv | 0.6.6 |
| pipx | 1.7.1 |
| PostgreSQL client | 16.0 |
| Docker | 28.2.2 |
| Pixi | 0.66.0 |
| Conda | 24.9.2 |
| Terraform | 1.5.7 |
| Google Cloud CLI | 572.0.0 |
| Cloud SQL Auth Proxy | 2.21.0 |
| Claude Code | 2.1.251 |
| Model credentials | Vertex ADC available; Google AI Studio key unavailable |

Database-backed work used disposable audit databases. PostgreSQL 16 with pgvector 0.5.0 and PostgreSQL 18.6 with pgvector 0.8.6 both passed isolated start, extension, status, and stop checks. The separately authorized Terraform route used a unique audit instance, never the shared development instance.

## Dimension status

| Dimension | Status | Evidence |
| --- | --- | --- |
| Technical fidelity and safety | Blocked | Confirmed security, backup, Terraform-default, reindex, and build-context failures |
| Reader completion and reference coverage | Blocked | Flagship package, generated demo, offline tutorial, provider, and deployment routes cannot all reach their stated end states |
| Content type and information architecture | Needs work | Reference synchronization is strong, but conditional credential and offline branches are not consistently separated |
| Examples and code usability | Blocked | Multiple public commands are absent, unsafe, stale, or incomplete as written |
| Language and editorial quality | Needs work | Format and selector inconsistencies remain, with no broad style-check failure |
| Accessibility, inclusion, and scanability | Unverified beyond automated checks | Strict build, page-type/nav checks, rendered breadcrumb tests, advisory scan, and link checks passed. No manual assistive-technology, keyboard-only, contrast, or screen-reader audit was performed. |

## Findings

Commands below are the exact audited invocations or the smallest equivalent source-level probe. Run them from a clean checkout at the audited SHA unless a finding names a generated project. Shell variables such as `$TEMPLATE`, `$ANSWERS`, and `$OUTPUT` must point to caller-owned scratch paths; no command requires a real secret unless its environment explicitly says Vertex ADC was used.

### Blocker

#### F-001: Local-template generation copies ignored workspace state

- **Issue:** [Issue #153: Local-template generation copies ignored workspace state](https://github.com/sustainability-software-lab/sci-rag-kit/issues/153)
- **Severity:** Blocker
- **Class:** Security and local-state disclosure
- **Source:** `docs/cli.md:247`; `src/sci_rag/scaffold/fetch.py:30-42,83-87`
- **Environment:** Clean `git archive` at `3d400a0`; macOS 26.5.2; Python 3.12.8; uv 0.6.6; harmless synthetic `.cloudsql` and `.context` sentinels; no real ignored state read.
- **Exact command:** `uv run sci-rag-new --answers-file "$ANSWERS" --template-path "$TEMPLATE" --output-dir "$OUTPUT"`
- **Documented expectation:** `docs/cli.md:247` defines `--template-path` as “Generate from a local checkout instead of downloading.” The safety contract is that generation transfers distributable template content, not ignored credentials or agent state.
- **Actual result:** Generation exited 0 and copied the synthetic `.cloudsql/password`, `.cloudsql/pgpass`, and `.context/sentinel.txt` files byte-for-byte into the output.
- **Reproduction:** In a clean exported template, run `mkdir -p "$TEMPLATE/.cloudsql" "$TEMPLATE/.context"; printf synthetic > "$TEMPLATE/.cloudsql/password"; printf synthetic > "$TEMPLATE/.context/sentinel.txt"; uv run sci-rag-new --answers-file "$ANSWERS" --template-path "$TEMPLATE" --output-dir "$OUTPUT"; cmp "$TEMPLATE/.cloudsql/password" "$OUTPUT/.cloudsql/password"`.
- **Durable evidence:** [Issue #153 reproduction and safety notes](https://github.com/sustainability-software-lab/sci-rag-kit/issues/153)
- **Repair direction:** Code-side. Define a fail-closed template-copy allowlist or equivalent exclusion boundary and regression-test every sensitive local-state class.

#### F-002: Published package lacks the documented `sci-rag new` command

- **Issue:** [Issue #154: Published package lacks `sci-rag new`](https://github.com/sustainability-software-lab/sci-rag-kit/issues/154)
- **Severity:** Blocker
- **Class:** Broken and stale
- **Source:** `docs/quickstart.md:15,39-42`; `README.md:23-24`; `docs/index.md:48-49`
- **Environment:** Fresh isolated pipx homes on macOS 26.5.2; pipx 1.7.1; PyPI package `sci-rag-kit==0.3.0`; no repository environment reused.
- **Exact command:** `pipx install sci-rag-kit && "$PIPX_BIN_DIR/sci-rag" new`
- **Documented expectation:** `docs/quickstart.md:39-42` shows `pipx install sci-rag-kit` followed by `sci-rag new`, while the same page says “Tested with v0.3.”
- **Actual result:** Installation succeeded, but `sci-rag new` exited 2 with `No such command 'new'`; only the older `sci-rag-new` entry point was released.
- **Reproduction:** Run `export PIPX_HOME="$(mktemp -d)" PIPX_BIN_DIR="$(mktemp -d)"; pipx install sci-rag-kit; "$PIPX_BIN_DIR/sci-rag" new`.
- **Durable evidence:** [Issue #154 clean-pipx reproduction](https://github.com/sustainability-software-lab/sci-rag-kit/issues/154)
- **Repair direction:** Release-side and doc-side. Publish the current generator contract and name its first valid version, or document the released standalone command until then.

#### F-004: Generated demo project has no seed questions for `make demo`

- **Issue:** [Issue #156: Generated demo has no seed questions](https://github.com/sustainability-software-lab/sci-rag-kit/issues/156)
- **Severity:** Blocker
- **Class:** Broken and mismatch
- **Source:** `docs/quickstart.md:149-174`; `Makefile:46-49`; `src/sci_rag/scaffold/apply.py:157-159`
- **Environment:** Fresh current-main Offline `demo_only` generated project; Python 3.12.8; uv 0.6.6; disposable PostgreSQL with pgvector; deterministic local-hash embeddings.
- **Exact command:** `make demo`
- **Documented expectation:** `docs/quickstart.md:153` says the command “ingests five synthetic CC0 documents,” retrieves evidence, and “scores retrieval against the bundled seed questions.”
- **Actual result:** Ingestion and retrieval passed, then evaluation failed because generation had replaced the bundled questions with an empty guided file.
- **Reproduction:** Generate an Offline project with `corpus_source=demo_only`, complete `make setup` against a disposable database, then run `make demo` and observe `No questions found in domain/eval_seed_questions.jsonl.`
- **Durable evidence:** [Issue #156 end-to-end demo reproduction](https://github.com/sustainability-software-lab/sci-rag-kit/issues/156)
- **Repair direction:** Code-side. Preserve the synthetic seed set for demo projects or change the generated demo target so it does not promise impossible scoring.

#### F-006: Backup runbook uses an undefined database URL

- **Issue:** [Issue #158: Backup runbook uses an undefined URL](https://github.com/sustainability-software-lab/sci-rag-kit/issues/158)
- **Severity:** Blocker
- **Class:** Missing-step
- **Source:** `docs/operations.md:94-101`
- **Environment:** Current source on macOS Bash; `SCI_RAG_DATABASE_URL_SYNC` deliberately unset; harmless shell function substituted for `pg_dump`; no socket, credential, or database used.
- **Exact command:** `pg_dump "$SCI_RAG_DATABASE_URL_SYNC" --format=custom --file "sci-rag-$(date +%Y%m%d).dump"`
- **Documented expectation:** The “Backup” procedure at `docs/operations.md:90-101` presents this as the local or self-hosted full knowledge-base backup command before migrations or bulk work.
- **Actual result:** No documented setting or helper defines the variable. In a normal shell the command receives an empty first argument; under `bash -u` it fails before invocation.
- **Reproduction:** Run `unset SCI_RAG_DATABASE_URL_SYNC; pg_dump(){ printf '<%s>\n' "$@"; }; pg_dump "$SCI_RAG_DATABASE_URL_SYNC" --format=custom --file audit.dump` and inspect the empty first argument. Then run the same expansion under `bash -u` to reproduce the unbound-variable failure.
- **Durable evidence:** [Issue #158 safe shell reproduction](https://github.com/sustainability-software-lab/sci-rag-kit/issues/158)
- **Repair direction:** Doc-side. Define and validate a non-empty libpq-compatible connection input, explain shell loading, and use a credential-safe invocation.

#### F-026: Benchmark report selection reverses compressed and uncompressed roles

- **Issue:** [Issue #178: Benchmark report roles are reversed](https://github.com/sustainability-software-lab/sci-rag-kit/issues/178)
- **Severity:** Blocker
- **Class:** Scientific integrity, provenance, and mismatch
- **Source:** `docs/benchmarks.md:71-129`; `Makefile:125-131`
- **Environment:** Clean current-main archive; isolated PostgreSQL; Vertex ADC; five synthetic documents and 34 chunks; full benchmark completed in 656.936 seconds.
- **Exact command:** `make benchmark`
- **Documented expectation:** `docs/benchmarks.md:88-110` says the comparison uses one compressed and one uncompressed run, and that the gate holds only when no judged dimension falls while prompt tokens drop.
- **Actual result:** Timestamp selection swapped the two answer-report roles after calibration touched the older directory. The page reversed quality values, showed a false token comparison, claimed the gate held, and omitted calibration.
- **Reproduction:** Run `make benchmark`; then run `for f in eval_results/*-answers/report.json; do printf '%s ' "$f"; jq -r '.config.compression.enabled // .configuration.compression.enabled' "$f"; done` and compare those roles and directory times with the two paths selected at `Makefile:125-131`.
- **Durable evidence:** [Issue #178 report-role reproduction and measured values](https://github.com/sustainability-software-lab/sci-rag-kit/issues/178)
- **Repair direction:** Code-side, followed by generated-doc repair. Carry validated report paths directly, reject duplicate or reversed roles, and derive prose only from validated report data.

#### F-027: Build contexts admit ignored credentials and local state

- **Issue:** [Issue #179: Build contexts admit local sensitive state](https://github.com/sustainability-software-lab/sci-rag-kit/issues/179)
- **Severity:** Blocker
- **Class:** Security and local-state disclosure
- **Source:** `docs/deploy-gcp.md:68-80`; repository build-context configuration
- **Environment:** Clean current-main archive; Docker 28.2.2; Google Cloud CLI 572.0.0; synthetic `.env`, `.cloudsql`, `.context`, and private-data sentinels only; no real values read.
- **Exact command:** `docker build -f "$AUDIT_DOCKERFILE" -t sci-rag-context-audit .` and `gcloud meta list-files-for-upload .`
- **Documented expectation:** `docs/deploy-gcp.md:74-80` submits the repository root as the build context and says the image packages the kit, `domain/`, and migrations. The safety expectation is that local credentials, agent state, and private corpus files are not uploaded to builders.
- **Actual result:** With no `.dockerignore`, all synthetic sentinels entered Docker context. The Cloud Build upload list also included locally ignored `.context` state because no committed `.gcloudignore` protects it.
- **Reproduction:** In a clean archive, create harmless sentinels under `.env`, `.cloudsql/`, `.context/`, and `data/raw/`; build an audit-only Dockerfile containing `COPY . /audit-context`; then run `gcloud meta list-files-for-upload .` and inspect path names without reading file contents.
- **Durable evidence:** [Issue #179 sentinel and upload-manifest evidence](https://github.com/sustainability-software-lab/sci-rag-kit/issues/179)
- **Repair direction:** Both. Commit restrictive Docker and Cloud Build context files, document the boundary, and add regression tests for sensitive paths.

### Major

#### F-003: Fixed Docker container name blocks a second project

- **Issue:** [Issue #155: Fixed Docker name blocks a second project](https://github.com/sustainability-software-lab/sci-rag-kit/issues/155)
- **Severity:** Major
- **Class:** Broken and friction
- **Source:** `docs/quickstart.md:125-137`; `docker-compose.yml:11`
- **Environment:** Docker 28.2.2; fresh generated Docker project; stopped synthetic sibling container named `sci-rag-db`; no listener on host port 5433.
- **Exact command:** `make setup`
- **Documented expectation:** `docs/quickstart.md:129-137` says `make setup` starts the selected backend, applies every migration, and reaches `Database schema is up to date.`
- **Actual result:** A stopped sibling container with the global name `sci-rag-db` made Compose fail before port handling or migration.
- **Reproduction:** Run `docker create --name sci-rag-db pgvector/pgvector:pg16`; in a fresh generated project run `make setup`; after the check, remove only the synthetic container you created.
- **Durable evidence:** [Issue #155 Docker collision reproduction](https://github.com/sustainability-software-lab/sci-rag-kit/issues/155)
- **Repair direction:** Code-side. Remove the fixed name and use Compose project namespacing or a generated project-specific name; document host-port handling separately.

#### F-005: Campaign checkpoint names a nonexistent report command

- **Issue:** [Issue #157: Campaign checkpoint names a nonexistent command](https://github.com/sustainability-software-lab/sci-rag-kit/issues/157)
- **Severity:** Major
- **Class:** Stale
- **Source:** `docs/campaigns.md:205-210`
- **Environment:** Current source CLI; Python 3.12.8; uv 0.6.6; no campaign data, database, model, or network required.
- **Exact command:** `uv run sci-rag campaign report --name rice-straw`
- **Documented expectation:** The checkpoint at `docs/campaigns.md:205-210` says this command “should reconcile” included, excluded, awaiting-review, and candidate counts.
- **Actual result:** The command exited 2 because the live CLI exposes only `discover`, `build`, `screen`, and `review`.
- **Reproduction:** Run `uv run sci-rag campaign report --name rice-straw`; then run `uv run sci-rag campaign --help` to verify the registered command set.
- **Durable evidence:** [Issue #157 CLI-help reproduction](https://github.com/sustainability-software-lab/sci-rag-kit/issues/157)
- **Repair direction:** Doc-side. Point the checkpoint to supported review output and the generated screening report.

#### F-007: Embedding guidance names a nonexistent plan command

- **Issue:** [Issue #159: Embedding guidance names a nonexistent command](https://github.com/sustainability-software-lab/sci-rag-kit/issues/159)
- **Severity:** Major
- **Class:** Stale
- **Source:** `docs/extend.md:145`; `docs/faq.md:155`
- **Environment:** Current source CLI at `3d400a0`; Python 3.12.8; uv 0.6.6; no database or credential required to resolve command registration.
- **Exact command:** `uv run sci-rag embed plan`
- **Documented expectation:** `docs/extend.md:145` says “`sci-rag embed plan` exists to scope exactly that work.”
- **Actual result:** `embed plan` exited 2; live help exposes the dry-run-by-default route as `embed reindex`.
- **Reproduction:** Run `uv run sci-rag embed --help; uv run sci-rag embed plan`.
- **Durable evidence:** [Issue #159 live-help reproduction](https://github.com/sustainability-software-lab/sci-rag-kit/issues/159)
- **Repair direction:** Doc-side. Use the current non-applying reindex route and preserve the dimension-migration warning.

#### F-008: Full database dump is not protected by an ignore rule

- **Issue:** [Issue #160: Full database dump lacks an ignore rule](https://github.com/sustainability-software-lab/sci-rag-kit/issues/160)
- **Severity:** Major
- **Class:** Missing-step and safety
- **Source:** `docs/operations.md:94-98`; `.gitignore`
- **Environment:** Clean current-main worktree; Git only; no dump created and no database contacted.
- **Exact command:** `git check-ignore -q sci-rag-20991231.dump`
- **Documented expectation:** `docs/operations.md:95-97` writes the whole knowledge-base backup as `sci-rag-$(date +%Y%m%d).dump` in the repository root; a safety backup should not become an ordinary source-control candidate.
- **Actual result:** `git check-ignore` exited 1 because no tracked ignore rule covers the documented filename.
- **Reproduction:** Run `git check-ignore -v sci-rag-20991231.dump; test $? -eq 1` from the repository root. This check creates no dump.
- **Durable evidence:** [Issue #160 ignore-rule reproduction](https://github.com/sustainability-software-lab/sci-rag-kit/issues/160)
- **Repair direction:** Both. Write backups to an ignored location and add a matching template ignore rule.

#### F-010: Standalone Pixi manifest is absent from the generated Docker build

- **Issue:** [Issue #162: Pixi manifest is absent from Docker build](https://github.com/sustainability-software-lab/sci-rag-kit/issues/162)
- **Severity:** Major
- **Class:** Broken
- **Source:** `src/sci_rag/scaffold/manifests.py:143-154`; `src/sci_rag/scaffold/runners.py:213-220`
- **Environment:** Fresh Advanced generation from clean current-main; Pixi 0.66.0 selected with standalone `pixi.toml`; no credential or container build needed to inspect inputs.
- **Exact command:** `uv run sci-rag-new --answers-file "$ANSWERS" --template-path "$TEMPLATE" --output-dir "$OUTPUT"`
- **Documented expectation:** The Advanced generator accepts Pixi plus standalone `pixi.toml` as one project configuration, so its generated container route must install from that selected manifest.
- **Actual result:** Generation wrote `pixi.toml`, but the Dockerfile copied only `pyproject.toml` and `README.md` before `pixi install`.
- **Reproduction:** Set `environment_manager: pixi` and `dependency_file: pixi.toml` in `$ANSWERS`; run the exact generator command; then run `grep -nE 'COPY|pixi install' "$OUTPUT/Dockerfile"` and verify no `pixi.toml` copy precedes installation.
- **Durable evidence:** [Issue #162 generated-project assertions](https://github.com/sustainability-software-lab/sci-rag-kit/issues/162)
- **Repair direction:** Code-side. Copy the selected manifest before dependency installation and test both supported Pixi shapes.

#### F-011: Python 3.11 selection leaves `.python-version` at 3.12

- **Issue:** [Issue #163: Python 3.11 selection leaves a 3.12 pin](https://github.com/sustainability-software-lab/sci-rag-kit/issues/163)
- **Severity:** Major
- **Class:** Mismatch
- **Source:** generated `.python-version`; Python-aware scaffold appliers
- **Environment:** Fresh answers-file generation from current-main; selected runtime Python 3.11; generator ran under Python 3.12.8 and uv 0.6.6.
- **Exact command:** `uv run sci-rag-new --answers-file "$ANSWERS" --template-path "$TEMPLATE" --output-dir "$OUTPUT"`
- **Documented expectation:** The Advanced generator's `python_version: "3.11"` selection is a project-wide runtime choice, and the generated completion contract presents the selected project as coherent.
- **Actual result:** Package metadata, CI, and Docker changed to 3.11 while `.python-version` remained 3.12.
- **Reproduction:** Set `python_version: "3.11"` in `$ANSWERS`; generate; then run `cat "$OUTPUT/.python-version"; grep -RFn '3.11' "$OUTPUT/pyproject.toml" "$OUTPUT/.github/workflows" "$OUTPUT/Dockerfile"`.
- **Durable evidence:** [Issue #163 cross-file pin assertions](https://github.com/sustainability-software-lab/sci-rag-kit/issues/163)
- **Repair direction:** Code-side. Rewrite `.python-version` from the selected answer and assert cross-file pin parity.

#### F-012: Answers-file ontology drafting cannot realize its accepted value

- **Issue:** [Issue #164: Answers-file drafting cannot realize its value](https://github.com/sustainability-software-lab/sci-rag-kit/issues/164)
- **Severity:** Major
- **Class:** Unreachable and ambiguous
- **Source:** `src/sci_rag/cli/new.py:122-170`; `src/sci_rag/scaffold/answers.py:109-111`
- **Environment:** Fresh noninteractive answers-file generation; `ontology: draft_with_llm`; placeholder model configuration; no credential and no model call.
- **Exact command:** `uv run sci-rag-new --answers-file "$ANSWERS" --template-path "$TEMPLATE" --output-dir "$OUTPUT"`
- **Documented expectation:** `docs/cli.md:242` describes an answers file as “for reproducible generation,” so every accepted value must either produce its selected effect or fail validation.
- **Actual result:** `draft_with_llm` was accepted, skipped because answers-file mode is noninteractive, and coerced to `keep_demo_example` with a warning.
- **Reproduction:** Set `ontology: draft_with_llm` in `$ANSWERS`; run the exact generator command; inspect stdout and `"$OUTPUT/domain/domain.yaml"` to see the fallback demo ontology.
- **Durable evidence:** [Issue #164 noninteractive-generation evidence](https://github.com/sustainability-software-lab/sci-rag-kit/issues/164)
- **Repair direction:** Code-side and doc-side decision. Reject the value early, define deterministic noninteractive acceptance, or narrow the published schema.

#### F-013: Apache license choice produces a notice under a verbatim-text contract

- **Issue:** [Issue #165: Apache choice produces a notice](https://github.com/sustainability-software-lab/sci-rag-kit/issues/165)
- **Severity:** Major
- **Class:** Ambiguous and mismatch
- **Source:** `src/sci_rag/scaffold/licenses.py:1-5`; generated Apache `LICENSE`
- **Environment:** Fresh current-main answers-file generation; `open_source_license: Apache-2.0`; offline byte-level inspection only.
- **Exact command:** `uv run sci-rag-new --answers-file "$ANSWERS" --template-path "$TEMPLATE" --output-dir "$OUTPUT"`
- **Documented expectation:** The generator offers a named `Apache-2.0` license-file choice, while `licenses.py:1-5` says its offered license texts are stored verbatim.
- **Actual result:** The Apache selection produced a 19-line attributed notice linking to the license, while the other named choices contained their full offered terms.
- **Reproduction:** Set `open_source_license: Apache-2.0` in `$ANSWERS`; generate; then run `wc -l "$OUTPUT/LICENSE"; sed -n '1,25p' "$OUTPUT/LICENSE"` and compare the artifact with the stated generator contract.
- **Durable evidence:** [Issue #165 generated-license assertions](https://github.com/sustainability-software-lab/sci-rag-kit/issues/165)
- **Repair direction:** Code-side and doc-side decision. Emit full terms or explicitly label and describe the artifact as a notice.

#### F-015: Offline answer refusal waits on model-only stages and recommends the active provider

- **Issue:** [Issue #167: Offline answer refusal is slow and misdirected](https://github.com/sustainability-software-lab/sci-rag-kit/issues/167)
- **Severity:** Major
- **Class:** Friction and mismatch
- **Source:** `docs/quickstart.md:113-121,174-184`; Offline answer path
- **Environment:** Fresh Offline generated project; local-hash embeddings; five demo documents; disposable PostgreSQL; no model credential and no model request.
- **Exact command:** `uv run sci-rag answer "How much rice straw was generated in the Colusa Basin in 2023?"`
- **Documented expectation:** `docs/quickstart.md:184` says Offline mode “reports that no LLM is configured” and does not fabricate an answer; lines 113-121 identify graph and HyDE as unavailable.
- **Actual result:** The honest refusal took 30.88 seconds after graph and HyDE credential errors, then recommended local-hash even though it was already active and cannot generate.
- **Reproduction:** In an ingested Offline demo project, run `uv run sci-rag doctor` to confirm `embedding=local-hash`, then run the exact answer command and time it.
- **Durable evidence:** [Issue #167 offline answer trace](https://github.com/sustainability-software-lab/sci-rag-kit/issues/167)
- **Repair direction:** Code-side. Fail promptly with generation-specific guidance and mark known unavailable model-only stages skipped or disabled.

#### F-016: Default Vertex timeout discards the demo evidence

- **Issue:** [Issue #168: Default Vertex timeout discards demo evidence](https://github.com/sustainability-software-lab/sci-rag-kit/issues/168)
- **Severity:** Major
- **Class:** Friction and mismatch
- **Source:** `docs/quickstart.md:101-111,174-182`; generated Vertex retrieval defaults
- **Environment:** Fresh generated Vertex project; ADC; default `us-central1`; Google embeddings; five ingested synthetic documents; isolated database.
- **Exact command:** `uv run sci-rag answer "How much rice straw was generated in the Colusa Basin in 2023?"`
- **Documented expectation:** `docs/quickstart.md:182` says the credentialed demo answer is approximately 302,000 dry tons and cites the synthetic assessment.
- **Actual result:** Default 30-second vector, graph, and HyDE budgets yielded zero sources and an honest no-evidence refusal. A 60-second control returned the expected evidence.
- **Reproduction:** Run the exact answer command with generated defaults; then run `SCI_RAG_DEEP_STAGE_TIMEOUT_S=60 uv run sci-rag retrieve "How much rice straw was generated in the Colusa Basin in 2023?" --profile deep` against the unchanged corpus and compare stage traces.
- **Durable evidence:** [Issue #168 default and 60-second control](https://github.com/sustainability-software-lab/sci-rag-kit/issues/168)
- **Repair direction:** Both. Budget supported remote latency separately or change the default, and name the exact recovery setting when timeout occurs.

#### F-017: Same-prefix API keys share one rate-limit bucket

- **Issue:** [Issue #169: Same-prefix API keys share a rate bucket](https://github.com/sustainability-software-lab/sci-rag-kit/issues/169)
- **Severity:** Major
- **Class:** Security and correctness
- **Source:** `docs/api.md:13-20,43-55`; `src/sci_rag/server/auth.py:75-95,100-148`
- **Environment:** Loopback REST server on port 18000; isolated audit PostgreSQL; synthetic static keys only; raw keys excluded from logs.
- **Exact command:** `uv run python -c 'from sci_rag.server.auth import StaticKeyBackend; b=StaticKeyBackend.from_json("{\"audit-one\":{},\"audit-two\":{}}"); print(b.authenticate("audit-one").key_id, b.authenticate("audit-two").key_id)'`
- **Documented expectation:** `docs/api.md:50` defines `rate_limited` as exceeding a “per-key limit,” and the configuration example assigns rate limits to individual keys.
- **Actual result:** Distinct tokens sharing their first six characters received the same limiter identity, so an unused low-rate key received 429 on its first live request after other keys used the shared bucket.
- **Reproduction:** Run the exact source probe to see identical `key:audit-...` identities, then configure same-prefix synthetic keys in `SCI_RAG_API_KEYS`, use one key up to the shared limit, and call once with the unused key during the same minute.
- **Durable evidence:** [Issue #169 live REST matrix and source cause](https://github.com/sustainability-software-lab/sci-rag-kit/issues/169)
- **Repair direction:** Code-side. Key the limiter with a stable collision-resistant opaque digest while retaining only short safe labels for display.

#### F-018: Generated uv projects retain an inconsistent lockfile

- **Issue:** [Issue #170: Generated uv lockfile is inconsistent](https://github.com/sustainability-software-lab/sci-rag-kit/issues/170)
- **Severity:** Major
- **Class:** Broken and mismatch
- **Source:** `src/sci_rag/scaffold/apply.py:246-279,876-918`; generated uv projects
- **Environment:** Clean current-main archive; untouched `--defaults` and answers-file uv projects; Python 3.12.8; uv 0.6.6; offline lock validation.
- **Exact command:** `uv lock --check --offline`
- **Documented expectation:** The wizard says it writes a configured project (`docs/quickstart.md:36-42`), and uv-managed generated metadata and its committed lock must agree before installation.
- **Actual result:** Generation rewrote the root package name in `pyproject.toml` but retained `sci-rag-kit` in `uv.lock`; the offline lock check exited 2.
- **Reproduction:** Run `uv run sci-rag new --defaults --template-path "$TEMPLATE" --output-dir "$OUTPUT"`; then run `(cd "$OUTPUT/my-scientific-kb" && uv lock --check --offline)` before editing the generated project.
- **Durable evidence:** [Issue #170 default and answers-file lock checks](https://github.com/sustainability-software-lab/sci-rag-kit/issues/170)
- **Repair direction:** Code-side. Regenerate or coherently rewrite the lock after metadata substitution and gate every uv route on lock consistency.

#### F-019: Public Terraform defaults name internal shared infrastructure

- **Issue:** [Issue #171: Terraform defaults name shared infrastructure](https://github.com/sustainability-software-lab/sci-rag-kit/issues/171)
- **Severity:** Major
- **Class:** Missing-step and safety
- **Source:** `infra/terraform/dev-database/variables.tf:1-17`
- **Environment:** Clean scratch copy at `3d400a0`; Terraform 1.5.7; source inspection only for this reproduction; no unsafe plan or apply.
- **Exact command:** `sed -n '1,17p' infra/terraform/dev-database/variables.tf`
- **Documented expectation:** The development-database guide describes an operator-selected project and deliberate development target; a public module must not silently select maintained internal infrastructure.
- **Actual result:** The public variables defaulted to the internal project and live shared instance name. Safe audited execution required explicit overrides and saved-plan review.
- **Reproduction:** Run the exact source command and inspect the `project_id` and `instance_name` defaults. Do not run `terraform apply` with those defaults.
- **Durable evidence:** [Issue #171 defaults and safe override receipt](https://github.com/sustainability-software-lab/sci-rag-kit/issues/171)
- **Repair direction:** Both. Require project and instance inputs, or use neutral values that cannot select maintained infrastructure; keep plan-review guidance.

#### F-020: The domain tutorial's offline path cannot reach its end state

- **Issue:** [Issue #172: Offline domain tutorial cannot reach its end state](https://github.com/sustainability-software-lab/sci-rag-kit/issues/172)
- **Severity:** Major
- **Class:** Missing-step and unreachable
- **Source:** `docs/bring-your-own-domain.md:8-31,287-385`
- **Environment:** Clean current-main generated Offline project; three harmless synthetic Markdown documents; isolated PostgreSQL; local-hash embeddings; no model credential.
- **Exact command:** `uv run sci-rag graph extract; uv run sci-rag graph communities; uv run sci-rag eval answers; uv run sci-rag answer "What does the synthetic corpus say?"`
- **Documented expectation:** The page says “there is a path” without credentials (`docs/bring-your-own-domain.md:17`) and promises that by the end the reader's concepts are in the graph and their own questions score the result (`lines 8-10`).
- **Actual result:** Drafting, ingest, retrieval, and retrieval evaluation passed, but graph extraction, communities, judged answers, and the final cited answer exited at the credential boundary with no complete offline lane.
- **Reproduction:** Complete the documented `--print-prompt` and `--from-file` drafting route with no credential, ingest the small corpus, then run the exact model-only command sequence from steps 5 through 7.
- **Durable evidence:** [Issue #172 clean offline tutorial route](https://github.com/sustainability-software-lab/sci-rag-kit/issues/172)
- **Repair direction:** Doc-side. Split credentialed and offline checkpoints, label skips explicitly, and name the successful reduced offline outcome.

#### F-022: Resumed campaign build ignores the requested maximum

- **Issue:** [Issue #174: Campaign build ignores its maximum](https://github.com/sustainability-software-lab/sci-rag-kit/issues/174)
- **Severity:** Major
- **Class:** Mismatch, friction, and safety
- **Source:** `docs/campaigns.md:39-102`; `src/sci_rag/cli/main.py:1186-1273`
- **Environment:** Current-main CLI; live OpenAlex and Unpaywall; purpose-limited campaign state; monitored contact address redacted from evidence; no downloads in dry-run.
- **Exact command:** `uv run sci-rag campaign build --topic "rice straw valorization" --name rice-straw --mailto "$CONTACT_EMAIL" --max-results 20 --dry-run`
- **Documented expectation:** The example at `docs/campaigns.md:90-101` sets `--max-results 20` and says the dry run queries Unpaywall “for each DOI,” presenting 20 as the bound for that trial after the 100-result discovery example.
- **Actual result:** The dry run processed all 100 retained candidates, resolved 99, and retried the same 100-candidate scope on exact rerun.
- **Reproduction:** Set `CONTACT_EMAIL` to a monitored address; run the documented discover command with `--max-results 100`; then run the exact build command and inspect its `candidates` row.
- **Durable evidence:** [Issue #174 live campaign counts and retry](https://github.com/sustainability-software-lab/sci-rag-kit/issues/174)
- **Repair direction:** Both. Enforce a deterministic bound across retained candidates and document whether it is lifetime or per-run.

#### F-023: Reindex dimension guard compares settings with themselves

- **Issue:** [Issue #175: Reindex dimension guard misses live schema drift](https://github.com/sustainability-software-lab/sci-rag-kit/issues/175)
- **Severity:** Major
- **Class:** Broken and safety
- **Source:** `docs/troubleshooting.md:207-215`; `src/sci_rag/embed/planner.py:59-68`
- **Environment:** Populated disposable PostgreSQL database with a live `vector(1536)` column and 34 chunks; new process configured with local-hash dimension 999; no apply attempted.
- **Exact command:** `SCI_RAG_EMBEDDING_DIM=999 uv run sci-rag embed reindex --dry-run`
- **Documented expectation:** `docs/troubleshooting.md:215` says cross-dimension changes require a migration and warns, “Do not mix vector dimensions or change `SCI_RAG_EMBEDDING_DIM` on a populated database.”
- **Actual result:** Doctor correctly reported live 1536 versus configured 999, but reindex dry-run exited 0, marked all chunks stale, and recommended `--apply`.
- **Reproduction:** Against the disposable 1536-width database, run `SCI_RAG_EMBEDDING_DIM=999 uv run sci-rag doctor`; then run the exact reindex command. Do not run `--apply`.
- **Durable evidence:** [Issue #175 live-schema mismatch evidence](https://github.com/sustainability-software-lab/sci-rag-kit/issues/175)
- **Repair direction:** Code-side. Compare the selected embedder with live column metadata rather than an import-time constant derived from the same setting.

#### F-024: A malformed graph batch remains stuck across exact retries

- **Issue:** [Issue #176: Malformed graph batch remains stuck](https://github.com/sustainability-software-lab/sci-rag-kit/issues/176)
- **Severity:** Major
- **Class:** Broken and friction
- **Source:** `docs/quickstart.md:186-200`; `src/sci_rag/graph/extractor.py:178-212`
- **Environment:** Clean generated Vertex project; ADC; five synthetic documents and 34 chunks; default extraction model; isolated database.
- **Exact command:** `make demo-cloud`
- **Documented expectation:** `docs/quickstart.md:191-199` says `make demo-cloud` extracts entities and relationships, builds communities, asks a multi-document question, and produces a retrieval report.
- **Actual result:** One ten-chunk JSON parse failure repeated at the same position on exact retry. Reducing the batch to five processed all ten remaining chunks. A separate clean benchmark processed all 34 chunks at the default size, so this is a composition-sensitive failure, not a universal default-size failure.
- **Reproduction:** Run `make demo-cloud`; rerun it unchanged; then run `uv run sci-rag graph extract --batch-size 5 --max-chunks 10`. Preserve the separate clean default-size benchmark as the passing control.
- **Durable evidence:** [Issue #176 retry, split-batch, and default-size control](https://github.com/sustainability-software-lab/sci-rag-kit/issues/176)
- **Repair direction:** Both. Split persistently malformed batches under a bound or document the batch-size recovery while leaving invalid chunks unstamped.

#### F-025: Published benchmark is not reproducible from the documented route

- **Issue:** [Issue #177: Published benchmark is not reproducible](https://github.com/sustainability-software-lab/sci-rag-kit/issues/177)
- **Severity:** Major
- **Class:** Scientific reproducibility and mismatch
- **Source:** `docs/benchmarks.md:8-21,131-145`; `Makefile:115-132`
- **Environment:** Clean current-main archive; isolated PostgreSQL; Vertex ADC; same five synthetic documents and 34 chunks as the published page.
- **Exact command:** `make benchmark`
- **Documented expectation:** `docs/benchmarks.md:8` says the measured page is “regenerated with one command,” and `lines 131-145` identify `make benchmark` as that reproduction route.
- **Actual result:** The full target exited 0 but produced 93 entities, 106 relationships, and 12 communities instead of 83, 79, and 7; retrieval and judged-answer metrics also changed materially.
- **Reproduction:** Run `make benchmark` in a clean archive with an isolated database; then compare the regenerated `docs/benchmarks.md` and report fingerprints with the audited commit using `git diff -- docs/benchmarks.md`.
- **Durable evidence:** [Issue #177 benchmark fingerprints and page diff](https://github.com/sustainability-software-lab/sci-rag-kit/issues/177)
- **Repair direction:** Both. Pin or record every material model and evaluation input, define scientific tolerance, and require a reviewed variance receipt before publishing new numbers.

#### F-028: Pixi and Conda ignore an explicit Docker backend selection

- **Issue:** [Issue #180: Pixi and Conda ignore Docker selection](https://github.com/sustainability-software-lab/sci-rag-kit/issues/180)
- **Severity:** Major
- **Class:** Mismatch, safety, and backend dispatch
- **Source:** `docs/run-postgres.md:26-45,72-84`; `src/sci_rag/scaffold/apply.py:384-422`
- **Environment:** Clean current-main generated Pixi 0.66.0 and Conda 24.9.2 projects; Make dry runs only; no server or database started.
- **Exact command:** `SCI_RAG_DB_BACKEND=docker make -n db-up`
- **Documented expectation:** `docs/run-postgres.md:26-29` says `SCI_RAG_DB_BACKEND` controls which backend `make db-up`, `make db-down`, and `make setup` dispatch to; its table says Pixi and Conda can select Docker.
- **Actual result:** In both managers, `docker` and `local` produced byte-identical recipes that started the trust-auth local helper, while the generated Makefile still declared Docker as default.
- **Reproduction:** In each generated manager project, run `SCI_RAG_DB_BACKEND=docker make -n db-up > docker.txt; SCI_RAG_DB_BACKEND=local make -n db-up > local.txt; cmp docker.txt local.txt`.
- **Durable evidence:** [Issue #180 manager-backend command comparison](https://github.com/sustainability-software-lab/sci-rag-kit/issues/180)
- **Repair direction:** Both. Preserve per-backend dispatch, align declared defaults, and test every retained manager-backend pair.

#### F-029: Provider preflight hides the documented wrong-region repair

- **Issue:** [Issue #181: Provider preflight hides the location fix](https://github.com/sustainability-software-lab/sci-rag-kit/issues/181)
- **Severity:** Major
- **Class:** Recovery mismatch and missing diagnostic
- **Source:** `docs/extend.md:104-120`; `src/sci_rag/scaffold/preflight.py:144-196`
- **Environment:** Clean current-main provider copy; Python 3.12.8; deterministic production failure mapper; representative sanitized provider messages; live Anthropic path separately blocked by project authorization.
- **Exact command:** `uv run python -c 'from sci_rag.scaffold.preflight import _failure_result; print(_failure_result(RuntimeError("400 model is not servable in region us-central1"), vertex=True)); print(_failure_result(RuntimeError("404 model not found in location us-central1"), vertex=True))'`
- **Documented expectation:** `docs/extend.md:116-120` says partner models require `SCI_RAG_GCP_LOCATION=global` and that `sci-rag doctor --probe` catches the named 400 and 404 failures before a pipeline run.
- **Actual result:** Both error forms mapped to generic credential advice that named neither `SCI_RAG_GCP_LOCATION` nor `global`.
- **Reproduction:** Run the exact mapper command and inspect each returned `detail` and `fix`; do not treat an earlier API-disabled response as a wrong-region result.
- **Durable evidence:** [Issue #181 deterministic diagnostic evidence](https://github.com/sustainability-software-lab/sci-rag-kit/issues/181)
- **Repair direction:** Both. Classify location failures before generic credentials, keep authorization distinct, and align the guide with tested recovery text.

#### F-030: Documented Grok 4.1 Fast provider route is retired

- **Issue:** [Issue #182: Documented Grok route is retired](https://github.com/sustainability-software-lab/sci-rag-kit/issues/182)
- **Severity:** Major
- **Class:** Stale and unreachable
- **Source:** `.env.example:49-65`; `docs/extend.md:104-120`; current Google Cloud partner-model lifecycle
- **Environment:** Clean current-main OpenAI-extra copy; `uv sync --extra openai`; Vertex ADC with `global`; live call blocked by project API authorization before model dispatch; retirement confirmed independently from current official lifecycle sources.
- **Exact command:** `SCI_RAG_GCP_LOCATION=global SCI_RAG_LLM_MODEL=openai-compatible:xai/grok-4.1-fast-non-reasoning uv run sci-rag doctor --probe`
- **Documented expectation:** `.env.example:56-65` gives this exact worked model and says Grok works from `global`; `docs/extend.md:114-120` presents Grok 4.1 as the publisher-ID example reachable there.
- **Actual result:** Google shut down both Grok 4.1 Fast identifiers on 2026-08-20 and documents HTTP 400 for later requests. The local 403 authorization gate is not used as retirement evidence.
- **Reproduction:** Run `uv sync --extra openai`, then the exact probe in an authorized audit project; independently compare the identifier with the [Grok 4.1 Fast model card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/grok/grok-4-1-fast) and [Google Cloud release notes](https://docs.cloud.google.com/release-notes).
- **Durable evidence:** [Issue #182 lifecycle sources and environment limitation](https://github.com/sustainability-software-lab/sci-rag-kit/issues/182)
- **Repair direction:** Doc-side plus automated freshness testing. Use a currently served adapter-compatible model, date partner examples, and continuously check lifecycle status.

#### F-031: Clone setup creates a world-readable credential file

- **Issue:** [Issue #183: Clone setup creates a world-readable `.env`](https://github.com/sustainability-software-lab/sci-rag-kit/issues/183)
- **Severity:** Major
- **Class:** Missing step and local credential disclosure
- **Source:** `docs/quickstart.md:83-89`; clone setup path
- **Environment:** Clean public source archive; normal audit umask `0022`; public `.env.example` only; no credential value written.
- **Exact command:** `cp .env.example .env`
- **Documented expectation:** `docs/quickstart.md:83-89` says the wizard created `.env` with owner-only mode `0600`, then directs clone and template users to create the same local environment file with `cp`.
- **Actual result:** The exact copy exited 0 and created `.env` with mode `0644`.
- **Reproduction:** In a clean scratch clone, run `umask 0022; cp .env.example .env; stat -f '%Lp' .env` on macOS, or `stat -c '%a' .env` on Linux, before adding any value.
- **Durable evidence:** [Issue #183 mode reproduction](https://github.com/sustainability-software-lab/sci-rag-kit/issues/183)
- **Repair direction:** Doc-side and test-side. Add a portable owner-only mode step and execute the clone snippet in regression coverage.

### Minor

#### F-009: Backup prose says plain format while the command uses custom format

- **Issue:** [Issue #161: Backup prose names the wrong format](https://github.com/sustainability-software-lab/sci-rag-kit/issues/161)
- **Severity:** Minor
- **Class:** Mismatch
- **Source:** `docs/operations.md:95-96,132-135`
- **Environment:** Source-only inspection at `3d400a0`; no database, credential, or file mutation.
- **Exact command:** `sed -n '95,96p;132,135p' docs/operations.md`
- **Documented expectation:** The comment at `docs/operations.md:95` calls the adjacent artifact a “Plain-format dump,” while the same procedure must accurately identify what readers create and restore.
- **Actual result:** The command uses `--format=custom`, and the restore drill uses `pg_restore`, which is the custom/archive workflow rather than a plain SQL dump.
- **Reproduction:** Run the exact source command and compare the comment, dump flag, and restore utility.
- **Durable evidence:** [Issue #161 direct source comparison](https://github.com/sustainability-software-lab/sci-rag-kit/issues/161)
- **Repair direction:** Doc-side. Call it a custom-format archive or change dump and restore together.

#### F-014: Generated docs make an unusable no-bare-double-brace claim

- **Issue:** [Issue #166: Generated docs make an unusable brace claim](https://github.com/sustainability-software-lab/sci-rag-kit/issues/166)
- **Severity:** Minor
- **Class:** Mismatch and ambiguous
- **Source:** `docs/faq.md:164-166`; `docs/citation.md:16`; ADR 0004 and ADR 0007
- **Environment:** Fresh current-main generated projects from the 28-case offline sweep; source-token scan only.
- **Exact command:** `grep -RFn '{{' "$OUTPUT/docs" "$OUTPUT/domain"`
- **Documented expectation:** Generated FAQ and ADR prose state that no bare `{{` token should remain in generated output, intending to guard unresolved scaffold placeholders.
- **Actual result:** The raw invariant rejected its own wording plus intentional BibTeX and Cookiecutter examples, so it could not distinguish leakage from valid syntax.
- **Reproduction:** Generate a clean project, run the exact scan, and inspect each match in FAQ, citation, and ADR pages rather than treating every hit as an unresolved placeholder.
- **Durable evidence:** [Issue #166 first-pass scan adjudication](https://github.com/sustainability-software-lab/sci-rag-kit/issues/166)
- **Repair direction:** Both. Define unresolved placeholder syntax precisely and enforce that semantic invariant instead of a context-free token ban.

#### F-021: Drafting example omits a selector it says to repeat

- **Issue:** [Issue #173: Drafting pair omits a repeated selector](https://github.com/sustainability-software-lab/sci-rag-kit/issues/173)
- **Severity:** Minor
- **Class:** Mismatch and ambiguity
- **Source:** `docs/llm-assisted-setup.md:54-75`
- **Environment:** Clean current-main Offline project; synthetic corpus; validated saved reply; no model call.
- **Exact command:** `uv run sci-rag draft questions --count 10 --print-prompt > prompt.txt; uv run sci-rag draft questions --from-file reply.json`
- **Documented expectation:** `docs/llm-assisted-setup.md:71-74` says to pass the same `--count` and `--folder` values to `--print-prompt` and `--from-file`.
- **Actual result:** The example passes `--count 10` only to the first command and succeeds solely because ten is currently the default.
- **Reproduction:** Save a valid reply as `reply.json`, run the exact pair, then compare the two argument lists with the invariant directly below the example.
- **Durable evidence:** [Issue #173 paired-command evidence](https://github.com/sustainability-software-lab/sci-rag-kit/issues/173)
- **Repair direction:** Doc-side. Repeat the selector on the second command and regression-test selector parity in canonical pairs.

## Verification and test receipts

- **Static conformance:** 45 CLI help nodes plus standalone generator help passed. The audit compared 413 CLI references and 82 Make references. STYLE/nav parity covered 44 published pages. Focused documentation tests passed 86 tests. Strict MkDocs and generated-reference freshness passed.
- **Links:** 283 internal links had zero errors. External Markdown checking found zero errors among 99 unique destinations after documented exclusions. The built-site checker classified 4,641 link occurrences: 211 were checked successfully, 4 were redirects, and 4,430 were excluded by its URL model; it reported zero checked-link errors. This does not establish availability for excluded destinations.
- **Generator sweep:** 28 real offline generations completed; final coherence was 24 pass, 2 fail, and 2 ambiguous. The focused generator baseline passed 141 tests.
- **Guide and drafting routes:** clean default and answers-file projects, real-PTY advanced init, print-prompt/from-file/apply/dry-run variants, three-document BYO ingest, retrieval, retrieval evaluation, and server health were exercised. Rights remained unknown and drafted tags remained intact.
- **Preflight and managers:** malformed, rejected, network, retry, continue, environment reuse, no-preflight, and no-TTY branches passed with zero synthetic-key leaks. Focused tests passed 123 tests. PostgreSQL 16 and 18 isolated backends passed. The exact Advanced uv, PostgreSQL 16, Vertex, and local-files persona passed through ingest, doctor, lock check, shutdown, and port verification. The venv plus pip persona installed fully before reproducing F-003 at Docker setup.
- **Troubleshooting and configuration:** 55 troubleshooting tests and 32 tuning tests passed. Live probes covered unreachable Docker, local, and Cloud backends; missing credentials; offline mode; empty and narrow retrieval; pypdf fallback; a successful installed-Docling replacement ingest; server rejection; and dimension mismatch. The separate 13-page Docling stress input timed out at 1,800.797 seconds without database mutation.
- **Campaigns and operations:** live topic and DOI discovery, bounded build, screening, real-PTY review, manifest ingest, snapshot, enrichment dry-run, citation dry-run/apply, restore digest, license report, JSONL/Parquet/scoped export, one-document delete, graph GC, entity resolution, retrieval diff, and profile JSON were exercised in disposable databases.
- **API surface:** The plan inventoried six REST endpoints, while current `docs/api.md` and live OpenAPI expose seven route patterns because document detail (`GET /v1/documents/{document_id}`) is distinct from document listing. All seven current routes, four scopes, both answer modes to their expected offline boundary, nine documented error rows, eight MCP tools, two MCP resources, Python API, and pinned Python and TypeScript generated clients were exercised. One distinct `internal_error` code remained uninduced.
- **Providers:** both extras installed and 50 focused provider tests passed with one skip. Global provider success remained authorization-blocked. Wrong-location mapping was reproduced deterministically, and current official lifecycle sources verified the retired example.
- **Terraform:** root fmt, backendless init, validate, and create-only plan passed. The isolated development module completed reviewed plan, apply, output-schema inspection, minimal connectivity, reviewed destroy, empty state, and absence checks. Shared development infrastructure remained running.
- **Benchmark:** the full `make benchmark` target completed in 656.936 seconds. All reports, fingerprints, generated page, and 121-line comparison diff were retained. Completion exposed the reproducibility and report-role failures; it does not validate the published metrics.
- **Epic reconciliation:** the report contains 31 unique findings, F-001 through F-031, mapped to 31 unique open issues, #153 through #183. A live 100-item sub-issue query confirmed all 31 are native children of epic #151.
- **Matrix validation:** 144 unique documentation IDs matched extractor order, every non-executable classification was N/A, every finding row named an issue identifier, and the final strict checker reported 56 PASS, 49 FINDING, 28 BLOCKED, 59 N/A, and zero PENDING.

## Evidence archive

Finding-specific evidence is preserved in the descriptive GitHub issue links in F-001 through F-031. Those issue bodies contain the redacted reproduction, environment, actual result, and acceptance criteria and do not depend on the disposable scratch tree.

The local redacted closeout pack is indexed by `.context/docs-audit/evidence/README.md`. `.context/docs-audit/evidence/findings/evidence-map.json` maps every F ID to its phase summary, and `.context/docs-audit/evidence/SHA256SUMS` authenticates the retained pack as described by its README. No disposable scratch path is a post-cleanup evidence dependency.

The command ledgers recorded working directory, duration, exit code, and timeout state during the audit. Persisted provider, Terraform, campaign, manager, API, and operations summaries used synthetic or redacted values. Scientific benchmark issue evidence records the source SHA, corpus fingerprint, report configuration, and measured diff.

## Cleanup status

Verified final cleanup:

- API, MCP, BYO, and troubleshooting servers were stopped and their audit ports were free.
- Isolated PostgreSQL 16 and 18 servers were stopped.
- Benchmark, operations, guide, campaign, Vertex, restore, and Docling databases created by their phases were removed; no shared development corpus was used for destructive tests.
- The Terraform audit proxy was stopped, its state was emptied, its audit instance and secret were absent, and the shared development instance remained `RUNNABLE`.
- Benchmark processes ended and the benchmark database was absent.
- Provider processes were absent, provider artifacts passed the final redaction scan, and the provider audit port was free.
- The audit container, its Compose network and named volume, and all four audit image tags were removed. Ports 5433, 55433, 55435, 55436, 55437, 18000, and 18002 were free.
- The workspace `.env` retained mode `0600`, size 4,647 bytes, and its exact baseline SHA-256. The workspace proxy PID 74792 remained live and the shared Cloud SQL instance remained `RUNNABLE`.
- Baseline proxy PID 56516 had ended through concurrent external drift, while a new proxy PID 34536 appeared after the audit started. No audit command targeted a proxy, and workspace and sibling Cloud SQL proxies were not stopped or paused.
- No audit SQL instance, audit secret, Terraform state, or `demo-corpus` MCP registration remained. The sibling Docker containers retained their observed states.
- The exact audit run tree was removed from `/tmp` and moved to Trash for recoverability after its redacted summaries were retained in `.context/docs-audit/evidence/`.

## Repository delivery boundary

This report is the sole intended tracked output of the audit. Its pull request, required-check results, merge SHA, epic closure, and base-branch ancestry are repository-delivery receipts and are intentionally verified outside this self-referential document.

## Checks not run or not completed

- Real accepted Google AI Studio generation and preflight.
- Successful live Anthropic and OpenAI-compatible generation under an authorized partner-model project.
- Production Google Cloud deployment and live Cloud Run acceptance.
- Cloud SQL backup creation on a user-selected nonshared instance.
- Interactive mutation of a user's Claude MCP registration.
- Full first-time Python dependency materialization for the Pixi and Conda personas.
- Completion of the separate 13-page Docling stress input inside 30 minutes; the installed one-page replacement-ingest control passed.
- A safely induced distinct REST internal error.

## Preserve during revision

- Keep offline refusal explicit and evidence-honest.
- Keep unknown rights and drafted evaluation tags visible until a person resolves them.
- Keep retrieval scope enforcement before ranking and community exclusion for scoped requests.
- Keep REST and MCP behavior behind the shared service facade.
- Keep saved-plan review, unique audit targeting, output-schema-only inspection, and explicit destroy in Terraform procedures.
- Keep benchmark corpus fingerprints, source SHA, report roles, and variance receipts first-class rather than hand-editing the published page.
