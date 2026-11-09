# Identity and versions: development verification handoff

- Date: 2026-10-24.
- Authoring and verification: AI-assisted implementation.
- Independent nonauthor group reviewer: unassigned.
- Status: implementation and v1.2 candidate pending formal group review.
- Scope: C-1 through C-5; scoped storage revision 0008; A3-6 through A3-8,
  A4-6, A6-2, and interruption/current-evidence tests.

The v1.2 candidate is `../2026-10-24-identity-version-spec-v1.2.md`.
ADR 0014 records identity, atomic current-row changes, and the rollback guard.
The previously reviewed v1.1 files remain historical evidence. This handoff does
not assert approval, a merge, or completion of the full M-0008-R or F6 tasks.

## Evidence

The three initial database regressions failed on the inherited implementation:
source copies collapsed, a revert skipped its third revision, and member identities
collapsed. New PostgreSQL tests cover atomic rollback, concurrent ingestion,
current-only candidate limits, old graph bridges, aggregate invalidation, deletion
reconnection, and fresh/legacy upgrade and downgrade paths.

Exact executed commands, timestamps, logs, JUnit, baseline comparison, and skips are
in `.context/identity-versions-20261024/verification-summary.json` and adjacent files.
The fresh unit baseline is 1574 passes, 8 failures, and 41 skips on Python 3.12.14.
Five failures require missing Git history, one reports documented unimplemented
commands, and two require the missing Git chmod executable. Full-project mypy has
the existing `embed/google.py:117` error. Only actual final evidence may be reported
as passing; the historical Office counts are not a substitute for this run.

## Review focus and limits

Check identity normalization and member isolation, hash collisions at the content
comparison layer, version indexes and composite foreign keys, transaction interruption,
default versus explicit historical scope, and aggregate provenance. Check that safe
rollback preserves data and incompatible rollback fails before any destructive change.
The inventory fingerprint must never be described as a restorable database backup.

The shared transaction lock serializes writers and aggregate rebuilds. Unknown legacy
paths remain separate; recorded ingestion order is not verified original edit order.
Historical documents are retained, while historical graph descriptions are not temporal
snapshots. Filesystem reconciliation, project classification, and scheduled updates
remain open. No real private corpus, paid model, or existing database is used.

AGENTS.md section 5 requires a real nonauthor reviewer to record their own commands,
identity, findings, and decision. The included AI development evidence is not a signature.

Reference implementation: [SQLAlchemy versioned rows](https://github.com/sqlalchemy/sqlalchemy/blob/main/examples/versioned_rows/versioned_rows_w_versionid.py).
