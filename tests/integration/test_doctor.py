"""The doctor's checks against a real database, offline."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text, update

from sci_rag.cli.doctor import _run_checks
from sci_rag.db import Document, KgEntity, get_engine, get_session_factory
from sci_rag.ingest import ingest_entries, load_manifest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).parents[2]


async def _stamp_alembic_revision() -> None:
    # Tests build the schema via create_all (same DDL source as the
    # migration); the doctor reads alembic_version, so stamp it.
    async with get_engine().begin() as conn:
        await conn.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) PRIMARY KEY)")
        )
        await conn.execute(text("DELETE FROM alembic_version"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('0007')"))


async def test_doctor_reports_outdated_schema_before_new_column_queries(clean_tables) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    async with get_engine().begin() as conn:
        await conn.execute(text("UPDATE alembic_version SET version_num = '0004'"))
        await conn.execute(text("ALTER TABLE kg_entities DROP COLUMN canonical_entity_id CASCADE"))
    try:
        checks = _by_name(await _run_checks(probe=False))
        assert checks["schema"].status == "fail"
        assert "expected 0007" in checks["schema"].detail
        assert "db upgrade" in checks["schema"].fix
    finally:
        async with get_engine().begin() as conn:
            await conn.execute(
                text("ALTER TABLE kg_entities ADD COLUMN canonical_entity_id VARCHAR(32)")
            )
            await conn.execute(
                text(
                    "ALTER TABLE kg_entities ADD CONSTRAINT "
                    "fk_kg_entities_canonical_entity_id FOREIGN KEY (canonical_entity_id) "
                    "REFERENCES kg_entities(id) ON DELETE SET NULL"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX ix_kg_entities_canonical_entity_id "
                    "ON kg_entities (canonical_entity_id)"
                )
            )
            await conn.execute(text("UPDATE alembic_version SET version_num = '0007'"))


def _by_name(checks) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {check.name: check for check in checks}


async def test_doctor_reports_an_unbuildable_embedder_instead_of_raising(
    clean_tables, local_embedder, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """A project that wants the Google embedder and has no key must still get a table.

    The embedding-version row builds the configured embedder to learn its
    version stamp, and the Google one refuses to construct without
    credentials. Letting that escape means the command a user runs to find
    out what is wrong dies with a traceback and reports nothing at all,
    including the credentials failure that explains it.
    """
    await _stamp_alembic_revision()
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    await ingest_entries(entries[:1], embedder=local_embedder)

    from sci_rag.config import reset_settings_cache

    monkeypatch.setenv("SCI_RAG_EMBEDDING_PROVIDER", "google")
    reset_settings_cache()
    try:
        checks = _by_name(await _run_checks(probe=False))
    finally:
        monkeypatch.setenv("SCI_RAG_EMBEDDING_PROVIDER", "local-hash")
        reset_settings_cache()

    assert checks["credentials"].status == "fail"
    assert checks["embedding versions"].status == "warn"
    assert "RuntimeError" in checks["embedding versions"].detail
    # The rows after the embedder lookup still have to be reached.
    assert "knowledge graph" in checks


async def test_doctor_on_empty_schema(clean_tables) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    checks = _by_name(await _run_checks(probe=False))

    assert checks["config"].status == "ok"
    # conftest pins local-hash + no credentials: usable, but generation is out.
    assert checks["credentials"].status == "warn"
    assert checks["domain"].status == "ok"
    assert checks["seed questions"].status == "ok"
    assert checks["database"].status == "ok"
    assert checks["pgvector"].status == "ok"
    assert checks["schema"].status == "ok"
    assert checks["embedding dimension"].status == "ok"
    assert checks["corpus"].status == "warn"
    assert "ingest" in checks["corpus"].fix


async def test_doctor_with_corpus_flags_missing_graph(clean_tables, local_embedder) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    await ingest_entries(entries, embedder=local_embedder)

    checks = _by_name(await _run_checks(probe=False))
    assert checks["corpus"].status == "ok"
    assert checks["knowledge graph"].status == "warn"
    assert "graph extract" in checks["knowledge graph"].fix


async def test_doctor_passes_for_an_offline_project_with_a_corpus(
    clean_tables, local_embedder
) -> None:  # type: ignore[no-untyped-def]
    """The state the wizard writes for `credentials: offline` is not a failure.

    The test environment is that state: the local-hash embedder, no
    credentials, the shipped generation defaults. A user who pressed Enter
    through the wizard and ingested a corpus should see an exit code of 0,
    so nothing here may report `fail`. The missing pieces still have to be
    visible, hence the warnings this asserts alongside.
    """
    await _stamp_alembic_revision()
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    await ingest_entries(entries, embedder=local_embedder)

    checks = await _run_checks(probe=False)
    by_name = _by_name(checks)

    failures = {check.name: check.detail for check in checks if check.status == "fail"}
    assert failures == {}
    assert by_name["credentials"].status == "warn"
    assert by_name["llm credentials (deepseek)"].status == "warn"


async def test_doctor_warns_about_known_retracted_documents(clean_tables, local_embedder) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    await ingest_entries(entries[:1], embedder=local_embedder)
    async with get_engine().begin() as conn:
        await conn.execute(update(Document).values(extra={"crossref": {"is_retracted": True}}))

    checks = _by_name(await _run_checks(probe=False))

    assert checks["retractions"].status == "warn"
    assert "1" in checks["retractions"].detail
    assert "exclude" in checks["retractions"].fix.lower()


async def test_doctor_warns_about_normalized_entity_duplicates(clean_tables) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    async with get_session_factory()() as session:
        session.add_all(
            [
                KgEntity(name="Rice-straw", entity_type="Feedstock"),
                KgEntity(name="rice straw", entity_type="Feedstock"),
            ]
        )
        await session.commit()

    checks = _by_name(await _run_checks(probe=False))

    assert checks["entity resolution"].status == "warn"
    assert "resolve-entities" in checks["entity resolution"].fix


async def test_doctor_catches_dimension_mismatch(clean_tables, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    monkeypatch.setenv("SCI_RAG_EMBEDDING_DIM", "999")
    from sci_rag.config import reset_settings_cache

    reset_settings_cache()
    try:
        checks = _by_name(await _run_checks(probe=False))
        assert checks["embedding dimension"].status == "fail"
        assert "999" in checks["embedding dimension"].detail
        assert "chunks.embedding" in checks["embedding dimension"].detail
        assert "kg_communities.summary_embedding" in checks["embedding dimension"].detail
    finally:
        monkeypatch.delenv("SCI_RAG_EMBEDDING_DIM")
        monkeypatch.setenv("SCI_RAG_EMBEDDING_DIM", "64")
        reset_settings_cache()


async def test_doctor_catches_community_embedding_dimension_mismatch(clean_tables) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    async with get_engine().begin() as conn:
        await conn.execute(text("UPDATE kg_communities SET summary_embedding = NULL"))
        await conn.execute(
            text(
                "ALTER TABLE kg_communities ALTER COLUMN summary_embedding TYPE vector(32) "
                "USING NULL::vector(32)"
            )
        )
    try:
        checks = _by_name(await _run_checks(probe=False))
        assert checks["embedding dimension"].status == "fail"
        assert "kg_communities.summary_embedding" in checks["embedding dimension"].detail
        assert "vector(32)" in checks["embedding dimension"].detail
    finally:
        async with get_engine().begin() as conn:
            await conn.execute(text("UPDATE kg_communities SET summary_embedding = NULL"))
            await conn.execute(
                text(
                    "ALTER TABLE kg_communities ALTER COLUMN summary_embedding TYPE vector(64) "
                    "USING NULL::vector(64)"
                )
            )


async def test_doctor_reports_a_missing_community_embedding_column(clean_tables) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    async with get_engine().begin() as conn:
        await conn.execute(text("ALTER TABLE kg_communities DROP COLUMN summary_embedding"))
    try:
        checks = _by_name(await _run_checks(probe=False))
        detail = checks["embedding dimension"].detail

        assert checks["embedding dimension"].status == "fail"
        assert "kg_communities.summary_embedding is missing" in detail
    finally:
        async with get_engine().begin() as conn:
            await conn.execute(
                text("ALTER TABLE kg_communities ADD COLUMN summary_embedding vector(64)")
            )


async def test_doctor_rejects_a_non_vector_community_column(clean_tables, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    await _stamp_alembic_revision()
    monkeypatch.setenv("SCI_RAG_EMBEDDING_DIM", "1024")
    from sci_rag.config import reset_settings_cache

    reset_settings_cache()
    try:
        async with get_engine().begin() as conn:
            await conn.execute(text("UPDATE kg_communities SET summary_embedding = NULL"))
            await conn.execute(
                text(
                    "ALTER TABLE kg_communities ALTER COLUMN summary_embedding TYPE varchar(1020) "
                    "USING NULL::varchar(1020)"
                )
            )
        checks = _by_name(await _run_checks(probe=False))
        detail = checks["embedding dimension"].detail

        assert checks["embedding dimension"].status == "fail"
        assert "kg_communities.summary_embedding" in detail
        assert "character varying(1020)" in detail
        assert "expected vector(1024)" in detail
    finally:
        async with get_engine().begin() as conn:
            await conn.execute(text("UPDATE kg_communities SET summary_embedding = NULL"))
            await conn.execute(
                text(
                    "ALTER TABLE kg_communities ALTER COLUMN summary_embedding TYPE vector(64) "
                    "USING NULL::vector(64)"
                )
            )
        monkeypatch.delenv("SCI_RAG_EMBEDDING_DIM")
        monkeypatch.setenv("SCI_RAG_EMBEDDING_DIM", "64")
        reset_settings_cache()


async def test_static_modelscope_doctor_path_never_downloads(
    clean_tables, local_embedder, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Construction does not download; the first embed call loads the model."""
    await _stamp_alembic_revision()
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    await ingest_entries(entries[:1], embedder=local_embedder)

    import sci_rag.embed.modelscope as modelscope_embed

    forbidden_calls: list[str] = []

    def forbid_download(*_args, **_kwargs) -> None:
        forbidden_calls.append("download")
        raise AssertionError("static doctor must not download a model")

    def forbid_load(*_args, **_kwargs) -> None:
        forbidden_calls.append("load")
        raise AssertionError("static doctor must not load a model")

    monkeypatch.setattr(modelscope_embed, "_download_snapshot", forbid_download)
    monkeypatch.setattr(modelscope_embed, "_load_sentence_transformer", forbid_load)
    monkeypatch.setattr("sci_rag.cli.doctor.find_spec", lambda _name: object())
    monkeypatch.setenv("SCI_RAG_EMBEDDING_PROVIDER", "modelscope")
    monkeypatch.setenv("SCI_RAG_DEEPSEEK_API_KEY", "offline-test-key")
    from sci_rag.config import reset_settings_cache

    reset_settings_cache()
    try:
        checks = _by_name(await _run_checks(probe=False))
        failures = {check.name: check.detail for check in checks.values() if check.status == "fail"}

        assert failures == {}
        assert "embedding versions" in checks
        assert forbidden_calls == []
    finally:
        monkeypatch.setenv("SCI_RAG_EMBEDDING_PROVIDER", "local-hash")
        monkeypatch.delenv("SCI_RAG_DEEPSEEK_API_KEY")
        reset_settings_cache()


async def test_the_domain_coherence_rows_appear(clean_tables) -> None:  # type: ignore[no-untyped-def]
    """The shipped profile is the reference the new rows are calibrated against."""
    await _stamp_alembic_revision()

    checks = _by_name(await _run_checks(probe=False))

    assert checks["ontology"].status == "ok"
    assert checks["seed coherence"].status == "ok"
    assert checks["ground truth"].status == "ok"


async def test_ground_truth_is_checked_against_the_ingested_corpus(
    clean_tables, local_embedder
) -> None:  # type: ignore[no-untyped-def]
    """Only meaningful once documents exist, which is why it lives down here."""
    await _stamp_alembic_revision()
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    await ingest_entries(entries, embedder=local_embedder)

    checks = _by_name(await _run_checks(probe=False))

    assert checks["ground truth vs corpus"].status == "ok"


async def test_a_reference_title_that_matches_nothing_is_flagged(
    clean_tables, local_embedder
) -> None:  # type: ignore[no-untyped-def]
    """A title that resolves to no document scores zero forever, and in the
    report that is indistinguishable from a retrieval failure."""
    await _stamp_alembic_revision()
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    await ingest_entries(entries, embedder=local_embedder)
    async with get_engine().begin() as conn:
        await conn.execute(
            text("UPDATE documents SET title = title || ' (renamed after the fact)'")
        )

    checks = _by_name(await _run_checks(probe=False))

    assert checks["ground truth vs corpus"].status == "warn"
    assert "reference title" in checks["ground truth vs corpus"].detail


async def test_the_manifest_row_is_absent_without_a_manifest(clean_tables) -> None:  # type: ignore[no-untyped-def]
    """A project that ingests by folder never writes one; that is not a finding."""
    await _stamp_alembic_revision()

    checks = _by_name(await _run_checks(probe=False))

    assert "manifest" not in checks
