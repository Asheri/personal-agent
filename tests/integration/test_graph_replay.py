"""Record and replay the demo graph through fresh database identities."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import pytest
from scripts.graph_replay import (
    GraphReplayError,
    ReplayArtifact,
    run_graph_replay,
    write_candidate,
)
from sqlalchemy import func, select, text

from sci_rag.db import (
    Chunk,
    Document,
    EntityResolutionAudit,
    KgEntity,
    KgRelationship,
    get_session_factory,
)
from sci_rag.domain import load_domain
from sci_rag.graph.extractor import ExtractedEntity, ExtractionStats, _upsert_entities
from sci_rag.ingest import chunk_document, load_manifest, parse_file
from sci_rag.ingest.ingester import content_hash_for
from sci_rag.llm import LLMClient

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"
EXTRACTION_MODEL = "test:scripted-extraction"
EXTRACTION = json.dumps(
    {
        "entities": [
            {
                "name": "alpha feedstock",
                "type": "Feedstock",
                "description": "a synthetic residue",
                "passages": [1],
            },
            {
                "name": "beta region",
                "type": "Region",
                "description": "a synthetic region",
                "passages": [2],
            },
        ],
        "relationships": [
            {
                "source": "alpha feedstock",
                "target": "beta region",
                "type": "LOCATED_IN",
                "evidence": "synthetic location evidence",
                "passage": 1,
                "confidence": 0.9,
            }
        ],
    }
)
AMBIGUOUS_ALIAS_EXTRACTIONS = (
    json.dumps(
        {
            "entities": [
                {
                    "name": "almond prunings",
                    "type": "Feedstock",
                    "description": "a specific synthetic residue",
                    "passages": [1],
                    "aliases": ["prunings"],
                },
                {
                    "name": "orchard prunings",
                    "type": "Feedstock",
                    "description": "a broader synthetic residue",
                    "passages": [1],
                    "aliases": ["prunings"],
                },
            ],
            "relationships": [],
        }
    ),
    json.dumps(
        {
            "entities": [
                {
                    "name": "prunings",
                    "type": "Feedstock",
                    "description": "an ambiguous surface form",
                    "passages": [1],
                }
            ],
            "relationships": [],
        }
    ),
)


class ScriptedExtractionLLM(LLMClient):
    model = EXTRACTION_MODEL

    def __init__(self) -> None:
        self.call_count = 0

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        self.call_count += 1
        return EXTRACTION

    async def _stream(self) -> AsyncIterator[str]:
        yield "unused"

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        return self._stream()


class InvalidExtractionLLM(ScriptedExtractionLLM):
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        return "not valid JSON"


class AmbiguousAliasLLM(ScriptedExtractionLLM):
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        try:
            response = AMBIGUOUS_ALIAS_EXTRACTIONS[self.call_count]
        except IndexError as exc:
            raise AssertionError("ambiguous alias fixture received an unexpected call") from exc
        self.call_count += 1
        return response


async def _seed_demo(
    *,
    first_ids: tuple[str, str],
    second_ids: tuple[str, str],
    source: str = "demo_fixture",
    license_class: str = "public",
    stamped: bool = False,
    graph_row: bool = False,
    with_chunks: bool = True,
    audit_row: bool = False,
) -> None:
    documents = (
        ("Alpha fixture", "Alpha is a synthetic agricultural residue.", first_ids),
        ("Beta fixture", "Beta is a synthetic agricultural region.", second_ids),
    )
    async with get_session_factory()() as session:
        for title, content, (document_id, chunk_id) in documents:
            session.add(
                Document(
                    id=document_id,
                    title=title,
                    source=source,
                    license_class=license_class,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    chunk_count=int(with_chunks),
                )
            )
            if with_chunks:
                session.add(
                    Chunk(
                        id=chunk_id,
                        document_id=document_id,
                        chunk_index=0,
                        content=content,
                        token_count=len(content.split()),
                        graph_extracted_at=datetime.now(UTC) if stamped else None,
                    )
                )
        if graph_row:
            session.add(
                KgEntity(
                    id="e" * 32,
                    name="preexisting graph state",
                    entity_type="Feedstock",
                    aliases=[],
                    document_ids=[],
                    chunk_ids=[],
                )
            )
        if audit_row:
            session.add(
                EntityResolutionAudit(
                    id="a" * 32,
                    merged_entity_id="b" * 32,
                    merged_entity_name="merged",
                    surviving_entity_id="c" * 32,
                    surviving_entity_name="survivor",
                    method="test",
                    confidence=1.0,
                )
            )
        await session.commit()


def _write_tracked_demo(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    documents = (
        ("alpha.md", "Alpha fixture", "Alpha is a synthetic agricultural residue."),
        ("beta.md", "Beta fixture", "Beta is a synthetic agricultural region."),
    )
    rows: list[str] = []
    for filename, title, content in documents:
        (fixture / filename).write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        rows.append(
            json.dumps(
                {
                    "path": f"fixture/{filename}",
                    "title": title,
                    "authors": ["Demo Author"],
                    "year": 2026,
                    "license_class": "public",
                    "source": "demo_fixture",
                }
            )
        )
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
    replay_script = tmp_path / "scripts" / "graph_replay.py"
    extractor_source = tmp_path / "src" / "sci_rag" / "graph" / "extractor.py"
    replay_script.parent.mkdir(parents=True)
    extractor_source.parent.mkdir(parents=True)
    replay_script.write_text("# tracked replay contract\n", encoding="utf-8")
    extractor_source.write_text("# tracked extractor contract\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "manifest.jsonl", "fixture", "scripts", "src"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Graph Replay Test",
            "-c",
            "user.email=graph-replay@example.invalid",
            "commit",
            "-qm",
            "track demo",
        ],
        check=True,
    )
    return manifest


def _source_commit(manifest_path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(manifest_path.parent), "rev-parse", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


async def _seed_tracked_demo(
    manifest_path: Path,
    *,
    persistence_ids: tuple[tuple[str, tuple[str, ...]], ...] | None = None,
    source: str | None = None,
    license_class: str | None = None,
    stamped: bool = False,
    graph_row: bool = False,
    with_chunks: bool = True,
    audit_row: bool = False,
) -> None:
    entries = load_manifest(manifest_path)
    if persistence_ids is not None:
        assert len(persistence_ids) == len(entries)
    async with get_session_factory()() as session:
        for entry_index, entry in enumerate(entries):
            parsed = parse_file(entry.path)
            drafts = chunk_document(parsed)
            entry_persistence_ids = (
                persistence_ids[entry_index] if persistence_ids is not None else None
            )
            if entry_persistence_ids is not None:
                assert len(entry_persistence_ids[1]) == len(drafts)
            document = Document(
                title=entry.title or parsed.title,
                source=source or entry.source,
                source_ref=str(entry.path),
                authors=entry.authors,
                publication_year=entry.year,
                doi=entry.doi,
                journal=entry.journal,
                license_class=license_class or entry.license_class,
                license_source="manifest",
                content_hash=content_hash_for(drafts),
                page_count=parsed.page_count,
                chunk_count=len(drafts) if with_chunks else 0,
            )
            if entry_persistence_ids is not None:
                document.id = entry_persistence_ids[0]
            session.add(document)
            await session.flush()
            for index, draft in enumerate(drafts if with_chunks else []):
                chunk = Chunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=draft.content,
                    token_count=draft.token_count,
                    section_path=draft.section_path,
                    is_table=draft.is_table,
                    graph_extracted_at=datetime.now(UTC) if stamped else None,
                )
                if entry_persistence_ids is not None:
                    chunk.id = entry_persistence_ids[1][index]
                session.add(chunk)
        if graph_row:
            session.add(
                KgEntity(
                    id="e" * 32,
                    name="preexisting graph state",
                    entity_type="Feedstock",
                    aliases=[],
                    document_ids=[],
                    chunk_ids=[],
                )
            )
        if audit_row:
            session.add(
                EntityResolutionAudit(
                    id="a" * 32,
                    merged_entity_id="b" * 32,
                    merged_entity_name="merged",
                    surviving_entity_id="c" * 32,
                    surviving_entity_name="survivor",
                    method="test",
                    confidence=1.0,
                )
            )
        await session.commit()


async def _reset_database(database) -> None:  # type: ignore[no-untyped-def]
    async with database.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE documents, chunks, document_citations, kg_entities, "
                "kg_relationships, kg_communities, entity_resolution_audit CASCADE"
            )
        )


async def _document_titles_in_chunk_id_order() -> list[str]:
    async with get_session_factory()() as session:
        result = await session.scalars(
            select(Document.title).join(Chunk, Chunk.document_id == Document.id).order_by(Chunk.id)
        )
        return list(result)


async def _ambiguous_alias_target(
    *,
    first_id: str,
    second_id: str,
    first_name: str,
    second_name: str,
    alias: str,
) -> str:
    async with get_session_factory()() as session:
        session.add_all(
            [
                KgEntity(
                    id=first_id,
                    name=first_name,
                    entity_type="Feedstock",
                    aliases=[alias],
                    document_ids=[],
                    chunk_ids=[],
                ),
                KgEntity(
                    id=second_id,
                    name=second_name,
                    entity_type="Feedstock",
                    aliases=[alias],
                    document_ids=[],
                    chunk_ids=[],
                ),
            ]
        )
        await session.flush()
        selected = await _upsert_entities(
            session,
            [
                ExtractedEntity(
                    name=alias,
                    entity_type="Feedstock",
                    description="",
                    passages=[],
                )
            ],
            {},
            {},
            fallback_chunk_ids=[],
            fallback_document_ids=[],
            stats=ExtractionStats(),
        )
        row = await session.get(KgEntity, selected[alias])
        assert row is not None
        return row.name


async def test_ambiguous_alias_tie_break_does_not_depend_on_database_ids(
    clean_tables, database
) -> None:  # type: ignore[no-untyped-def]
    """Fresh UUIDs cannot change which semantic entity an alias enriches."""
    inputs = {
        "first_name": "almond prunings",
        "second_name": "orchard prunings",
        "alias": "prunings",
    }
    first = await _ambiguous_alias_target(first_id="f" * 32, second_id="a" * 32, **inputs)
    await _reset_database(database)
    second = await _ambiguous_alias_target(first_id="1" * 32, second_id="f" * 32, **inputs)

    assert first == second == "almond prunings"


async def test_casefold_equivalent_alias_tie_break_does_not_depend_on_database_ids(
    clean_tables, database
) -> None:  # type: ignore[no-untyped-def]
    """Application ordering, not database collation or UUIDs, breaks alias ties."""
    inputs = {
        "first_name": "Prunings",
        "second_name": "prunings",
        "alias": "crop residue",
    }
    first = await _ambiguous_alias_target(first_id="f" * 32, second_id="a" * 32, **inputs)
    await _reset_database(database)
    second = await _ambiguous_alias_target(first_id="1" * 32, second_id="f" * 32, **inputs)

    assert first == second == "Prunings"


async def test_refresh_rejects_an_extra_public_demo_document_before_provider_construction(
    clean_tables, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    await _seed_demo(
        first_ids=("1" * 32, "3" * 32),
        second_ids=("2" * 32, "4" * 32),
    )
    provider_constructions = 0

    def provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        return ScriptedExtractionLLM()

    with pytest.raises(GraphReplayError, match="exactly match the tracked demo"):
        await run_graph_replay(
            mode="refresh",
            artifact_dir=tmp_path / "artifacts",
            receipt_path=tmp_path / "receipt.json",
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model=EXTRACTION_MODEL,
            llm_factory=provider,
            source_commit=_source_commit(manifest_path),
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider_constructions == 0


async def test_refresh_rejects_modified_demo_chunk_before_provider_construction(
    clean_tables, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    async with get_session_factory()() as session:
        chunk = await session.scalar(select(Chunk).order_by(Chunk.id).limit(1))
        assert chunk is not None
        chunk.content = "modified after ingestion"
        await session.commit()
    provider_constructions = 0

    def provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        return ScriptedExtractionLLM()

    with pytest.raises(GraphReplayError, match="exactly match the tracked demo"):
        await run_graph_replay(
            mode="refresh",
            artifact_dir=tmp_path / "artifacts",
            receipt_path=tmp_path / "receipt.json",
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model=EXTRACTION_MODEL,
            llm_factory=provider,
            source_commit=_source_commit(manifest_path),
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider_constructions == 0


async def test_refresh_rejects_modified_demo_manifest_metadata_before_provider_construction(
    clean_tables, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    async with get_session_factory()() as session:
        document = await session.scalar(select(Document).order_by(Document.id).limit(1))
        assert document is not None
        document.title = "Different public demo title"
        await session.commit()
    provider_constructions = 0

    def provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        return ScriptedExtractionLLM()

    with pytest.raises(GraphReplayError, match="exactly match the tracked demo"):
        await run_graph_replay(
            mode="refresh",
            artifact_dir=tmp_path / "artifacts",
            receipt_path=tmp_path / "receipt.json",
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model=EXTRACTION_MODEL,
            llm_factory=provider,
            source_commit=_source_commit(manifest_path),
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider_constructions == 0


async def test_refresh_rejects_dirty_tracked_demo_source_before_provider_construction(
    clean_tables, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    source_path = tmp_path / "fixture" / "alpha.md"
    source_path.write_text(source_path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    provider_constructions = 0

    def provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        return ScriptedExtractionLLM()

    with pytest.raises(GraphReplayError, match="dirty tracked demo source"):
        await run_graph_replay(
            mode="refresh",
            artifact_dir=tmp_path / "artifacts",
            receipt_path=tmp_path / "receipt.json",
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model=EXTRACTION_MODEL,
            llm_factory=provider,
            source_commit=_source_commit(manifest_path),
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider_constructions == 0


async def test_refresh_rejects_dirty_graph_contract_source_before_provider_construction(
    clean_tables, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    replay_source = tmp_path / "scripts" / "graph_replay.py"
    replay_source.write_text("# dirty replay contract\n", encoding="utf-8")
    provider_constructions = 0

    def provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        return ScriptedExtractionLLM()

    with pytest.raises(GraphReplayError, match="dirty graph replay source checkout"):
        await run_graph_replay(
            mode="refresh",
            artifact_dir=tmp_path / "artifacts",
            receipt_path=tmp_path / "receipt.json",
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model=EXTRACTION_MODEL,
            llm_factory=provider,
            source_commit=_source_commit(manifest_path),
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider_constructions == 0


async def test_record_and_require_replay_survive_fresh_database_ids(
    clean_tables, database, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(
        manifest_path,
        persistence_ids=(
            ("1" * 32, ("1" * 32,)),
            ("2" * 32, ("2" * 32,)),
        ),
    )
    assert await _document_titles_in_chunk_id_order() == ["Alpha fixture", "Beta fixture"]
    artifact_dir = tmp_path / "artifacts"
    record_receipt = tmp_path / "record-receipt.json"

    recorded = await run_graph_replay(
        mode="refresh",
        artifact_dir=artifact_dir,
        receipt_path=record_receipt,
        session_factory=get_session_factory(),
        domain=load_domain(DOMAIN_DIR),
        extraction_model=EXTRACTION_MODEL,
        llm_factory=ScriptedExtractionLLM,
        source_commit=_source_commit(manifest_path),
        manifest_path=manifest_path,
        batch_size=2,
        rate_limit_s=0,
    )

    assert recorded.mode == "refresh"
    assert recorded.extracted_calls == 1
    assert recorded.replayed_calls == 0
    assert recorded.artifact_path.is_file()
    assert record_receipt.is_file()

    await _reset_database(database)
    # The same tracked content now has fresh ids whose persistence order is reversed.
    await _seed_tracked_demo(
        manifest_path,
        persistence_ids=(
            ("f" * 32, ("f" * 32,)),
            ("e" * 32, ("e" * 32,)),
        ),
    )
    assert await _document_titles_in_chunk_id_order() == ["Beta fixture", "Alpha fixture"]
    provider_constructions = 0

    def forbidden_provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("strict replay constructed a live provider")

    replay_receipt = tmp_path / "replay-receipt.json"
    replayed = await run_graph_replay(
        mode="require",
        artifact_path=recorded.artifact_path,
        receipt_path=replay_receipt,
        session_factory=get_session_factory(),
        domain=load_domain(DOMAIN_DIR),
        extraction_model=EXTRACTION_MODEL,
        llm_factory=forbidden_provider,
        manifest_path=manifest_path,
        batch_size=2,
        rate_limit_s=0,
    )

    assert provider_constructions == 0
    assert replayed.mode == "require"
    assert replayed.extracted_calls == 0
    assert replayed.replayed_calls == recorded.extracted_calls
    assert replayed.artifact_sha256 == recorded.artifact_sha256
    assert replayed.corpus_digest == recorded.corpus_digest
    assert replayed.domain_digest == recorded.domain_digest
    assert replayed.graph_digest == recorded.graph_digest
    assert replayed.entity_count == recorded.entity_count
    assert replayed.relationship_count == recorded.relationship_count
    assert replay_receipt.is_file()


async def test_record_and_require_replay_resolve_ambiguous_aliases_identically(
    clean_tables, database, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """The incident path remains stable through the complete replay contract."""
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    recorded = await run_graph_replay(
        mode="refresh",
        artifact_dir=tmp_path / "artifacts",
        receipt_path=tmp_path / "record-receipt.json",
        session_factory=get_session_factory(),
        domain=load_domain(DOMAIN_DIR),
        extraction_model=EXTRACTION_MODEL,
        llm_factory=AmbiguousAliasLLM,
        source_commit=_source_commit(manifest_path),
        manifest_path=manifest_path,
        batch_size=1,
        rate_limit_s=0,
    )

    await _reset_database(database)
    await _seed_tracked_demo(manifest_path)
    provider_constructions = 0

    def forbidden_provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("strict replay constructed a live provider")

    replayed = await run_graph_replay(
        mode="require",
        artifact_path=recorded.artifact_path,
        receipt_path=tmp_path / "replay-receipt.json",
        session_factory=get_session_factory(),
        domain=load_domain(DOMAIN_DIR),
        extraction_model=EXTRACTION_MODEL,
        llm_factory=forbidden_provider,
        manifest_path=manifest_path,
        batch_size=1,
        rate_limit_s=0,
    )

    async with get_session_factory()() as session:
        rows = (await session.execute(select(KgEntity).order_by(KgEntity.name))).scalars().all()

    assert provider_constructions == 0
    assert replayed.extracted_calls == 0
    assert replayed.replayed_calls == 2
    assert replayed.graph_digest == recorded.graph_digest
    assert replayed.entity_count == recorded.entity_count == 2
    assert [(row.name, len(row.document_ids)) for row in rows] == [
        ("almond prunings", 2),
        ("orchard prunings", 1),
    ]


@pytest.mark.parametrize(
    (
        "source",
        "license_class",
        "stamped",
        "graph_row",
        "with_chunks",
        "audit_row",
        "reason",
    ),
    [
        ("local", "public", False, False, True, False, "demo_fixture"),
        ("demo_fixture", "restricted", False, False, True, False, "public"),
        ("demo_fixture", "public", True, False, True, False, "unstamped"),
        ("demo_fixture", "public", False, True, True, False, "graph"),
        ("demo_fixture", "public", False, False, False, False, "chunk"),
        ("demo_fixture", "public", False, False, True, True, "graph"),
    ],
)
async def test_refresh_refuses_a_target_outside_the_pristine_public_demo_boundary(
    clean_tables,
    tmp_path: Path,
    source: str,
    license_class: str,
    stamped: bool,
    graph_row: bool,
    with_chunks: bool,
    audit_row: bool,
    reason: str,
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(
        manifest_path,
        source=source,
        license_class=license_class,
        stamped=stamped,
        graph_row=graph_row,
        with_chunks=with_chunks,
        audit_row=audit_row,
    )
    provider_constructions = 0

    def provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        return ScriptedExtractionLLM()

    artifact_dir = tmp_path / "artifacts"
    receipt_path = tmp_path / "receipt.json"
    with pytest.raises(GraphReplayError, match=reason):
        await run_graph_replay(
            mode="refresh",
            artifact_dir=artifact_dir,
            receipt_path=receipt_path,
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model=EXTRACTION_MODEL,
            llm_factory=provider,
            source_commit=_source_commit(manifest_path),
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider_constructions == 0
    assert not artifact_dir.exists()
    assert not receipt_path.exists()
    async with get_session_factory()() as session:
        entity_count = await session.scalar(select(func.count(KgEntity.id)))
        relationship_count = await session.scalar(select(func.count(KgRelationship.id)))
    assert entity_count == int(graph_row)
    assert relationship_count == 0


async def test_require_rejects_identity_drift_without_constructing_a_provider(
    clean_tables, database, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    recorded = await run_graph_replay(
        mode="refresh",
        artifact_dir=tmp_path / "artifacts",
        receipt_path=tmp_path / "record-receipt.json",
        session_factory=get_session_factory(),
        domain=load_domain(DOMAIN_DIR),
        extraction_model=EXTRACTION_MODEL,
        llm_factory=ScriptedExtractionLLM,
        source_commit=_source_commit(manifest_path),
        manifest_path=manifest_path,
        batch_size=2,
        rate_limit_s=0,
    )
    await _reset_database(database)
    await _seed_tracked_demo(manifest_path)
    provider_constructions = 0

    def forbidden_provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("identity drift constructed a live provider")

    with pytest.raises(GraphReplayError, match="extraction model"):
        await run_graph_replay(
            mode="require",
            artifact_path=recorded.artifact_path,
            receipt_path=tmp_path / "drift-receipt.json",
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model="test:a-different-model",
            llm_factory=forbidden_provider,
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider_constructions == 0
    async with get_session_factory()() as session:
        entity_count = await session.scalar(select(func.count(KgEntity.id)))
        relationship_count = await session.scalar(select(func.count(KgRelationship.id)))
    assert entity_count == 0
    assert relationship_count == 0


async def test_failed_refresh_writes_neither_candidate_nor_receipt(
    clean_tables, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    artifact_dir = tmp_path / "artifacts"
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(GraphReplayError, match="incomplete"):
        await run_graph_replay(
            mode="refresh",
            artifact_dir=artifact_dir,
            receipt_path=receipt_path,
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model=EXTRACTION_MODEL,
            llm_factory=InvalidExtractionLLM,
            source_commit=_source_commit(manifest_path),
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert not artifact_dir.exists()
    assert not receipt_path.exists()


async def test_off_mode_counts_live_calls_without_writing_an_artifact(
    clean_tables, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    await _seed_demo(
        first_ids=("1" * 32, "3" * 32),
        second_ids=("2" * 32, "4" * 32),
    )
    receipt_path = tmp_path / "receipt.json"

    receipt = await run_graph_replay(
        mode="off",
        receipt_path=receipt_path,
        session_factory=get_session_factory(),
        domain=load_domain(DOMAIN_DIR),
        extraction_model=EXTRACTION_MODEL,
        llm_factory=ScriptedExtractionLLM,
        batch_size=2,
        rate_limit_s=0,
    )

    assert receipt.extracted_calls == 1
    assert receipt.replayed_calls == 0
    assert receipt.artifact_path is None
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["extracted_call_count"] == 1
    assert payload["artifact_path"] is None


async def test_require_rejects_an_artifact_that_declares_failed_batches(
    clean_tables, database, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    recorded = await run_graph_replay(
        mode="refresh",
        artifact_dir=tmp_path / "recorded",
        receipt_path=tmp_path / "record-receipt.json",
        session_factory=get_session_factory(),
        domain=load_domain(DOMAIN_DIR),
        extraction_model=EXTRACTION_MODEL,
        llm_factory=ScriptedExtractionLLM,
        source_commit=_source_commit(manifest_path),
        manifest_path=manifest_path,
        batch_size=2,
        rate_limit_s=0,
    )
    raw = json.loads(recorded.artifact_path.read_text(encoding="utf-8"))
    raw["failed_batches"] = 1
    incomplete_path = write_candidate(ReplayArtifact.from_dict(raw), tmp_path / "incomplete")

    await _reset_database(database)
    await _seed_tracked_demo(manifest_path)
    provider_constructions = 0

    def forbidden_provider() -> LLMClient:
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("incomplete artifact constructed a provider")

    with pytest.raises(GraphReplayError, match="failed batches"):
        await run_graph_replay(
            mode="require",
            artifact_path=incomplete_path,
            receipt_path=tmp_path / "incomplete-receipt.json",
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model=EXTRACTION_MODEL,
            llm_factory=forbidden_provider,
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider_constructions == 0
    assert not (tmp_path / "incomplete-receipt.json").exists()


async def test_refresh_rejects_a_mislabeled_provider_before_its_first_call(
    clean_tables, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_tracked_demo(tmp_path)
    await _seed_tracked_demo(manifest_path)
    provider = ScriptedExtractionLLM()
    artifact_dir = tmp_path / "artifacts"
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(GraphReplayError, match="effective extraction model"):
        await run_graph_replay(
            mode="refresh",
            artifact_dir=artifact_dir,
            receipt_path=receipt_path,
            session_factory=get_session_factory(),
            domain=load_domain(DOMAIN_DIR),
            extraction_model="test:mislabeled-model",
            llm_factory=lambda: provider,
            source_commit=_source_commit(manifest_path),
            manifest_path=manifest_path,
            batch_size=2,
            rate_limit_s=0,
        )

    assert provider.call_count == 0
    assert not artifact_dir.exists()
    assert not receipt_path.exists()
