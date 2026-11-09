# Chinese retrieval and model quality review

- Date: 2026-10-25.
- Author: Codex implementation; independent reviewer: pending.
- Status: awaiting nonauthor review, no approval or merge implied.
- Scope: v1.6 candidate; specification sections 3, 4.2, 4.4, 5; C-4/C-5,
  C-6/C-7; A2 and A4.

The implementation author's checks and raw evidence are in
`.context/chinese-quality-20261025/`. An independent reviewer must classify
findings as P0, P1, or P2 and record a decision before adoption.

Check the stronger Chinese gate against the reviewed specification, verify
scope predicates before limits, inspect existing-data backfill and safe rollback,
and distinguish controlled model scoring from human-reviewed business accuracy.
Read actual answers and their sources; term and citation checks alone can pass
an incorrect statement. Confirm owned services and disposable data were cleaned
after evidence was archived. This template is not an independent review.
