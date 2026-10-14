# Plan: sci-rag-kit v0.2+ roadmap. Making the template industry-leading and scientific-community-leading

> Committed 2026-08-27 as the canonical Wave 1 execution plan. Naming correction applied: the flagship LBL domain is **BioCirV** (the original draft said "BioServ"). Waves 2-3 are roadmap-grade and get their own planning passes.

> Supersedes the v0.1 build plan (executed 2026-08-26; repo live at github.com/sustainability-software-lab/sci-rag-kit, v0.1.0a0 released, CI green, disclosure filed). This plan is the product of a three-stream research pass: an internal gap analysis of the repo, a web survey of the GraphRAG/advanced-RAG landscape, and a web survey of scientific RAG systems, evaluation practice, and community-leadership playbooks (80+ primary sources).

## Context

sci-rag-kit v0.1 is a complete, verified GraphRAG template, but "complete" is not "leading." The field moved fast through 2025-2026 and the research shows exactly where the bar sits:

- **The competitive opening is real.** Microsoft GraphRAG (35.7k stars) is in maintenance mode. LightRAG (39.2k stars) is the active general-purpose leader (incremental insert/delete, dual-level retrieval, Postgres backend option). PaperQA2 (9.1k) owns agentic scientific literature QA. Nobody owns the position we are built for: the opinionated, evaluated, Postgres-native TEMPLATE that a scientific group specializes for their domain, with governance-grade evaluation and campaign-scale corpus tooling. That is the position to claim.
- **Our own methodology doc makes promises the code has not kept yet.** The reranker seam is unfilled; embedding version stamping has no re-embed command acting on it; entity aliases and relationship confidence are stored but never used; communities have a level column but only level 0.
- **Scientific users have needs generic frameworks ignore**, and the research names them: citation traversal and reference-graph retrieval (PaperQA2), retraction awareness (Crossref Retraction Watch), campaign corpus building from scholarly APIs (OpenAlex/Crossref/Unpaywall), PRISMA-aligned LLM screening, citation-faithfulness metrics (ALCE) with kappa-calibrated judges, and corpus versioning for reproducibility.
- **Evidence discipline matters:** benchmarks show graph layers pay off mainly on multi-hop questions (~10-15% of typical query mix); the honest leading position is adaptive routing plus published ablations, not graph-everything. Several hyped techniques are explicitly not worth adopting (RAPTOR, agentic loops on every query, contextual-retrieval's 100x indexing overhead, Neo4j migration).

Intended outcome: a 3-release technical roadmap plus a community-leadership program that together make sci-rag-kit the default answer to "we need a RAG over our scientific field's literature," with the BioCirV/UW SSEC collaboration as flagship first users and PISCES improvements flowing both directions.

## Research findings (consolidated, with the decisions they drive)

### From the internal gap analysis
Highest-severity gaps, in order: (1) no cross-encoder reranker despite the documented seam; (2) eval harness lacks judge calibration vs humans, confidence intervals, and a report-diff command, which caps its citability; (3) no public benchmark numbers against alternatives; (4) corpus lifecycle absent (no delete/update, no orphaned-entity GC, no snapshots, no re-embed CLI, no backup runbook); (5) graph-quality features dormant (aliases, confidence, hierarchy); (6) metadata filters stop at license+source (year/author/DOI unused); (7) no bulk acquisition path from DOI lists or topic queries; (8) formats limited to pdf/md/txt; (9) no observability; (10) single-corpus per deployment. Ten strengths were flagged as non-negotiable to preserve: the blind two-pass judge, scope-before-ranking, one-database design, content-hash dedup, embedding version stamping, ablation-first tuning, structure-aware chunking, graceful degradation, REST+MCP behind one service, and the lean dependency footprint.

### From the GraphRAG landscape survey
Transferable with evidence: LightRAG-style incremental patching (per-document extraction cache enabling cheap update/delete); LazyGraphRAG's lesson that community summaries should be cached and regenerated lazily on graph change rather than eagerly rebuilt; Graphiti/Zep bi-temporal edge validity for evolving scientific knowledge; cross-encoder reranking as table stakes; query decomposition for multi-hop (5-15% recall lift); adaptive routing (enable graph/HyDE conditionally) as the honest default given graph's multi-hop-only advantage; pgvector halfvec/iterative-scan and ParadeDB BM25 as available Postgres upgrades. Anti-recommendations adopted: no RAPTOR, no per-query agentic loops by default, no Neo4j, no Anthropic-style contextual embedding at index time (our breadcrumb prepending already captures most of the value at zero cost), recursive CTEs fine at template scale with a documented escape hatch.

### From the scientific-RAG and community survey
Scientific differentiators to adopt: the PaperQA2 evidence pattern (per-chunk relevance-scored contextual summarization before answering; metadata enrichment incl. retraction status; citation traversal with references as first-class graph edges); the campaign pipeline (OpenAlex/Crossref/Unpaywall topic-to-corpus with license metadata and Retraction Watch); L-PRISMA-aligned LLM screening with human gates; ALCE-style citation precision/recall metrics plus Cohen's-kappa judge calibration (what makes an eval harness citable in a methods section); multi-corpus routing over our existing corpus-manifest seam. Community-leadership playbook: transparent comparison content, a public benchmark page, Zenodo DOI minting, a JOSS paper (we already meet its infrastructure bar), pyOpenSci review, HF Spaces demo, notebook gallery with 2-3 worked domains, ROADMAP/VERSIONING/governance docs, curated good-first-issues, and Discussions.

## Synthesis decisions

1. **Three waves, credibility first.** Wave 1 (v0.2 "Credibility") closes the gaps that gate trust: the reranker, eval statistics and calibration, corpus lifecycle, and a public benchmark, plus the launch-package docs, so the repo flips public at full strength. Wave 2 (v0.3 "Campaigns") builds the scientific differentiators. Wave 3 (v0.4+ "Scale and intelligence") adopts the landscape's proven scale patterns. Wave 1 is specified to execution detail and is what gets built first on approval; waves 2-3 are roadmap-grade and will each get their own planning pass.
2. **Ablation-first stays the house rule.** Every retrieval-affecting feature ships with an ablation config and lands only with before/after evidence on the demo corpus; the benchmark page publishes those tables.
3. **Provider-agnostic reranker.** The design agents proposed Vertex Ranking as the default; overruled for a template: a `Reranker` interface with two adapters (LLM-rerank via the existing `LLMClient`, and an optional local cross-encoder extra), plus a Vertex Ranking adapter documented for GCP users. Off by default until the corpus's own ablation justifies it; the shipped demo benchmark includes the evidence.
4. **Calibration is a workflow, not a one-off study.** Ship `sci-rag eval calibrate` (human labels in, Cohen's kappa out, reported alongside every answers eval). Seed it ourselves with ~30 labeled demo answers; BioCirV expert labels replace them later. No invented kappa targets in docs; report what we measure.
5. **Adaptive routing is the honest default posture, presented as evidence.** Implement a cheap query classifier that enables graph/HyDE conditionally, but keep `deep` as the explicit always-everything profile; publish the ablation that justifies routing rather than asserting it.
6. **Corrections to agent outputs adopted here:** no fabricated performance promises (agents' "nDCG >= 0.85", "700x" style numbers dropped; we publish measured numbers only); UW SSEC is the University of Washington Scientific Software Engineering Center and their workstreams (eval platform, OAuth, federation) get presented in ROADMAP.md as collaboration seams without dates we don't control; BioCirV is the LBL flagship domain. CITATION.cff and attribution were removed at the user's request pending wording; the credibility ladder (Zenodo DOI, JOSS) REQUIRES restoring them, so that is flagged as a user decision at launch, not something I re-add unilaterally.


## GitHub scaffolding (backfilled 2026-08-27)

Milestone: [v0.2 Credibility](https://github.com/sustainability-software-lab/sci-rag-kit/milestone/1). Epic: [#5](https://github.com/sustainability-software-lab/sci-rag-kit/issues/5).

| Item | Issue |
|------|-------|
| 1 Reranker stage | #6 |
| 2 Eval statistics | #7 |
| 3 Report diff CLI | #8 |
| 4 Judge calibration | #9 |
| 5 Re-embed CLI | #10 |
| 6 Delete + graph GC | #11 |
| 7 Snapshot + runbook | #12 |
| 8 Adaptive routing | #13 |
| 9 Benchmark page | #14 |
| Launch docs | #15 |
| Community mechanics | #16 |

## WAVE 1 (execute first): v0.2 "Credibility" + launch package

### Technical items (each lands with tests, docs, and its ablation/eval evidence)

**1. Reranker stage** (M). New `src/sci_rag/retrieve/rerank.py`: `Reranker` interface; `LLMReranker` (default adapter, uses existing `LLMClient` to score top-N fused candidates, JSON mode, thinking off); optional `LocalCrossEncoder` behind a `rerank` extra (sentence-transformers); `VertexRanker` documented for GCP. Orchestrator calls it post-fusion over a configurable pool (default 20) with its own timeout and degraded-status trace ("rerank" appears in traces like any stage). `domain.yaml retrieval.reranker` block; `include_rerank` override on `Retriever.retrieve()` and `/v1/query`. Add nDCG@k to `evals/retrieval_eval.py` metrics; new ablation configs `with_rerank`/`no_rerank`. No schema change.

**2. Eval statistics** (S/M). In `evals/retrieval_eval.py` + `report.py`: bootstrap 95% CIs for hit@k/MRR/nDCG, small-n warning (n<10), paired comparison support. Reports state n and CI everywhere a mean appears.

**3. Report diff CLI** (S). New `evals/diff.py` + `sci-rag eval diff a/report.json b/report.json`: per-question rank deltas, metric deltas with paired significance test, markdown table output. Closes the documented improvement loop.

**4. Judge calibration workflow** (M). New `evals/calibration.py` + `sci-rag eval calibrate --labels labels.jsonl`: human labels (question_id, dimension scores) vs judge scores → Cohen's kappa per dimension + agreement matrix, appended to answers reports. Ship a `docs/evaluation.md` section on running a calibration and a seeded demo-corpus label set (~30 answers, labeled by us, marked as non-expert seed).

**5. Re-embed CLI** (S/M). New `embed/planner.py` + `sci-rag embed reindex [--dry-run|--apply]`: select chunks (and community summaries) whose `embedding_version` differs from the current embedder version, batch re-embed with progress and per-batch commit, refuse cross-dimension reindex (that's a migration). Mirrors PISCES's reembed-planner.

**6. Document delete + graph GC** (M). `sci-rag corpus delete <doc-id ...>` (cascade chunks via existing FK; scrub the doc's ids from `KgEntity.document_ids/chunk_ids` arrays; drop relationships whose evidence chunk belonged to it) and `sci-rag graph gc [--dry-run]` (remove evidence-less entities, dangling relationships, then rebuild communities). Migration 0002 if any supporting index is needed. Regression tests: deleted docs unreachable through every layer including graph traversal.

**7. Corpus snapshot + backup runbook** (S). `sci-rag corpus snapshot` writes a named fingerprint manifest (counts, content hashes, embedding versions, git commit); `docs/operations.md` gains a backup/restore runbook (pg_dump/Cloud SQL snapshots, restore drill, Parquet export note). Eval reports can reference a snapshot name.

**8. Adaptive routing** (M). New `retrieve/router.py`: cheap classifier (keyword heuristics from domain.yaml query classes + optional LLM fallback) mapping query → profile/layer set; new `auto` profile (default stays unchanged in v0.2; `auto` becomes default only if the published ablation supports it). `--explain-routing` on the CLI. Ablation: auto vs deep vs interactive on the demo set.

**9. Public benchmark page** (M). `docs/benchmarks.md`: demo-corpus results across all ablation configs incl. rerank and routing, with CIs, corpus fingerprint, commit, model ids, reproduction command (`make benchmark`). This page is the credibility anchor for launch and the JOSS paper.

### Launch package (docs + community mechanics, ready for flip-public day)

- `docs/ROADMAP.md` (waves 2-3 summarized; UW SSEC workstreams as collaboration seams: eval platform, OAuth on the AuthBackend seam, federation on corpus-manifest; BioCirV flagship domain), `docs/VERSIONING.md` (semver, 0.x rules, 1.0 criteria), `docs/GOVERNANCE.md` (lite: maintainers/reviewers/contributors, ADR + RFC-in-Discussions process).
- `docs/choosing-sci-rag-kit.md`: honest comparison vs Microsoft GraphRAG (maintenance mode), LightRAG, PaperQA2, LlamaIndex/Neo4j; axes: template-vs-library, evaluation rigor, license governance, serving (MCP), ops footprint; explicit concessions (no agentic loop, Postgres-only, early stage).
- Examples program start: convert bring-your-own-domain into a runnable notebook; `ADOPTERS.md` stub; second worked domain deferred to Wave 2 (BioCirV case study is the flagship and depends on their corpus).
- Community mechanics: enable Discussions (5 categories), seed 10 good-first-issues from the gap list (HTML parser, manifest linter, export CLI, OpenAPI client generation, metadata filters, ontology suggester, license audit report, question-to-seed converter, performance profiler, eval-report HTML view), label + write acceptance criteria for each.
- Launch-gated items requiring user decisions, listed in ROADMAP but not executed unilaterally: restore CITATION.cff/attribution wording, Zenodo DOI minting, JOSS submission, PyPI publication, HF Spaces demo.

## WAVE 2: v0.3 "Campaigns" (the scientific differentiator release)

- **Campaign builder**: new `src/sci_rag/campaigns/` package. `sci-rag campaign build --topic|--doi-file` → OpenAlex/Crossref query → DOI list → Unpaywall OA resolution → downloads legal PDFs → writes a corpus manifest with license classes derived from OA status (fail-closed to `unknown`), with `--dry-run` showing counts and license distribution first. Rate-limited, resumable.
- **Retraction and metadata enrichment**: Crossref (incl. Retraction Watch data) + optional Semantic Scholar enrichment into `Document.extra` (retraction status, citation count, journal); `RetrievalScope.exclude_retracted` (default ON for answering) enforced in every layer; doctor warns when retracted documents are present.
- **Citation-graph edges**: extract references (Crossref metadata first, GROBID/Docling references as fallback) into `CITES` relationships between documents present in the corpus; citation traversal joins the graph stage; MCP gains `get_citations(document_id)`.
- **Metadata filters**: extend `RetrievalScope` + all stage SQL + server schemas + MCP tools with year range, author, journal, DOI excludes. Migration for `journal` column + indexes.
- **Entity resolution**: extraction prompt emits aliases; `sci-rag graph resolve-entities [--dry-run]` merges by alias/fuzzy/LLM adjudication with audit log and `canonical_entity_id`; ablation proves retrieval impact.
- **Confidence-weighted traversal**: extraction prompt emits calibrated confidence; graph stage filters/weights by it; ablation config.
- **Contextual snippet compression** (PaperQA2 pattern): optional per-chunk relevance-scored summarization before answer assembly; judged-answer eval must show quality holds while tokens drop.
- **PRISMA-style screening** (optional flag-ship item, may slip): `sci-rag campaign screen` LLM inclusion/exclusion on abstracts with a human-review queue for low-confidence rows; PRISMA-aligned counts in the report.

## WAVE 3: v0.4+ "Scale and intelligence"

Lazy/cached community summaries with graph-change invalidation (LazyGraphRAG lesson); per-document extraction cache for cheap update/delete (LightRAG lesson); bi-temporal edge validity + `as_of` scoping (Graphiti lesson); multi-corpus in one deployment (schema-per-corpus + corpus routing; PISCES KbCollection analogue) feeding the federation seam; Prometheus/OTEL observability + `/metrics`; HTML/LaTeX/DOCX parsers + Docling OCR exposure; hierarchical communities (populate the level column, parent links); visual-retrieval seam (image chunks + vision embeddings) last, behind an extra.

## Credibility ladder and community program (sequenced)

1. At flip-public: benchmark page, comparison page, ROADMAP/VERSIONING/GOVERNANCE, Discussions + good-first-issues, notebook, ADOPTERS stub. 2. Fast-follow (user-gated): attribution/CITATION.cff wording, Zenodo DOI on next release, PyPI decision, HF Spaces demo. 3. JOSS paper (methodology.md is 70% of the draft; benchmark page supplies results; ~1000 words + review). 4. pyOpenSci review once community signals exist. 5. BioCirV flagship case study + second public domain example. Success is measured behaviorally (external PRs, adopter entries, citations), not stars.

## PISCES cross-pollination

Into the kit (Wave 1-2): reranker (PISCES `lib/builder/reranker.ts` pattern), re-embed planner (`lib/kb/reembed-planner.ts`), corpus catalog/fingerprint discipline (`docs/kb-system/CORPUS-CATALOG.md`), multi-corpus collections (KbCollection). Back to PISCES (file follow-up issues as each proves out in the kit): adaptive routing for Florence interactive latency, snippet compression for KB answers, entity alias resolution for the KG, statistics/CI + report-diff for the eval registry, campaign builder for corpus growth, and the already-filed thinking-budget fix (#6893).

## Verification (Wave 1)

Each item: unit + integration tests (offline, mock LLM; the existing harness), ablation/eval evidence committed to `docs/benchmarks.md`, `make check` green, CI green. Wave-1 exit: benchmark page reproducible via `make benchmark` from a clean clone; delete/GC regression test proves deleted docs unreachable through all layers; `eval diff` demonstrated on two real runs; calibration run on the seeded label set with kappa reported; doctor updated for new subsystems; CHANGELOG + ROADMAP updated; full test suite and the four CI jobs green.

## Out of scope (deliberate, from the anti-recommendation evidence)

No Neo4j/graph-DB migration; no RAPTOR; no default agentic retrieval loop (routing + decomposition first; an agentic mode may become a Wave-3+ experiment); no Anthropic-style contextual embedding at index time (breadcrumb prepending already captures the value); no learned fusion; recursive-CTE traversal stays, with the >10M-edge escape hatch documented.
