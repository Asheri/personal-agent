---
title: Operate a live corpus
description: Back up, restore, snapshot, delete, garbage-collect, and re-embed a corpus that keeps changing under a running service.
---

# Operate a live corpus

Protect a live corpus with two records: a snapshot identifies its documents, while a
database backup preserves the stored data. Rehearse the restore before you need it.

<div class="srag-meta-strip">
  <div><strong>You'll build</strong>A backup, a restore drill, and a snapshot protocol</div>
  <div><strong>You'll need</strong>Database access and `pg_dump`</div>
  <div><strong>Time</strong>About 30 minutes for the first pass</div>
  <div><strong>Tested with</strong>v0.5</div>
</div>

## Before you start

| Requirement | Why | Check |
|---|---|---|
| A corpus worth protecting | Most of this page is unnecessary on the demo fixture | `uv run sci-rag stats` |
| `pg_dump` and `psql` on your path | The backup and restore paths are ordinary Postgres tools | `pg_dump --version` |
| Storage outside the database host | A separate destination protects the dump from host or disk loss | |
| A disposable database for the restore drill | You are going to restore into it, and it will be overwritten | |

## Crossref enrichment and retraction review

After ingesting DOI-bearing papers, preview Crossref enrichment:

```bash
uv run sci-rag corpus enrich --mailto you@example.org --dry-run
```

The dry run makes no network calls and writes nothing. Remove `--dry-run` to apply it; use `--limit N` for a trial. The client sends your contact address to Crossref's polite pool, rate-limits requests, retries 429 and 5xx responses, and records failures per document. Later runs skip metadata refreshed in the last 30 days.

The command adds citation count, journal, normalized reference DOIs, enrichment time, and explicit Crossref retraction assertions to `documents.extra`. It also promotes journal to its indexed column. Both current `updated-by` responses and Retraction Watch's `update-to` format are recognized. The kit never infers retraction from titles or missing fields.

Preview citation reconciliation, then apply it:

```bash
uv run sci-rag graph citations --dry-run
uv run sci-rag graph citations --apply
```

Resolved rows connect two corpus documents that exist. References to DOIs not yet in the corpus stay as null-target pointers and resolve later when you ingest them. Self-references and duplicate DOI references skip edge creation. `corpus delete` cascades affected pointers. Later, `sci-rag graph gc` reports and removes any dangling rows.

After citation reconciliation, run `uv run sci-rag doctor`. It reports known retractions. Answer generation excludes retracted documents by default; raw retrieval does not change. Review flagged records and use `sci-rag corpus delete` when they should go.

## Record corpus identity

```bash
uv run sci-rag corpus snapshot v0.2-demo
```

This writes `data/snapshots/v0.2-demo.json`: document counts, per-document content hashes, embedding versions, the git commit, and a single `corpus_digest` (SHA-256 over sorted content hashes). Two corpora with the same digest hold identical documents, regardless of IDs or ingestion order.

Snapshots are small, immutable (naming something twice fails), and safe to commit next to eval evidence. Reference them from eval runs:

```bash
uv run sci-rag eval retrieval --ablation --snapshot v0.2-demo
```

The report JSON carries the snapshot name, so later you can verify the numbers came from exactly that corpus. Snapshots contain identity metadata. Database backups preserve the stored data.

## Backup

### Local or self-hosted Postgres

Keep the database password out of shell history and process arguments. Put it in a libpq
passfile such as `~/.pgpass`, restrict the file to your account, and reference that file from
the application URL. The passfile fields are `host:port:database:user:password`:

```text
localhost:5433:sci_rag:sci_rag:your-database-password
```

```bash
chmod 600 ~/.pgpass

# Read the configured URL and convert the async driver name for libpq.
SCI_RAG_DATABASE_URL_SYNC="$(
  grep -m1 '^SCI_RAG_DATABASE_URL=' .env |
    cut -d= -f2- |
    sed 's/^postgresql+asyncpg:/postgresql:/'
)"

# Stop if the URL contains a password that pg_dump would expose in its process arguments.
case "$SCI_RAG_DATABASE_URL_SYNC" in
  postgresql://*:*@*) echo "Move the inline database password to a passfile." >&2; exit 1 ;;
esac

# Custom-format archive: schema and data, compressed.
pg_dump "$SCI_RAG_DATABASE_URL_SYNC" --format=custom \
  --file "backups/sci-rag-$(date +%Y%m%d).dump"
```

`backups/` is ignored by Git and ships with `.gitkeep` so it exists before you need it. This matters because a dump holds everything you ingested. For a private corpus, the file **is** the corpus. Writing it to the repository root, as this page used to recommend, left it one `git add .` away from being published.

Keep only working copies there. Valuable data belongs encrypted, on a separate destination, under whatever retention your licenses require. Credentials and Terraform state are separate concerns. A database dump contains neither.

The procedure preserves a `?passfile=` query from the application URL and stops before
`pg_dump` if the URL contains an inline password. If `.env` has no application URL, add a
passwordless URL with a `passfile` query before running the procedure.

Restore a custom-format archive with `pg_restore`. The archive is compressed and supports restoring one table at a time. Plain output is SQL for `psql`; each command accepts a different archive format.

The pgvector extension types are included in the archive. The restore target needs the extension available; migration 0001 runs `CREATE EXTENSION vector`, and `pg_restore` recreates it from the archive.

### Cloud SQL (the deploy-gcp.md path)

Prefer managed backups:

```bash
gcloud sql backups create --instance=YOUR_INSTANCE --project=YOUR_PROJECT
gcloud sql backups list --instance=YOUR_INSTANCE --project=YOUR_PROJECT
```

Enable automated daily backups and point-in-time recovery on the instance. The Terraform module in `infra/` exposes both flags. Take a manual backup before every schema migration and every bulk operation (delete campaigns, re-embed).

<!-- BEGIN GENERATED PROJECT FEATURE: cloud-helper -->
The optional development Cloud SQL helper is a different path. Its instance
has no backup guarantee, and backups plus deletion protection are disabled by
default. Do not store the only copy of a valuable corpus there. Export or dump
anything you need to keep before an operator pauses or replaces the instance.
<!-- END GENERATED PROJECT FEATURE: cloud-helper -->

## Restore drill

Rehearse this before an incident, on a scratch database:

```bash
createdb sci_rag_restore
pg_restore --dbname "postgresql://sci_rag:sci_rag@localhost:5433/sci_rag_restore" \
  --no-owner "backups/sci-rag-20260827.dump"

# Point the kit at the restored copy and verify:
SCI_RAG_DATABASE_URL="postgresql+asyncpg://sci_rag:sci_rag@localhost:5433/sci_rag_restore" \
  uv run sci-rag doctor
```

`doctor` checks schema, pgvector, corpus counts, and embedding versions. Then compare identity against the snapshot you took before the dump:

```bash
SCI_RAG_DATABASE_URL=... uv run sci-rag corpus snapshot restore-check
# corpus_digest in data/snapshots/restore-check.json must match the
# digest from the snapshot taken when the backup was made.
```

Cloud SQL restores use the console or `gcloud sql backups restore`. Run the same doctor + snapshot-digest verification afterward.

## Analytical export

For sharing data outside Postgres or archival:

```bash
sci-rag corpus export export/                      # JSONL, no extra dependency
sci-rag corpus export export/ --format parquet     # needs `uv sync --extra export`
```

One file per table: `documents`, `chunks`, `entities`, `relationships`. Chunk embeddings are omitted by default because they dominate the output size and few downstream consumers want them. Use `--include-embeddings` to keep them.

### An export is redistribution

Reading rows out of Postgres by hand, with DuckDB or anything else, loses the rights enforcement the kit applies elsewhere. The copy that leaves the database is the copy nobody re-checks. So export applies the same license allowlist retrieval does, fail-closed:

```bash
sci-rag corpus export export/ --license public --license open_commercial
```

`unknown` is excluded unless you name it, like in retrieval. The graph uses a stricter rule: an entity's description aggregates evidence from every document it was extracted from, so **an entity survives scope only when every source document did**. A relationship survives only when its own document did and both endpoints survived. Entities with no document attribution cannot be scoped, so a scoped export drops them.

Communities are never exported. A community summary aggregates across documents with no per-document attribution to filter on, the same reason the community retrieval layer disables under any scope.

### Restore from a database backup

Use `pg_restore` or Cloud SQL backups to restore the database. Analytical exports represent vectors as arrays and omit the database structures needed for a restore. In Parquet, `documents.extra` stays a JSON string because its keys vary by document and an inferred schema would change with the corpus.

## Retrieval latency

```bash
sci-rag profile                       # interactive, deep, and auto over the seed questions
sci-rag profile --runs 10             # more replays, tighter percentiles
sci-rag profile --json                # machine-readable, for tracking over time
```

Nothing new is instrumented: each request already records per-stage duration. The profiler replays seed questions and aggregates those traces into p50/p95 per stage, per profile, plus a verdict naming the slowest stage and what `auto` chose.

Two aspects are easy to misread, so the command names both:

* **Concurrent stages overlap.** Candidate generators run at the same time, so request latency tracks the slowest stage. Each table title reports wall-clock time separately.
* **The query-embedding cache is off while profiling.** Production requests cache query embeddings in memory, so replaying one question ten times would measure cache hits on runs 2–10 and report a p50 no real user sees. Every profile run is cold, which makes profiles comparable and slightly pessimistic about warm performance.

A switched-off stage reports `disabled`. The `interactive` profile disables graph, community, and HyDE by design, and an unconfigured reranker reports the same status. Degradation warnings are reserved for stages that ran and failed. A timeout can shorten a request while leaving it incomplete.

The profiler measures speed. Use [Benchmarks](benchmarks.md) to judge whether a layer improves retrieval or answer quality.

## The habits that matter

1. Snapshot before and after every bulk change (ingest campaign, delete, reindex). The digest diff is your receipt.
2. Back up before schema migrations.
3. Run the restore drill before an incident.
4. Run `sci-rag doctor` after every restore.

<div class="srag-checkpoint" markdown>
**Checkpoint: the restore actually works**

The drill has been run at least once: dump, restore into a scratch database, `sci-rag doctor` clean, and a corpus digest that matches the snapshot taken before the dump. The restore procedure must be verified before it is needed.
</div>

## Next steps

- Re-embed after changing a model or a dimension: [Configuration](configuration.md)
- Understand what a license class does to retrieval: [Scope precedes ranking](methodology.md#7-scope-precedes-ranking)
- Run the same service on managed infrastructure: [Deploy on Google Cloud](deploy-gcp.md)
