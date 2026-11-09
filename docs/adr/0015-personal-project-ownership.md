# ADR 0015: Personal project ownership and extraction receipts

Keep explicit document ownership separate from mentioned Project entities, and retain
evidence for automatic decisions. This decision is pending nonauthor group review.

## Context

The personal ontology and draft prompts existed, but ownership and tag passes had no
caller. Their prompts did not include source text. Exact-name entity enrichment lacked
the specification's audit receipt, and rejected entities were not counted. The personal
profile also lacked shared runtime prompts, preventing its graph-query path from running.
Garbage collection removes ghosts, not a valid graph built under an earlier ontology.

## Decision

Add projects and explicit document ownership/tag columns in revision 0009. Enforce the
manual/rule/inferred source contract and keep manual ownership across source revisions.
Validate inferred projects against existing ids/names, confidence, and quoted source
evidence. Preserve prior decisions on failures and keep manual/automatic tags separate.
Resolve ordered directory globs before inference; never infer redistribution rights.

Reuse the upstream runtime templates without changing the protected demo profile.
Connect the two personal metadata prompts to actual source heads. Record exact-name
receipts, rejection counts, and a domain digest. Recheck current evidence before graph
writes, conservatively gate model calls by declared rights, and omit exception contents
from operational logs. Provide an explicit confirmed graph reset for ontology changes.

## Consequences

Manual choices remain stable while automatic decisions are inspectable. Shared entities
have source pointers and same-name receipts. Model calls and revision writes remain
serialized where needed, so slow metadata calls can delay other writers. Same-name
people can still be incorrectly merged. The conservative rights gate also skips unknown
material on local endpoints; an explicit trusted-local policy is not implied.

The small synthetic real-model run demonstrates wiring and evidence paths, not general
extraction accuracy. Its labels remain provisional. Project browsing, filesystem events,
and scheduling are outside this change. Downgrade refuses project/tag loss.

## Reversal conditions

Revisit single-owner grouping only if real course examples require multiple projects
per file. Add person disambiguation when measured same-name errors justify it. Revise
the inference threshold or concurrency model only with paired evidence and a new review.
Any private-local inference policy must remain explicit and must not bypass rights or
privacy checks by changing license labels.
