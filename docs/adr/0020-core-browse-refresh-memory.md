# ADR 0020: Complete scoped browsing, refresh, and Agent memory

The remaining course engineering needs one set of scope predicates and one refresh
writer across local tools, scheduled jobs, and Agent hooks.

## Context

V1.7 lacked first-class document dates, full browse surfaces, automatic trigger
entry points, and implemented memory routes. Its language dispatch missed some
identifiers, and external MCP defaults could expose unknown-rights sources.

## Decision

Add revisions 0012/0013 for indexed dates/access metadata, universal token backfill,
and content-free refresh events. Share browse/facet/topic predicates with retrieval.
Keep explicit null buckets and deterministic date/ingestion/id ordering. Retain
English stemming with a simple-index fallback instead of changing fusion weights.

Hold the existing advisory lock across one refresh orchestration. All three
trigger channels use that operation; no new watcher or job queue is introduced.
Provide tested launchers and upstream scheduler definitions without modifying
GenericAgent seed files or registering persistent tasks during acceptance.

Keep memory pointer-only. Derive access and stale metadata from actual operations,
retain old evidence, patch only managed memory blocks, and require three confirmed
tasks before a reusable procedure is recorded. Intersect every external MCP read
with external-safe license classes, including metadata and alternate read paths.
Apply the same default to CLI exports and keep access telemetry out of exported
columns. The trusted internal library export remains an operator API.

## Consequences

Existing data needs a backfill and a coordinated application/schema upgrade.
External MCP defaults are intentionally narrower; clients requesting private
sources receive no data. Scoped community aggregates are disabled because their
source mixtures cannot be filtered afterward. Local operator REST reads remain
separate from this external boundary.

Offline refresh explicitly disables model-dependent inference. Access telemetry
is best-effort for read-only hosts. Constructed protocol and timing checks do not
validate live model behavior, a personal corpus, arbitrary skill learning, or
large-directory performance. Review/adoption and course deliverables remain open.

## Reversal conditions

Revisit the one-shot polling choice only after measured discovery latency or
directory cost justifies a watcher and a recovery design. Any broader external
rights policy requires explicit authorization and matching negative tests.
Change memory learning beyond confirmed templates only with a separate evaluation
protocol. Preserve failed trials and the requirement matrix before relaxing gates.
