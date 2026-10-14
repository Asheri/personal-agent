"""Add corpus-local Crossref citation pointers.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS document_citations ("
        "id VARCHAR(32) PRIMARY KEY, "
        "citing_document_id VARCHAR(32) NOT NULL REFERENCES documents(id) ON DELETE CASCADE, "
        "cited_document_id VARCHAR(32) REFERENCES documents(id) ON DELETE CASCADE, "
        "cited_doi TEXT NOT NULL, "
        "source TEXT NOT NULL DEFAULT 'crossref', "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_document_citations_pair "
        "UNIQUE (citing_document_id, cited_document_id), "
        "CONSTRAINT uq_document_citations_reference "
        "UNIQUE (citing_document_id, cited_doi, source))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_citations_citing "
        "ON document_citations (citing_document_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_citations_cited "
        "ON document_citations (cited_document_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_citations_doi ON document_citations (cited_doi)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_citations")
