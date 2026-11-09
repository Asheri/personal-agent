# Core engineering candidate v1.8

This serial candidate supplements v1.7. The reviewed v1.1 baseline remains intact.
Independent review/adoption and course report/slides/demo are excluded this stage.
Optional P6 research remains outside the stated course-engineering scope.

## Affected contracts

Specification sections 3, 4.4-4.7, and 5; C-10/C-11/C-12/C-13; A4 date filtering,
A5 browsing, A6 trigger/history behavior, and A7 memory. Earlier identity, parser,
ownership, and relation decisions remain as recorded in their dated candidates.

Revisions 0012/0013 add document-date/access columns, token backfill, and refresh
events. Date sources follow C-11. Scope fields and their coverage meta-test now
include dates, projects, tags, automatic tags, and entity names. Facets count current
in-scope evidence; named topics and community overviews remain separate.

## Behavior and departures

English keyword queries gain a simple-index fallback; Latin-only sources enter
that index. A matched boundary spike records recall and latency before/after.
No fusion weights or default domain files change.

External MCP tools enforce external-safe rights even for metadata, versions,
relations, and explicit caller filters. This closes the earlier permissive defaults.
REST remains the local operator catalog. Community text/counts are suppressed for
restricted scopes; this is explicit degradation instead of unscoped aggregation.

Refresh holds one lock through reconciliation and derived updates. A running
audit marker survives interruption and is reclassified on restart. Paths are hashed
in persisted events. A7 procedures are confirmed templates created after three
successful tasks; they do not claim unrestricted model-driven self-improvement.
Memory hot-pointer edits retain patches and preserve surrounding rules.

## Evidence

See the [engineering matrix](../../engineering-requirements.md) and
`.context/core-completion-20261026/`. Keep matched keyword results, negative privacy
tests, pagination/null buckets, real migration round trips, trigger/lock/recovery
checks, actual pinned upstream protocols, memory patches, polling measurements,
and full regression results. Declared skips are not passes.

## Adoption

The dated [review template](reviews/2026-10-26-core-completion-review.md) is pending.
No author approval, project merge, production corpus ingestion, persistent OS task,
or live model conversation is implied. User-specific deployment configuration and
independent human course assessment remain explicit operational/review boundaries.
