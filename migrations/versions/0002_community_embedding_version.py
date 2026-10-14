"""Stamp community summaries with their embedding version.

Chunks have carried ``embedding_version`` since 0001; community summary
embeddings did not, which left ``sci-rag embed reindex`` unable to tell a
current summary vector from one produced by a retired model. NULL in the
new column reads as stale on purpose: every summary embedded before this
migration gets picked up by the next reindex.

``IF NOT EXISTS`` keeps this a no-op on fresh databases, where 0001's
``create_all`` already created the column from the current models.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27

"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE kg_communities ADD COLUMN IF NOT EXISTS summary_embedding_version TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE kg_communities DROP COLUMN IF EXISTS summary_embedding_version")
