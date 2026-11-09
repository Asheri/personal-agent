"""Separate source identity from content equality and retain revisions.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import posixpath
from collections import defaultdict
from pathlib import PureWindowsPath

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _recorded_path(extra: dict, source_ref: str | None) -> str | None:
    for value in (extra.get("path"), source_ref):
        if not isinstance(value, str) or "://" in value:
            continue
        if PureWindowsPath(value).is_absolute():
            return ntpath.normcase(ntpath.normpath(value))
        if value.startswith("/"):
            return posixpath.normpath(value)
    return None


def upgrade() -> None:
    bind = op.get_bind()
    original = {c["name"] for c in sa.inspect(bind).get_columns("documents")}
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS uq_documents_content_hash")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS identity_key VARCHAR(64)")
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS version_seq INTEGER NOT NULL DEFAULT 1"
    )
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS version_of VARCHAR(32)")
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true"
    )
    if "identity_key" not in original:
        rows = (
            bind.execute(
                sa.text("SELECT id, source_ref, extra FROM documents ORDER BY ingested_at, id")
            )
            .mappings()
            .all()
        )
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            extra = dict(row["extra"] or {})
            path = _recorded_path(extra, row["source_ref"])
            member = extra.get("source_member", "")
            if path is not None and isinstance(member, str):
                identity = hashlib.sha256(
                    json.dumps([path, member], ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                extra.update(path=path, source_member=member, identity_origin="recorded_path")
            else:
                identity = hashlib.sha256(("legacy:" + row["id"]).encode("utf-8")).hexdigest()
                extra["identity_origin"] = "legacy_unresolved"
            groups[identity].append({"id": row["id"], "extra": extra})
        for identity, chain in groups.items():
            for index, row in enumerate(chain):
                bind.execute(
                    sa.text(
                        "UPDATE documents SET identity_key=:identity, version_seq=:seq, "
                        "version_of=:previous, is_current=:current, extra=CAST(:extra AS JSONB) WHERE id=:id"
                    ),
                    {
                        "identity": identity,
                        "seq": index + 1,
                        "previous": chain[index - 1]["id"] if index else None,
                        "current": index == len(chain) - 1,
                        "id": row["id"],
                        "extra": json.dumps(row["extra"], ensure_ascii=False),
                    },
                )
        if any(len(chain) > 1 for chain in groups.values()):
            op.execute("DELETE FROM kg_communities")
    op.execute("ALTER TABLE documents ALTER COLUMN identity_key SET NOT NULL")
    op.execute("ALTER TABLE documents ALTER COLUMN identity_key SET DEFAULT md5(random()::text)")
    inspector = sa.inspect(bind)
    uniques = {c["name"] for c in inspector.get_unique_constraints("documents")}
    if "uq_documents_id_identity" not in uniques:
        op.create_unique_constraint("uq_documents_id_identity", "documents", ["id", "identity_key"])
    if "uq_documents_identity_seq" not in uniques:
        op.create_unique_constraint(
            "uq_documents_identity_seq", "documents", ["identity_key", "version_seq"]
        )
    if "fk_documents_predecessor_identity" not in {
        c["name"] for c in inspector.get_foreign_keys("documents")
    }:
        op.create_foreign_key(
            "fk_documents_predecessor_identity",
            "documents",
            "documents",
            ["version_of", "identity_key"],
            ["id", "identity_key"],
            deferrable=True,
            initially="DEFERRED",
        )
    checks = {c["name"] for c in inspector.get_check_constraints("documents")}
    if "ck_documents_version_seq" not in checks:
        op.create_check_constraint("ck_documents_version_seq", "documents", "version_seq > 0")
    if "ck_documents_predecessor_seq" not in checks:
        op.create_check_constraint(
            "ck_documents_predecessor_seq", "documents", "version_of IS NULL OR version_seq > 1"
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_current_identity ON documents (identity_key) WHERE is_current"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_version_of ON documents (version_of) WHERE version_of IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)")


def downgrade() -> None:
    bind = op.get_bind()
    incompatible = bind.scalar(
        sa.text(
            "SELECT count(*) FROM documents WHERE NOT is_current OR version_seq <> 1 OR version_of IS NOT NULL"
        )
    )
    duplicates = bind.scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT content_hash FROM documents GROUP BY content_hash HAVING count(*) > 1) copies"
        )
    )
    if incompatible or duplicates:
        raise RuntimeError(
            "0008 downgrade would discard revision history or source copies. "
            "Keep a database backup and explicitly convert the data before retrying. No rows were deleted."
        )
    op.drop_constraint("fk_documents_predecessor_identity", "documents", type_="foreignkey")
    for name in (
        "uq_documents_current_identity",
        "uq_documents_version_of",
        "ix_documents_content_hash",
    ):
        op.drop_index(name, table_name="documents")
    for name in ("uq_documents_identity_seq", "uq_documents_id_identity"):
        op.drop_constraint(name, "documents", type_="unique")
    for name in ("ck_documents_version_seq", "ck_documents_predecessor_seq"):
        op.drop_constraint(name, "documents", type_="check")
    for name in ("version_of", "version_seq", "is_current", "identity_key"):
        op.drop_column("documents", name)
    op.create_unique_constraint("uq_documents_content_hash", "documents", ["content_hash"])
