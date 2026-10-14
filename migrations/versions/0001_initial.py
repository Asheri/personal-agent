"""Initial schema: documents, chunks, and the knowledge graph.

Creates the pgvector extension and every table defined in
``sci_rag.db.models``, including the HNSW and full-text indexes. The
embedding dimension is read from settings (``SCI_RAG_EMBEDDING_DIM``,
default 1536) at the moment this migration runs, so decide your dimension
before the first upgrade.

Revision ID: 0001
Revises:
Create Date: 2026-08-26

"""

from __future__ import annotations

from alembic import op

from sci_rag.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
