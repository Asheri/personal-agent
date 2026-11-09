# ADR 0018: Validate model names, endpoint types, and literal provenance

A valid JSON graph can still contain invented aliases, reversed relationships,
and evidence attributed to another passage. Reject those unsupported outputs
before they enter the graph.

## Context

Real-model controlled trials exposed canonical-name drift, reversed AUTHORED_BY
edges, unrelated projects merged as aliases, and quotes absent from their cited
passage. Interface and database tests alone did not reveal these quality failures.

## Decision

Add optional ontology contracts for canonical suffixes with minimum stem length
and allowed relation source/target types. The personal profile declares project
and method suffix rules and endpoint types for authorship, membership, use, and
production. Name normalization redirects response-local endpoints and retains the
original name as a source-checked alias. A four-character method-stem minimum
preserves short professional names such as the tested biotechnology term.

Drop generic document pronouns and remove outer book-title marks from Document
names. Reject mismatched endpoint types; do not reverse an edge automatically.
Validate each entity against its claimed passages and retain only literal aliases.
Require a relationship's quoted evidence and both endpoints in its claimed
passage. Whitespace and letter case are normalized; words and punctuation are not
rewritten. Rejections contribute to entity, alias, or relationship counters.

Use one chunk per extraction call for the measured local 7B configuration. This
uses the existing CLI batch-size option, without changing global defaults. Retain
few-shot examples from different named projects than the scored corpus.

## Consequences

Strict validation can reduce recall and cannot verify a relationship's meaning
or an alias's referent merely because words occur in a source. Source-defined
synonyms and indirect references may need review. The suffix policy is a domain
convention, not a universal linguistic rule; source aliases preserve original names.
The shipped demo profile has no suffix/type restrictions, but literal provenance
validation applies to all extraction domains. Existing scripted tests now quote
their actual fixture text and attribute its actual numbered passage.

Previously stored invalid graph rows are not retroactively repaired. Back up a
real deployment and use the documented explicit graph rebuild after reviewing
this candidate. This stage resets only its disposable acceptance database.

## Reversal conditions

Revisit constraints if a human-reviewed corpus exposes systematic false rejections
or conflated names. Preserve rejection receipts and raw responses before changing
the policy. Any relaxation needs matched correctness and scope checks and a real
nonauthor review. Never replace failed evidence with an invented quote or silently
flip a relation to improve a metric.
