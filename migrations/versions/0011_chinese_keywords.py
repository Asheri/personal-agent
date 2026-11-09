"""Backfilled, locale-independent Chinese keyword index.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

from sci_rag.keyword_tokens import index_chinese

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # The historical 0001 migration creates the live ORM metadata on fresh DBs.
    columns = {c["name"] for c in sa.inspect(bind).get_columns("chunks")}
    if "search_tokens" not in columns:
        op.add_column(
            "chunks", sa.Column("search_tokens", sa.Text(), nullable=False, server_default="")
        )
    last = ""
    while rows := bind.execute(
        sa.text("SELECT id,content FROM chunks WHERE id > :last ORDER BY id LIMIT 500"),
        {"last": last},
    ).all():
        bind.execute(
            sa.text("UPDATE chunks SET search_tokens=:tokens WHERE id=:id"),
            [{"id": row.id, "tokens": index_chinese(row.content)} for row in rows],
        )
        last = rows[-1].id
    if "search_zh_tsv" not in columns:
        op.add_column(
            "chunks",
            sa.Column(
                "search_zh_tsv",
                sa.dialects.postgresql.TSVECTOR(),
                sa.Computed("to_tsvector('simple', search_tokens)", persisted=True),
            ),
        )
    if "ix_chunks_search_zh_tsv" not in {i["name"] for i in sa.inspect(bind).get_indexes("chunks")}:
        op.create_index(
            "ix_chunks_search_zh_tsv", "chunks", ["search_zh_tsv"], postgresql_using="gin"
        )


def downgrade() -> None:
    # Only a reproducible search cache is removed. Content and graph data survive.
    op.drop_index("ix_chunks_search_zh_tsv", table_name="chunks")
    op.drop_column("chunks", "search_zh_tsv")
    op.drop_column("chunks", "search_tokens")
