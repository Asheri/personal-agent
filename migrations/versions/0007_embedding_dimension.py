"""Resize both pgvector columns to the configured embedding dimension.

运行本迁移前必须先备份数据库。迁移会清空所有向量和版本戳, 再重建
``ix_chunks_embedding_hnsw``, 因此不会保留或静默混用不同维度的向量。

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_VECTOR_COLUMNS = (
    ("chunks", "embedding"),
    ("kg_communities", "summary_embedding"),
)
_COLUMN_TYPE_SQL = text(
    "SELECT format_type(a.atttypid, a.atttypmod) "
    "FROM pg_attribute a "
    "WHERE a.attrelid = to_regclass(:table) AND a.attname = :column AND a.attnum > 0"
)


def _configured_dimension() -> int:
    raw = os.environ.get("SCI_RAG_EMBEDDING_DIM")
    if raw is None:
        from sci_rag.config import get_settings

        raw = str(get_settings().embedding_dim)
    try:
        dimension = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"SCI_RAG_EMBEDDING_DIM must be between 32 and 1024; received {raw!r}."
        ) from exc
    if not 32 <= dimension <= 1024:
        raise RuntimeError(
            f"SCI_RAG_EMBEDDING_DIM must be between 32 and 1024; received {dimension}."
        )
    return dimension


def _vector_types(bind) -> dict[tuple[str, str], str | None]:  # type: ignore[no-untyped-def]
    return {
        (table, column): bind.execute(
            _COLUMN_TYPE_SQL, {"table": table, "column": column}
        ).scalar_one_or_none()
        for table, column in _VECTOR_COLUMNS
    }


def _drop_vector_indexes() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_kg_communities_summary_embedding_hnsw")


def _create_chunk_hnsw_index() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def _resize_vector_columns(dimension: int) -> None:
    bind = op.get_bind()
    expected = f"vector({dimension})"
    current = _vector_types(bind)
    missing = [f"{table}.{column}" for (table, column), kind in current.items() if kind is None]
    if missing:
        raise RuntimeError("Cannot resize missing vector column(s): " + ", ".join(missing))

    _drop_vector_indexes()
    op.execute("UPDATE chunks SET embedding = NULL, embedding_version = NULL")
    op.execute(
        "UPDATE kg_communities SET summary_embedding = NULL, summary_embedding_version = NULL"
    )
    for table, column in _VECTOR_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {expected} USING NULL::{expected}"
        )
    _create_chunk_hnsw_index()


def upgrade() -> None:
    """把两个向量列迁移到 32 到 1024 范围内的配置维度。

    运行前必须备份数据库。旧向量和版本戳会先失效, 任何失败都会让
    Alembic 事务回滚并显示错误, 不会留下静默混合的宽度。
    """
    _resize_vector_columns(_configured_dimension())


def downgrade() -> None:
    """恢复旧的 1536 维 schema, 同时继续禁止保留旧向量。

    运行前必须备份数据库。先失效向量和版本戳, 再改型并重建旧索引。
    """
    _resize_vector_columns(1536)
