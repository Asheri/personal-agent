---
title: Run a corpus campaign
description: Discover a resumable DOI list, resolve explicit open-access rights, download verified PDFs, and write an ingestible corpus manifest.
---

# Run a corpus campaign

A campaign turns a research topic or DOI list into a reviewable corpus manifest. It
records discovery and rights checks before ingestion, so you can inspect candidates and
resume interrupted network work without starting over.

<div class="srag-meta-strip">
  <div><strong>You'll build</strong>A screened, rights-resolved corpus manifest</div>
  <div><strong>You'll need</strong>A topic or a DOI list, and a contact email</div>
  <div><strong>Time</strong>Minutes to run, longer to review</div>
  <div><strong>Credentials</strong>Optional, for the screening model only</div>
  <div><strong>Tested with</strong>v0.5</div>
</div>

## Before you start

| Requirement | Why | Check |
|---|---|---|
| A working database | The manifest is only useful once you ingest it | `uv run sci-rag doctor` |
| A contact email you monitor | OpenAlex, Crossref, and Unpaywall all want one, and rate-limit anonymous callers hard | |
| A topic phrase or a file of DOIs | The two ways to start a campaign | |
| Network access | Every step here talks to an external index | |

Campaigns never make rights decisions for you. Discovery produces candidates and an
explicit open-access signal from Unpaywall. Anything unestablished stays `unknown`,
which retrieval treats as unsafe.

## Discover from a topic

Identify every API request with a monitored contact address:

```bash
uv run sci-rag campaign discover \
  --topic "rice straw valorization" \
  --name rice-straw \
  --mailto you@example.org \
  --max-results 100
```

Topic discovery searches OpenAlex with cursor pagination. Casual use works without a key. For higher limits, set `OPENALEX_API_KEY` in the environment. The kit never prints that key or writes it to campaign state.

## Discover from DOI seeds

Put one bare DOI, DOI URL, or `doi:` value on each line. The reader skips
blank lines and lines beginning with `#`.

```text
10.7717/peerj.4375
https://doi.org/10.1038/s41586-020-2649-2
```

Then run:

```bash
uv run sci-rag campaign discover \
  --doi-file seed-dois.txt \
  --name seed-review \
  --mailto you@example.org
```

DOI-file discovery normalizes and deduplicates the values, then retrieves
bibliographic metadata from Crossref. The report counts invalid lines and
malformed upstream records, so none of them disappears silently.

## Resume behavior

Campaign state lives in `data/campaigns/<name>/state.jsonl`. Each completed DOI step is
appended to disk, and a repeated command skips records already present. If a write is
interrupted, the next run ignores the truncated tail and resumes from the last complete
record.

OpenAlex and Crossref calls are rate-limited. The client sends your contact address in both the query and User-Agent, retries 429 and 5xx with bounded backoff, and fails visibly when retries exhaust. An empty success report never happens.

Discovery metadata establishes that a document exists. Resolve its redistribution rights before downloading:

```bash
uv run sci-rag campaign build \
  --topic "rice straw valorization" \
  --name rice-straw \
  --mailto you@example.org \
  --max-results 20 \
  --dry-run
```

The dry run queries Unpaywall for each DOI, prints direct-PDF counts and the license-class breakdown, and writes only resumable state. It does not create `pdfs/` or `corpus.jsonl`.

`--max-results` bounds discovery, rights resolution, screening, and download for this invocation. If the campaign retained 100
candidates, `--max-results 20` resolves the first 20 and leaves the rest untouched in
dry-run and download modes. Because campaign state is append-only, retrying works on
the same prefix. The report shows both `retained` and
`candidates`; pass `--all-candidates` to process every retained candidate.

## Fail-closed rights mapping

Availability and redistribution rights are different signals. Unpaywall may mark a green or gold copy as reachable. Sharing still requires an explicit, recognized license at the selected location:

| Explicit location license | Corpus class |
| --- | --- |
| CC0 or public-domain mark | `public` |
| CC BY family | `open_commercial` |
| CC BY-NC family | `open_noncommercial` |
| Missing, `implied-oa`, publisher-specific, or unrecognized | `unknown` |

The mapping never infers a license from `oa_status`, a working URL, or a PDF response. `unknown` is the intentional safe default when rights are unclear.

## Download and ingest

Review the dry-run distribution, then repeat without `--dry-run`. The builder fetches only Unpaywall's direct `url_for_pdf` for records marked open access. It never scrapes landing pages.

Each response must declare `application/pdf`, stay within `--max-pdf-mb`, and start with a PDF signature. The builder writes to a temporary path and renames only after validation. After an interruption it reuses verified files, so resumed runs never download twice.

Successful downloads produce `data/campaigns/<name>/corpus.jsonl` in the format `sci-rag ingest` reads:

```bash
uv run sci-rag ingest --manifest data/campaigns/rice-straw/corpus.jsonl
```

Every manifest row retains the normalized DOI, bibliographic metadata,
fail-closed `license_class`, and the exact Unpaywall license signal in
`license_source`.

## Screen a discovered campaign

Write the review protocol as plain text. State the inclusion and exclusion
criteria precisely enough that another reviewer could apply them without
outside context:

```text
Include field studies of rice-straw conversion with a measured material yield.
Exclude reviews, simulations without experimental validation, and studies of
other feedstocks.
```

Screen the abstracts already retained in campaign state:

```bash
uv run sci-rag campaign screen \
  --name rice-straw \
  --criteria-file screening-criteria.txt \
  --confidence-threshold 0.8
```

The model receives abstracts in bounded batches and returns one strict `include` or `exclude` decision, confidence, and reason per work. The command does not trust that output blindly:

* Confidence below the threshold becomes `review`.
* A missing abstract becomes `review` without calling the model.
* Malformed JSON, missing rows, duplicate indexes, and provider failures mark the affected batch `review`.
* No failure path silently excludes a work.

Decisions append to `state.jsonl`. `screening-report.json` records the current protocol, its SHA-256 digest, the confidence floor, every per-work reason, failure counts, and the current PRISMA-aligned totals. PRISMA (Preferred Reporting Items for Systematic Reviews and Meta-Analyses) is the reporting standard for systematic reviews. Aligning with it means the counts match what reviewers expect. Repeat the same protocol and it resumes without calling the model. Change the criteria or floor and it starts fresh while preserving the old history.

The screening report begins at the deduplicated campaign-state boundary.
`identified`, `screened`, and the sum of `included`, `excluded`, and
`awaiting_review` therefore reconcile against the unique discovered works.
`campaign discover` already removed and reported the upstream duplicates, so
`duplicates_removed` is zero at this boundary. Exclusions include both an
aggregate count and a breakdown by reason.

## Review uncertain rows

Walk the queue interactively:

```bash
uv run sci-rag campaign review --name rice-straw
```

For each row, choose `include`, `exclude`, or `skip` and record a reason. Human decisions append after the model's suggestion, and the report regenerates from your latest choice. Skip a row and it stays `awaiting_review`, so totals reconcile without claiming you finished.

<div class="srag-checkpoint" markdown>
**Checkpoint: every row has a decision**

`sci-rag campaign review --name rice-straw` ends by printing the PRISMA-aligned
counts and the path to `data/campaigns/rice-straw/screening-report.json`, which
it rewrites from the latest decisions. In that table `included` plus `excluded`
plus `awaiting review` equals `screened`. No row is missing, and no row is
included without a rights answer you can point at.
</div>

**Verify the manifest is ready to ingest.** Open `data/campaigns/rice-straw/screening-report.json`. Confirm that `included` plus `excluded` plus `awaiting_review` equals `screened`. Check that `corpus.jsonl` exists and holds one JSON object per included row.

## Next steps

- Ingest the manifest this produced: [Bring your own domain](bring-your-own-domain.md#step-4-build-the-knowledge-base)
- Understand what a license class does to retrieval: [Scope precedes ranking](methodology.md#7-scope-precedes-ranking)
- Enrich the DOIs and check for retractions: [Operate a live corpus](operations.md)
