---
title: "ADR 0001: The graph lives in Postgres"
description: Why entities, relationships, and communities are rows in the same database as the chunks, and what that costs.
---

# ADR 0001: The graph lives in Postgres

Entities, relationships, and communities are rows in the same PostgreSQL database as the chunks they came from. There is no second database.

**Status:** accepted

## Context

GraphRAG designs usually reach for Neo4j or a Postgres graph extension
(Apache AGE). This kit stores entities, relationships, and communities
as plain rows in the same Postgres database as everything else, and
traverses with a recursive CTE.

## Decision

Postgres-native, no graph engine, for three reasons:

1. **The workload does not need one.** The methodology's only traversal
   is a two-hop neighborhood walk from a handful of seed entities, then
   a jump back to evidence chunks. That is a recursive CTE over indexed
   foreign keys, comfortably fast at the scale a domain corpus produces
   (hundreds to low tens of thousands of entities). Graph engines earn
   their keep on deep, unbounded traversals we never issue.
2. **Operational surface is the real cost.** A second database means a
   second backup story, second migration story, second access-control
   model, and a consistency boundary between the graph and the chunks it
   references. For a template meant to be run by small scientific
   groups, one database is a feature.
3. **Transactionality.** A chunk and its graph entries commit together.

## Consequences

* Deep multi-hop analytics, meaning path queries and centrality, are out
  of scope. A project that needs them should export the two tables to a
  graph tool for analysis rather than move the operational store.
* The replacement boundary is narrow: the graph layer is one stage behind the retrieval
  facade. Swapping in a graph engine later means reimplementing one
  stage, not the kit.

## Reversal conditions

* A corpus reaches millions of entities, where a two-hop recursive query
  over indexed foreign keys stops being comfortably fast.
* The product needs traversal three or more hops deep at query time, or
  needs centrality and path analytics as a live feature and not as an
  export.

Either one means reimplementing the graph stage behind the retrieval
facade. It does not mean moving the chunks.
