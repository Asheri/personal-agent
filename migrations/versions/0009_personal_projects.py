"""Add explicit project ownership and separate manual and automatic tags.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sci_rag.db.models import Project

    bind = op.get_bind()
    op.execute("SET CONSTRAINTS fk_documents_predecessor_identity IMMEDIATE")
    Project.__table__.create(bind, checkfirst=True)
    columns = {c["name"] for c in sa.inspect(bind).get_columns("documents")}
    if "project_id" not in columns:
        op.add_column("documents", sa.Column("project_id", sa.String(32), nullable=True))
        op.add_column("documents", sa.Column("project_source", sa.Text(), nullable=True))
        op.add_column(
            "documents",
            sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        )
        op.add_column(
            "documents",
            sa.Column(
                "auto_tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
            ),
        )
        op.create_foreign_key(
            "fk_documents_project_id", "documents", "projects", ["project_id"], ["id"]
        )
        op.create_check_constraint(
            "ck_documents_project_source",
            "documents",
            "(project_id IS NULL AND project_source IS NULL) OR (project_id IS NOT NULL AND project_source IS NOT NULL AND project_source IN ('manual','rule','inferred'))",
        )
        op.create_index("ix_documents_project_id", "documents", ["project_id"])
        op.create_index("ix_documents_tags", "documents", ["tags"], postgresql_using="gin")
        op.create_index(
            "ix_documents_auto_tags", "documents", ["auto_tags"], postgresql_using="gin"
        )
    op.execute("SET CONSTRAINTS fk_documents_predecessor_identity DEFERRED")


def downgrade() -> None:
    bind = op.get_bind()
    used = bind.scalar(
        sa.text(
            "SELECT count(*) FROM documents WHERE project_id IS NOT NULL OR cardinality(tags)>0 OR cardinality(auto_tags)>0"
        )
    )
    projects = bind.scalar(sa.text("SELECT count(*) FROM projects"))
    if used or projects:
        raise RuntimeError(
            "0009 downgrade would discard projects or tags. Keep a database backup and explicitly convert the data. No rows were deleted."
        )
    op.execute("SET CONSTRAINTS fk_documents_predecessor_identity IMMEDIATE")
    op.drop_constraint("fk_documents_project_id", "documents", type_="foreignkey")
    op.drop_constraint("ck_documents_project_source", "documents", type_="check")
    for name in ("ix_documents_project_id", "ix_documents_tags", "ix_documents_auto_tags"):
        op.drop_index(name, table_name="documents")
    for name in ("project_id", "project_source", "tags", "auto_tags"):
        op.drop_column("documents", name)
    op.drop_table("projects")
    op.execute("SET CONSTRAINTS fk_documents_predecessor_identity DEFERRED")
