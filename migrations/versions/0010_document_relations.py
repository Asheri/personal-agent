"""Document vector means and source-attributed mention references.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sci_rag.db.models import DocumentEmbedding

    bind = op.get_bind()
    DocumentEmbedding.__table__.create(bind, checkfirst=True)
    chunk_dimension = bind.scalar(
        sa.text(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid='chunks'::regclass AND attname='embedding'"
        )
    )
    mean_dimension = bind.scalar(
        sa.text(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid='document_embeddings'::regclass AND attname='embedding'"
        )
    )
    if not isinstance(chunk_dimension, int) or chunk_dimension <= 0:
        raise RuntimeError("Cannot determine the persisted chunk vector dimension")
    if mean_dimension != chunk_dimension:
        # These are reproducible caches, not source documents or citation evidence.
        op.execute("DELETE FROM document_embeddings")
        op.execute(
            f"ALTER TABLE document_embeddings ALTER COLUMN embedding TYPE vector({chunk_dimension}) USING NULL::vector({chunk_dimension})"
        )
    op.execute("""DELETE FROM document_embeddings means WHERE
        NOT EXISTS (SELECT 1 FROM chunks c WHERE c.document_id=means.document_id)
        OR EXISTS (SELECT 1 FROM chunks c WHERE c.document_id=means.document_id
            AND (c.embedding IS NULL OR c.embedding_version IS DISTINCT FROM means.embedding_version))""")
    columns = {c["name"] for c in sa.inspect(bind).get_columns("document_citations")}
    if "cited_key" not in columns:
        op.alter_column("document_citations", "cited_doi", nullable=True)
        op.add_column("document_citations", sa.Column("cited_key", sa.Text(), nullable=True))
        op.add_column(
            "document_citations", sa.Column("evidence_chunk_id", sa.String(32), nullable=True)
        )
        op.add_column("document_citations", sa.Column("confidence", sa.Float(), nullable=True))
        op.create_foreign_key(
            "fk_document_citations_evidence",
            "document_citations",
            "chunks",
            ["evidence_chunk_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_unique_constraint(
            "uq_document_citations_key", "document_citations", ["citing_document_id", "cited_key"]
        )
        op.create_check_constraint(
            "ck_document_citations_target",
            "document_citations",
            "cited_doi IS NOT NULL OR cited_document_id IS NOT NULL OR cited_key IS NOT NULL",
        )
        op.create_check_constraint(
            "ck_document_citations_mention",
            "document_citations",
            "source <> 'mention' OR (cited_key IS NOT NULL AND evidence_chunk_id IS NOT NULL AND confidence IS NOT NULL AND confidence >= 0 AND confidence <= 1)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM document_embeddings")) or bind.scalar(
        sa.text(
            "SELECT count(*) FROM document_citations WHERE cited_doi IS NULL OR cited_key IS NOT NULL OR evidence_chunk_id IS NOT NULL OR confidence IS NOT NULL"
        )
    ):
        raise RuntimeError(
            "0010 downgrade would discard relation data. Back up and explicitly convert or rebuild it first; no data was deleted."
        )
    for name, kind in [
        ("ck_document_citations_mention", "check"),
        ("ck_document_citations_target", "check"),
        ("uq_document_citations_key", "unique"),
    ]:
        op.drop_constraint(name, "document_citations", type_=kind)
    foreign_keys = sa.inspect(bind).get_foreign_keys("document_citations")
    for key in foreign_keys:
        if key["constrained_columns"] == ["evidence_chunk_id"]:
            op.drop_constraint(key["name"], "document_citations", type_="foreignkey")
    for column in ["confidence", "evidence_chunk_id", "cited_key"]:
        op.drop_column("document_citations", column)
    op.alter_column("document_citations", "cited_doi", nullable=False)
    op.drop_table("document_embeddings")
