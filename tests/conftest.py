"""Test configuration.

The environment is pinned BEFORE any sci_rag import: the embedding column
dimension is baked into the models at import time, and tests use a small
dimension (64) with the deterministic local-hash embedder so the whole
suite runs offline.

Integration tests need Postgres. Point SCI_RAG_TEST_DATABASE_URL at any
Postgres with the pgvector extension available (the repo's
Docker, local, and cloud development backends all work); if it is unreachable,
integration tests skip with a clear message instead of failing.
"""

from __future__ import annotations

import os

os.environ.setdefault("SCI_RAG_EMBEDDING_PROVIDER", "local-hash")
os.environ.setdefault("SCI_RAG_EMBEDDING_DIM", "64")
os.environ["SCI_RAG_DATABASE_URL"] = os.environ.get(
    "SCI_RAG_TEST_DATABASE_URL",
    "postgresql+asyncpg://sci_rag:sci_rag@localhost:5433/sci_rag_test",
)
# Never let a developer's real .env leak into tests.
os.environ.setdefault("SCI_RAG_GOOGLE_API_KEY", "")
os.environ.setdefault("SCI_RAG_GCP_PROJECT", "")

# 测试同时固定当前 provider 和模型默认值。只固定 `DEFAULT_LLM_MODEL`
# 而保留旧的 Google provider 会形成 mixed provider, 让离线 doctor 测试
# 因缺少 Google 凭据而错误失败。这里固定成对默认值, 使测试只验证代码。
from sci_rag.config import DEFAULT_LLM_MODEL

os.environ.setdefault("SCI_RAG_LLM_PROVIDER", "deepseek")
os.environ.setdefault("SCI_RAG_LLM_MODEL", DEFAULT_LLM_MODEL)

import pytest
import pytest_asyncio
from sqlalchemy import text

from sci_rag.config import get_settings, reset_settings_cache

reset_settings_cache()


@pytest.fixture(scope="session")
def settings():  # type: ignore[no-untyped-def]
    return get_settings()


@pytest_asyncio.fixture(scope="session")
async def database():  # type: ignore[no-untyped-def]
    """A clean schema in the test database, or a skip if Postgres is down."""
    from sci_rag.db import Base, dispose_engine, get_engine

    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await dispose_engine()
        pytest.skip(
            f"Postgres unavailable at {get_settings().database_url!r} ({type(exc).__name__}). "
            "Start it with `SCI_RAG_DB_BACKEND=docker make db-up`, "
            "`SCI_RAG_DB_BACKEND=local make db-up`, or "
            "`SCI_RAG_DB_BACKEND=cloud make db-up`; then set "
            "SCI_RAG_TEST_DATABASE_URL to that backend's disposable test database."
        )
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await dispose_engine()


@pytest_asyncio.fixture()
async def clean_tables(database):  # type: ignore[no-untyped-def]
    """Truncate all tables so each test starts from an empty knowledge base."""
    async with database.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE documents, chunks, document_citations, kg_entities, "
                "kg_relationships, kg_communities, entity_resolution_audit CASCADE"
            )
        )
    yield


@pytest.fixture()
def local_embedder(settings):  # type: ignore[no-untyped-def]
    from sci_rag.embed import LocalHashEmbedder

    return LocalHashEmbedder(settings.embedding_dim)
