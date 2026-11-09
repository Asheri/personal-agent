# Core engineering completion

The v1.8 candidate completes scoped browsing, refresh triggers, and Agent memory
integration on top of v1.7. It also repairs identifier retrieval across language
boundaries and closes the default external-tool rights scope. Independent review,
course report/slides/demo, and optional P6 research remain separate work.

## Browse the corpus

`sci-rag browse documents`, `projects`, `timeline`, `topics`, and `facets` use the
same `RagService` operations as REST and MCP. The API exposes
`GET /v1/corpus/browse`, `/facets`, `/projects`, and `/topics`. MCP adds
`browse_corpus` and `list_projects` to the earlier relation/version tools.

Pass a JSON filter object with `--filters` on the CLI, `filters` on the GET
query string, or the MCP tool. Supported fields include license/source allowlists,
publication-year bounds, authors/journals/DOI exclusions, document-date bounds,
projects, manual tags, automatic tags, and entity names. An explicitly empty
license or source allowlist returns nothing. Empty metadata lists add no filter.
Unknown fields and reversed date ranges fail validation.

```powershell
sci-rag browse facets --filters '{"sources":["local"]}'
sci-rag browse documents --filters '{"date_min":"2026-01-01","tags":["reviewed"]}'
sci-rag browse projects --by <stable-project-id>
sci-rag browse timeline --by 2026-10
sci-rag browse topics --by <exact-named-topic>
```

Documents sort by `doc_date desc nulls last`, `ingested_at desc`, and `id`.
Pagination is deterministic for a fixed corpus; concurrent changes require a new
traversal. Project/time/tag/topic/parser facets retain explicit `value=null`
buckets. Array/topic facets can count a document in several nonempty buckets.
Their bucket sums are not unique document totals. Project and time buckets each
partition the visible corpus. Empty corpora return empty arrays and total zero.

Named topics come from `KgEntity(entity_type='Topic')` with current literal
chunk evidence. Community summaries are a separate overview, never a filter.
Any restricted scope suppresses community overview text and counts because its
stored aggregates cannot be filtered after generation.

Document dates use mail Date, Office modified property, source mtime in UTC,
then ingestion time. `doc_date_source` distinguishes those sources; this is
independent of `publication_year`. Range filtering retains null dates. Revision
0012 backfills old rows from stored metadata, without reopening source files.
Ingest signature 3 performs one checked reparse afterward, including XLSX modified
properties that were not retained before. Unchanged chunks keep their existing
row/vector state. An optional OCR runtime is still needed to reparse image sources.

## Retrieve identifiers

The existing simple-language token index now includes Latin-only documents.
English queries retain the English stemming/phrase path and also probe the
simple index. Chinese questions retain search-mode segmentation and can now
find identifiers in pure English sources. Ranking takes the greater matching
term score before the existing fusion; no fusion weights changed.
Mixed questions with an explicit Latin/digit identifier rank identifier matches
ahead of common question words, before the candidate limit. A coverage-only
intermediate trial reduced nDCG and is retained; the final matched diff removes
that regression. First-hit metrics and target-document recall are reported separately.

The fixed 24-query language-boundary experiment has eight identifier, eight
mixed, and eight name queries. Every identifier has three expected documents,
so the measured value is target-document recall, not ordinary hit@20. The
before/after files preserve the same corpus digest, raw hits, and warm timings.
This constructed test does not establish general semantic quality. Older real
model and 24-query Chinese spike evidence stays in its original dated archive.

## Refresh and recover

`sci-rag refresh run <root> --channel manual|scheduler|hooks|poll` performs one
bounded refresh. An optional `--manifest` must sit directly under the explicit
root. Folder ingestion keeps unknown rights; manifests declare rights explicitly.
Use `--no-graph` when model updates are deliberately disabled. Missing generation
configuration is reported as `disabled_no_generation`, not a successful model run.

All channels hold the same connection-owned PostgreSQL advisory lock across
reconciliation and derived updates. A second instance returns exit 2 without a
database write. Source failures preserve their old version, defer unsafe deletion,
and return exit 1. Version writes retain the existing transactional writer lock.
Interrupted run markers become `interrupted` when the next owner takes the lock;
committed source work is safely reconciled again, not blindly repeated.

Revision 0013 adds `file_events`: run/source/database statuses, counts, and hashed
root/path identities. Bodies, queries, filenames, and project/person names do
not enter this audit. CLI results also persist under `.context/refresh-reports`.
`sci-rag refresh history` and `doctor` expose failed/interrupted outcomes.

Refresh updates mention edges, ownership rules, available graph extraction and
communities, and memory freshness. Graph calls retain the external-safe rights
gate. Configure generation explicitly for automatic entity/tag inference; offline
checks validate the update mechanism and declared degradation without paid calls.
Polling remains one-shot invocation by an OS task, with no permanent watcher.

## Memory and Agent integration

See [Agent deployment](deploy-pcmem.md) for the tested plugin/launcher installation.
Task start reads project/browse pointers; retrieval questions search; successful
file writes refresh and read versions; task completion records confirmed operation
receipts; scheduled checks refresh and maintain freshness. Only document ids,
operation status, and SOP pointers enter injected context. The adapter does not
copy source bodies, titles, paths, or queries into memory or routing logs.

Actual retrieval increments `access_count` and `last_accessed_at` once per returned
document. Access telemetry failure is logged by exception type while evidence can
still be served by a read-only host. Maintenance marks superseded revisions stale,
and marks a current document stale only after a year without access plus newer
material with the same explicit topic. It never physically deletes evidence.
Validity end times come from actual successors; inactivity alone does not invent
a fact's expiration date. Version responses label expired evidence explicitly.

Hot pointers are a managed patch within the 30-line L1 index. Existing rules
remain intact, while access order can change the managed pointer block. Every
memory edit retains a unified patch. Three distinct confirmed successful tasks
of one category create a small L3 procedure; failed or unexecuted tasks do not.
A fresh router reads the persisted procedure. This is a verified template workflow,
not a claim that a model learned an arbitrary new skill.

## External scope and limits

All external MCP read tools now intersect caller rights with `public` and
`open_commercial`. Unknown/restricted inputs cannot be exposed through document
details, histories, relations, entities, facets, source lists, or aggregate counts.
Explicitly requesting unknown rights returns no documents. Public corpus metadata
uses the same gate. The local REST catalog remains an operator-facing read surface;
it requires authentication when configured and should remain on loopback otherwise.

The user-facing `corpus export` command also defaults to external-safe rights and
excludes access telemetry columns. The trusted library export API retains its
explicit operator semantics for internal data handling; it is not an external tool.

Evidence is in `.context/core-completion-20261026/`. It includes failed development
trials, new migration round trips, privacy negatives, trigger/lock checks, the
matched keyword experiment, upstream protocol checks, and bounded polling costs.
The upstream check uses the real pinned hook bus, dispatch loop, and scheduler
with a controlled handler; it does not run a live model conversation. Its runtime
and test corpus are deleted after archiving. Native OCR and real-model extraction
results inherited from v1.7/v1.6 are historical evidence, not reruns of this stage.

No representative personal corpus, human approval, large-directory latency SLA,
handwriting benchmark, or P6 narrative/multimodal research claim is implied.
See [ADR 0020](adr/0020-core-browse-refresh-memory.md) and the
[engineering requirement matrix](engineering-requirements.md).
