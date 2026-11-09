---
title: Document relations and Agent tools
description: Inspect scoped similarity, references, retained revisions, and project peers through one service.
---

# Document relations and Agent tools

Inspect document-level relations separately from extracted concept-graph edges. CLI,
REST, and MCP use shared scope checks; this candidate awaits nonauthor group review.

## Four relation views

```bash
sci-rag relate similar DOCUMENT_ID --source YOUR_SOURCE
sci-rag relate citations DOCUMENT_ID --license public
sci-rag relate versions DOCUMENT_ID
sci-rag relate projects DOCUMENT_ID
```

Similarity uses a stored uncentered mean of each document's chunk embeddings. Ingestion
and re-embedding refresh it in the same transaction. Incomplete or mixed-version chunks
invalidate the mean. At query time, candidates and the centering mean are limited to the
visible corpus and the seed's embedding version. Hidden documents cannot influence its
scores. Different embedding versions are never compared. A score is a geometric ranking,
not a probability or proof that two documents describe the same work. Small corpora and
zero centered vectors can give unhelpful or empty rankings. Query cost grows with visible
document vectors; this is not an approximate-neighbor service for a large corpus.

Project peers share a nonempty project id. Returned assignments keep their manual,
rule, or inferred provenance. Unknown-project documents are not grouped together.
The explicit versions operation includes retained history but keeps the other scope
filters; hidden predecessors return null, and no synthetic version is invented.
Ordinary relation reads still use current documents by default.

## Build derived relations

Upgrade the database to revision 0010 before using this code. Existing chunk vectors can
populate the new means without generation or embedding model calls:

```bash
sci-rag db upgrade
sci-rag relate embeddings
sci-rag relate embeddings --apply
sci-rag relate mentions
sci-rag relate mentions --apply
```

Both builders default to dry run. Mention detection recognizes explicit wikilinks,
simple Markdown link destinations, backtick filenames, and bare DOI references. It does
not infer references from incidental names, implement a full Markdown parser, fetch URLs,
read linked files, or call a model. The literal key and source chunk are retained. Relative
paths are resolved before names; duplicated names remain unresolved. Rebuilding after a
target is ingested can resolve its pointer. Equivalent resolved pairs are deduplicated,
and authoritative cached Crossref references take precedence. A changed source's mention
set is replaced atomically; an unchanged set is a no-op. Source updates require another
explicit mention build. These references do not automatically enable citation expansion
in retrieval; that opt-in still requires paired evaluation.

Mentions require an evidence chunk and confidence in the database. Reads additionally
verify chunk ownership and the literal source text, and filter both document endpoints.
The confidence value records exact syntax matching, not semantic entailment. Existing
Crossref references keep their metadata provenance and need no fabricated chunk quote.

Revision 0010 adds document means and nullable mention fields while preserving existing
Crossref rows. Empty upgrade/downgrade is supported. Populated means or new citation data
prevent downgrade before destructive DDL; back up and explicitly convert data first.
Upgrade matches the persisted chunk vector dimension and invalidates means whose chunk
vectors are missing, mixed, or from a different version. A vector-resize migration must
not leave a stale derived mean behind.
This follows the existing loss-refusing migration policy.

## REST and MCP

Read-only endpoints, protected by the existing `corpus:read` scope:

```text
GET /v1/documents/{document_id}/related?relation=all
GET /v1/documents/{document_id}/versions
```

Related views accept `similar`, `citations`, or `projects`, plus a bounded limit.
`license_classes` and `sources` accept repeated query values. Internal Python callers
can pass the full `RetrievalScope`; explicitly empty allowlists deny all results.
Missing and hidden seed documents return the same not-found outcome.

The actual MCP registry now includes `get_related_documents` and `get_document_versions`.
The existing `get_citations` tool also accepts source and license filters. One Agent
workflow is to search for a source, inspect project peers or explicit references, check
versions when currentness matters, and inspect the returned documents before composing
a multi-file answer. The existing `answer_question` tool supplies numbered citations
and refusal behavior; no new autonomous planner or external Agent deployment is claimed.
GenericAgent seed files remain unchanged. Do not treat an unresolved link or similarity
score as evidence for an answer.

## Verification limits

This stage uses an explicitly authorized, task-owned local PostgreSQL database, controlled
vectors/text, and the existing mock answer engine for interface checks. It does not download
a language model or call paid services. Database lifecycle, scope boundaries, migration
rollback, REST, and registered MCP functions are mechanically verifiable; they do not
establish semantic similarity quality or real-model multi-file answer quality.

The earlier six-file 3B extraction result remains 7/15 provisional target mentions.
Chinese keyword retrieval and routing have not been improved in this change. Do not
label the full priority-5/course acceptance complete from these component results.
Representative model evaluation, the Chinese keyword spike, external Agent operation,
full browsing, and automatic update triggers remain separate work. See [ADR 0016](adr/0016-scoped-document-relations.md).
