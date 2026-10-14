"""Give documents a first-class journal column, and index the metadata filters.

v0.3 extends the retrieval scope with publication year, author, journal,
and DOI filters, all enforced inside every layer's SQL. Journal was the
one dimension with nowhere to live: putting it in ``Document.extra``
would have meant filtering on JSONB in the hot path of five queries. It
becomes a real column, with an index, alongside an index on
``publication_year`` for the year-range condition.

``IF NOT EXISTS`` keeps this a no-op on fresh databases, where 0001's
``create_all`` already created both from the current models.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-27

"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS journal TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_journal ON documents (journal)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_publication_year ON documents (publication_year)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_publication_year")
    op.execute("DROP INDEX IF EXISTS ix_documents_journal")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS journal")
