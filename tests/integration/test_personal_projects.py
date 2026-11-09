"""Project source priority, evidence checks, manual locks, and tag isolation."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from sci_rag.db import Document, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.projects import (
    ProjectRule,
    assign_project,
    check_project_rules,
    classify_documents,
    create_project,
    list_projects,
    set_manual_tags,
)

pytestmark = pytest.mark.integration
DOMAIN = Path(__file__).resolve().parents[2] / "domain-personal"


async def _entry(tmp_path, embedder, *, license_class="public"):  # type: ignore[no-untyped-def]
    path = tmp_path / "notes.txt"
    path.write_text(
        "Atlas project: Chen Lin prepares the knowledge graph experiment and its reproducible supporting notes.",
        encoding="utf-8",
    )
    entry = CorpusEntry(path=path, license_class=license_class)
    outcome = (await ingest_entries([entry], embedder=embedder)).outcomes[0]
    return entry, outcome.document_id


async def _document(document_id):  # type: ignore[no-untyped-def]
    async with get_session_factory()() as session:
        return await session.get(Document, document_id)


async def test_manual_rule_and_inference_priority_and_tag_columns(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    _, document_id = await _entry(tmp_path, local_embedder)
    atlas = await create_project(factory, "Atlas")
    other = await create_project(factory, "Other")
    llm = AsyncMock()
    llm.generate_json.return_value = {
        "project": "Atlas",
        "confidence": 0.9,
        "evidence": "Atlas project",
    }
    await classify_documents(factory=factory, domain=load_domain(DOMAIN), llm=llm, auto_tags=False)
    assert (await _document(document_id)).project_source == "inferred"
    rules = [ProjectRule(other.id, ("*notes.txt",))]
    await classify_documents(
        factory=factory, domain=load_domain(DOMAIN), rules=rules, infer=False, auto_tags=False
    )
    assert (await _document(document_id)).project_source == "rule"
    assert (await _document(document_id)).project_id == other.id
    await assign_project(factory, document_id, atlas.id)
    await set_manual_tags(factory, document_id, ["C++", "人工主题"])
    llm.generate_json.return_value = {"tags": ["graph", "GRAPH", "data"]}
    await classify_documents(factory=factory, domain=load_domain(DOMAIN), llm=llm, rules=rules)
    actual = await _document(document_id)
    assert (actual.project_id, actual.project_source) == (atlas.id, "manual")
    assert actual.tags == ["C++", "人工主题"] and actual.auto_tags == ["graph", "data"]
    await set_manual_tags(factory, document_id, ["replacement"])
    assert (await _document(document_id)).auto_tags == ["graph", "data"]


@pytest.mark.parametrize(
    "payload",
    [
        {"project": "Invented", "confidence": 0.9, "evidence": "Atlas project"},
        {"project": "Atlas", "confidence": 0.9, "evidence": "Absent quote"},
        {"project": "Atlas", "confidence": None, "evidence": "Atlas project"},
        {"project": "Atlas", "confidence": 0.2, "evidence": "Atlas project"},
    ],
)
async def test_bad_inference_preserves_previous_assignment(
    clean_tables, tmp_path, local_embedder, payload
):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    _, document_id = await _entry(tmp_path, local_embedder)
    atlas = await create_project(factory, "Atlas")
    async with factory() as session:
        document = await session.get(Document, document_id)
        document.project_id, document.project_source = atlas.id, "inferred"
        document.extra = {**document.extra, "project_confidence": 0.8}
        await session.commit()
    llm = AsyncMock()
    llm.generate_json.return_value = payload
    await classify_documents(factory=factory, domain=load_domain(DOMAIN), llm=llm, auto_tags=False)
    document = await _document(document_id)
    assert (document.project_id, document.project_source) == (atlas.id, "inferred")
    assert document.extra["project_confidence"] == 0.8
    assert len(await list_projects(factory)) == 1


async def test_unknown_rights_prevent_model_calls_but_allow_local_rules(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    _, document_id = await _entry(tmp_path, local_embedder, license_class="unknown")
    atlas = await create_project(factory, "Atlas")
    llm = AsyncMock()
    stats = await classify_documents(
        factory=factory,
        domain=load_domain(DOMAIN),
        llm=llm,
        rules=[ProjectRule(atlas.id, ("*notes.txt",))],
    )
    assert stats.outbound_skipped == 1 and not llm.generate_json.called
    assert (await _document(document_id)).project_source == "rule"


async def test_conflicting_rules_are_reported_before_first_wins(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    _, document_id = await _entry(tmp_path, local_embedder)
    first, second = await create_project(factory, "First"), await create_project(factory, "Second")
    rules = [ProjectRule(first.id, ("*notes.txt",)), ProjectRule(second.id, ("*notes.txt",))]
    assert await check_project_rules(factory, rules) == [document_id]
    await classify_documents(
        factory=factory, domain=load_domain(DOMAIN), rules=rules, infer=False, auto_tags=False
    )
    assert (await _document(document_id)).project_id == first.id


async def test_new_revision_retains_manual_ownership_and_tags(
    clean_tables, tmp_path, local_embedder
):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    entry, document_id = await _entry(tmp_path, local_embedder)
    atlas = await create_project(factory, "Atlas")
    await assign_project(factory, document_id, atlas.id)
    await set_manual_tags(factory, document_id, ["manual"])
    async with factory() as session:
        row = await session.get(Document, document_id)
        row.auto_tags = ["obsolete"]
        await session.commit()
    entry.path.write_text(
        entry.path.read_text(encoding="utf-8") + " Revised approved finding.", encoding="utf-8"
    )
    new_id = (await ingest_entries([entry], embedder=local_embedder)).outcomes[0].document_id
    current = await _document(new_id)
    assert (current.project_id, current.project_source, current.tags, current.auto_tags) == (
        atlas.id,
        "manual",
        ["manual"],
        [],
    )
    counts = {project.id: count for project, count in await list_projects(factory)}
    assert counts[atlas.id] == 1
    async with factory() as session:
        assert len((await session.scalars(select(Document))).all()) == 2
