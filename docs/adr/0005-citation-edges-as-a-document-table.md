---
title: "ADR 0005: Citation edges in their own table"
description: Why a citation is not the kind of edge the knowledge graph stores, and where it goes instead.
---

# ADR 0005: Citation edges in their own table

Citations between documents live in `document_citations`, their own table. The knowledge graph stays a graph of concepts.

**Status:** accepted

## Context

Wave 2 adds a citation graph: when document A's reference list names
document B and both are in the corpus, retrieval should be able to walk
from A to B. The knowledge graph already stores edges, so the cheap move
would be to reuse it.

It does not fit. `kg_relationships` is entity-to-entity by contract:
`source_entity_id` and `target_entity_id` are foreign keys into
`kg_entities`, the relation type must be one of the domain ontology's
declared types, and each row carries the chunk and the quoted phrase that
states it. A citation has none of those properties. It is
document-to-document, its type is always the same, and its evidence is a
DOI match in a reference list rather than a sentence someone wrote.

The alternative that would preserve the table is a synthetic entity per
document. That buys the reuse, and it pays for it three times over.
`search_entities` starts returning paper titles alongside concepts.
Community detection clusters documents with concepts and writes summaries
about the mixture. And `graph gc` has to learn that some entities may be
evidence-less, because they were never evidence-bearing to begin with.

## Decision

Citations get their own table, `document_citations`:

* `citing_document_id` and `cited_document_id`, both foreign keys into
  `documents` with `ON DELETE CASCADE`
* `cited_doi`, the DOI as printed in the reference list, kept so an
  unresolved reference can be re-resolved later when its target is
  ingested
* `source`, the provenance of the edge (`crossref` today; a reference
  parser later)
* a unique constraint on the pair, and indexes on both directions

Only edges **between documents present in the corpus** are stored. A
reference to a paper nobody ingested is not a graph edge, it is a dangling
pointer, and the corpus should not carry pointers it cannot resolve.

Citation traversal joins the existing graph stage as an optional
expansion, and not a sixth retrieval layer. Two reasons. The
fusion weights, the router, and the public trace contract all enumerate
five layers. And a citation walk is a variant of "walk from here to
related evidence", not a new kind of evidence.

## Consequences

* `corpus delete` and `graph gc` must clean this table up. The FK cascade
  handles deletion of either endpoint; GC sweeps rows whose endpoints
  vanished by other means. The every-layer unreachability regression test
  in `tests/integration/test_corpus_delete.py` grows a citation case.
* MCP gains `get_citations(document_id)`, which reads this table
  directly in both directions (cites out, cited by).
* The reference list of a document not yet fully resolved is not lost:
  `cited_doi` rows can be re-resolved against the corpus after a later
  ingest, without re-fetching Crossref.
* The knowledge graph stays a graph of concepts. That was the point of
  ADR 0001, and this keeps it true.

## Reversal conditions

* The domain ontology gains a document-level entity type for reasons of
  its own, at which point a citation would be an ordinary edge between
  two entities the ontology already declares.
* Citation traversal needs to run in the same recursive query as concept
  traversal, and the join across two tables becomes the bottleneck. Show
  the query plan first.
