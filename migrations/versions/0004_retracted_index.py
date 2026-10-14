"""Index documents explicitly flagged as retracted by Crossref.

Retraction status is sparse enrichment metadata rather than a general
retrieval dimension, so it stays in ``documents.extra``. This partial
expression index makes the known-retracted subset cheap to identify without
turning every optional metadata field into a column.

``IF NOT EXISTS`` keeps this safe on fresh databases, where 0001 builds the
current model before later migrations run.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_retracted "
        "ON documents ((extra #>> '{crossref,is_retracted}')) "
        "WHERE extra #>> '{crossref,is_retracted}' = 'true'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_retracted")
