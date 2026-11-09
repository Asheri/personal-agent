# Core engineering review

- Date: 2026-10-26.
- Author: Codex implementation; independent reviewer: pending.
- Status: template only; no approval or merge.
- Scope: candidate v1.8; sections 3, 4.4-4.7, 5; C-10 to C-13; A4-A7.

Check migration/backfill/rollback, all scope fields, external metadata/alternate
read paths, null bucket sums, stable pagination, refresh lock and interruption
semantics, memory provenance/patches, and unchanged Agent seeds. Verify every
matrix claim against its actual run, distinguish controlled handler tests from
a live model conversation, and confirm cleanup and package checksums.
