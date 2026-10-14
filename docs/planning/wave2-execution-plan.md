# Wave 2 execution plan: v0.3 "Campaigns"

> Authored 2026-08-27 at the start of Wave 2, from
> [wave2-handoff.md](wave2-handoff.md) and the "WAVE 2" section of
> [v02-roadmap-plan.md](v02-roadmap-plan.md). This is the decomposition
> the epic and its sub-issues are cut from: eleven sub-issues, their
> dependency order, the decisions taken up front, and the evidence each
> one owes before it lands.

## Drift check (against the handoff's commit a8f5331)

Verified on 2026-08-27 at `HEAD = 2ddc223`, one commit past the handoff's
baseline (the handoff doc itself). Everything the technical map names is
where it says it is:

- `src/sci_rag/retrieve/types.py`: `RetrievalScope` frozen dataclass with
  `license_classes`, `sources`, `exclude_document_ids`, plus
  `denies_all()`, `is_unrestricted()`, and `scope_conditions()`. The
  `is_unrestricted()` community trap is live in
  `retrieve/retriever.py` (`community_scope_blocked`) and in
  `retrieve/stages/community.py`.
- `src/sci_rag/db/models.py`: `Document.extra` JSONB present and empty;
  `KgEntity.aliases` ARRAY present and written nowhere;
  `KgRelationship.confidence` Float present, defaulted 1.0, read nowhere.
- `migrations/versions/`: `0001_initial.py` and
  `0002_community_embedding_version.py`. 0002 is the `ADD COLUMN IF NOT
  EXISTS` template for everything after it.
- Five stages under `retrieve/stages/`, `graph.py` carrying `_WALK_SQL`
  and `MAX_HOPS = 2`.
- `server/mcp_server.py` exposes seven tools; `server/schemas.py` carries
  `QueryRequest`/`AnswerRequest`; `server/service.py` has
  `RagService.scope_from`.
- `evals/retrieval_eval.py` holds `DEFAULT_ABLATIONS` (8 configs today).
- Baseline `make check`: ruff + mypy clean, **191 tests passed**.

No re-derivation needed. The map holds.

## Decisions taken up front

**D1. CITES edges live in their own table, not in `kg_relationships`.**
Recorded as [ADR 0005](../adr/0005-citation-edges-as-a-document-table.md).
A new `document_citations` table with `citing_document_id`,
`cited_document_id`, and provenance columns. `KgRelationship` is
entity-to-entity by contract, and synthetic per-document entities would
pollute entity search, community detection, and the GC sweep. The cost of
the separate table is that `corpus delete` and `graph gc` must learn
about it, which they must anyway.

**D2. `exclude_retracted` defaults OFF on the dataclass and ON at the
answer path.** `RetrievalScope(exclude_retracted=False)` keeps every
existing construction of a scope behaving exactly as before, including
`RetrievalScope()` in the eval harness. `AnswerEngine.answer_stream`
flips it on unless the caller passes a scope that says otherwise. That
keeps "answering never cites a retracted paper" true without silently
changing what `sci-rag retrieve` and the retrieval ablations measure.

**D3. Retraction status is a JSONB read, not a new column.** Filters
should not query JSONB as a rule (that is why `journal` becomes a real
column in S1), but retraction is a sparse boolean that only ever narrows
a result set, and a partial expression index
(`(extra->>'is_retracted')` where true) serves it at demo and mid scale.
A dedicated column is a Wave 3 change if a corpus ever makes it hurt.

**D4. Citation traversal joins the graph stage; it is not a sixth
layer.** The fusion weights, the router, the trace contract, and
`tests/server/test_api_contracts.py` all enumerate five layers plus
rerank. Adding a sixth stage would change the public trace shape for a
capability that is a variant of "walk from here to related evidence".
The graph stage gains an optional citation expansion step, off unless
the domain enables it, and the ablation measures it.

**D5. The entity-resolution audit log is a table, not a JSONL file.**
`entity_resolution_audit`, one row per merge decision, carrying method
(`alias` | `fuzzy` | `llm`), confidence, both names, and the timestamp.
Database state survives redeploys; a file under `data/` does not.

**D6. Campaign state is a JSONL file under `data/campaigns/<name>/`.**
The opposite call from D5 on purpose: campaign state is per-run scratch
for a resumable network job, not corpus state, and a killed run must be
resumable without a database at all.

## Sub-issue decomposition

| Tier | ID | Title | Depends on |
|------|----|-------|------------|
| T0 | S1 | [Retrieve] Metadata filters: year, author, journal, DOI excludes in every layer | none |
| T0 | S2 | [Corpus] Crossref enrichment and `exclude_retracted`, default on for answering | none |
| T0 | S3 | [Graph] Extraction emits entity aliases and calibrated relationship confidence | none |
| T1 | S4 | [Campaigns] Discovery: OpenAlex and Crossref to a DOI list, rate limited and resumable | none |
| T1 | S5 | [Campaigns] OA resolution, legal download, and a fail-closed manifest with `--dry-run` | S4 |
| T2 | S6 | [Graph] Entity resolution with audit log and `canonical_entity_id` | S3 |
| T2 | S7 | [Retrieve] Confidence-weighted graph traversal | S3 |
| T2 | S8 | [Graph] Citation edges, citation traversal, and MCP `get_citations` | S2 |
| T3 | S9 | [Answer] Contextual snippet compression, gated on judged evidence | none |
| T3 | S10 | [Campaigns] PRISMA-style screening (stretch, may slip) | S4, S5 |
| T3 | S11 | [Release] Wave 2 wrap: benchmark refresh, CHANGELOG 0.3.0, version bump, ROADMAP | all |

Execution is sequential in one workspace. The shared hotspots
(`cli/main.py`, `retrieve/types.py`, `server/schemas.py`, `db/models.py`,
`evals/retrieval_eval.py`) make parallel PRs collide, and Wave 1 proved
that stacking plus prompt restacking beats merge-conflict archaeology.

## Evidence each item owes

| Item | Ablation config | Evidence |
|------|-----------------|----------|
| S1 | none (filters narrow, they do not rank) | Integration test proving a year-filtered request disables the community layer, and a scoped-request demo |
| S2 | `no_retracted` | Retrieval eval on the demo corpus, which has no retracted documents, so the honest expected result is "identical metrics"; the test that proves the filter bites uses a synthetic retracted row |
| S3 | none directly (foundation) | Extraction test showing aliases and confidence stored, and old-format responses still parsing |
| S4, S5 | none (corpus construction, not retrieval) | One live `--dry-run` on a small CC-licensed topic, marked `cloud`, output pasted into the PR |
| S6 | `resolved_entities` | `sci-rag eval diff` between a run before and after `resolve-entities` on the demo corpus |
| S7 | `confidence_weighted` vs `full_deep` | Retrieval eval both ways, CIs reported |
| S8 | `with_citations` | Retrieval eval, plus the delete/GC unreachability regression test extended to citation edges |
| S9 | `compressed` (answers eval, not retrieval) | Judged answers both ways with dimension means and CIs, plus measured prompt-token counts. Adoption requires quality inside the CI while tokens drop; rejection with the numbers recorded is a valid outcome |
| S10 | none | Screening run against committed fixtures with PRISMA counts |
| S11 | all of the above | `make benchmark` re-render of `docs/benchmarks.md` |

## Out of scope, permanently

Neo4j or any graph-database migration, RAPTOR, agentic retrieval loops on
every query, index-time contextual embedding, learned fusion. Wave 3
items stay in the roadmap: lazy community summaries, extraction caching,
bi-temporal edges, multi-corpus, observability, more parsers,
hierarchical communities, the visual-retrieval seam.

## User-gated, prepared but not executed

`CITATION.cff`, the Zenodo DOI, JOSS submission, PyPI publication, a
hosted demo, flipping the repository public, and the `v0.3.0` git tag
itself. The release-wrap sub-issue prepares the version bump, the
CHANGELOG entry, and release notes, then hands the tag decision to the
maintainer.
