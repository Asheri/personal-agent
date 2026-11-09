# ADR 0021: Concurrency for graph extraction, with writes still serialized

Extraction used to be one model call at a time, which made a benchmark-wide graph
a 13-hour job even though the provider bills tokens and not seconds.

## Context

`extract_graph` awaited each batch before starting the next. On a hosted provider
that is the wrong shape: decode is what costs wall clock (measured at roughly 40
tokens/s per stream, 6,218 completion tokens per 10-chunk batch), and a single
stream leaves the provider's capacity and the account's per-minute budget unused.
Anyone weighting a benchmark build had to choose between a large corpus and a
finished run, and the documented conclusion was that benchmark-scale extraction
was a research task, not something an operator could switch on.

Two constraints bound the change. The document-write rule from ADR 0020 says one
writer mutates the corpus, and an entity name is not unique in the schema: two
batches that both meet "rice straw" must merge, not insert twice. So any overlap
has to keep the write phase serialized while the model calls overlap.

## Decision

Give `extract_graph` a `concurrency` parameter, surfaced as
`--concurrency` on `sci-rag graph extract` and `sci-rag build`, defaulting to 1 so
existing behavior and existing reports are unchanged.

Batches are cut up front from one query, so no two workers can pick the same
chunk. Each batch opens its own session and calls the model before touching the
database, then takes the existing transaction-scoped `pg_advisory_xact_lock`
before its lookups, upserts, and commit. Concurrent writes therefore queue one
batch at a time while the model calls run N-wide, and the stored graph does not
depend on the setting.

The pacing pause (`rate_limit_s`) applies to the serial path only. Once batches
overlap there is no "between batches" to pace, and the caller's quota is better
respected by choosing `concurrency` than by sleeping.

`build_communities` stays serial. It rebuilds every community in one transaction,
so its summaries cannot overlap without splitting that transaction, and the
number of clusters is small next to the chunk count.

## Consequences

Wall clock for a MultiHop-RAG-scale graph drops from about thirteen hours to about
one at eight in flight; the cost in provider tokens is identical, so this buys
time and not money. Both figures are arithmetic from the 20-article smoke run, not
a completed benchmark build.

The failure and recovery paths are unchanged: `_extract_with_recovery` still
splits an unusable batch and still leaves a failing chunk unstamped. Batches now
finish in an order that depends on the provider, so extraction logs and the order
of `created_at` timestamps are not reproducible; the graph content is, and
`tests/integration/test_graph_concurrency.py` asserts the same entities and
relationships at 1, 2, and 4 in flight.

A caller that raises concurrency past its account's tokens-per-minute ceiling gets
throttled responses. The client retries three times over three seconds, so an
overshoot shows up as failed batches; the run does not merely slow down. The flag is a
number the operator has to derive, and `docs/benchmark-catalogue.md` records the
formula.

`refresh` and the other programmatic callers keep the default of 1. Widening them
is a separate decision because refresh is the single-writer path that ADR 0020
deliberately kept serialized end to end.

## Reversal conditions

Revert to serial if any of these hold: two concurrent batches produce duplicate
entity rows in a test or an acceptance run; the writer lock is ever removed or
narrowed inside `_extract_batch`, since the merge depends on it covering the
lookup as well as the insert; or a provider starts billing per wall-clock second,
which would turn overlap into a cost rather than a saving.
