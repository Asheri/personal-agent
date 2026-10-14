"""Add canonical entity tombstones and the resolution audit log.

``IF NOT EXISTS`` keeps the migration safe for fresh databases because
0001 creates current model metadata before the later migrations run.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE kg_entities ADD COLUMN IF NOT EXISTS canonical_entity_id VARCHAR(32)")
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE kg_entities ADD CONSTRAINT fk_kg_entities_canonical_entity_id "
        "FOREIGN KEY (canonical_entity_id) REFERENCES kg_entities(id) ON DELETE SET NULL; "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kg_entities_canonical_entity_id "
        "ON kg_entities (canonical_entity_id)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS entity_resolution_audit ("
        "id VARCHAR(32) PRIMARY KEY, "
        "merged_entity_id VARCHAR(32) NOT NULL, "
        "merged_entity_name TEXT NOT NULL, "
        "surviving_entity_id VARCHAR(32) NOT NULL, "
        "surviving_entity_name TEXT NOT NULL, "
        "method TEXT NOT NULL, "
        "confidence DOUBLE PRECISION NOT NULL, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entity_resolution_audit_merged "
        "ON entity_resolution_audit (merged_entity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entity_resolution_audit_surviving "
        "ON entity_resolution_audit (surviving_entity_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS entity_resolution_audit")
    op.execute("DROP INDEX IF EXISTS ix_kg_entities_canonical_entity_id")
    op.execute(
        "ALTER TABLE kg_entities DROP CONSTRAINT IF EXISTS fk_kg_entities_canonical_entity_id"
    )
    op.execute("ALTER TABLE kg_entities DROP COLUMN IF EXISTS canonical_entity_id")
