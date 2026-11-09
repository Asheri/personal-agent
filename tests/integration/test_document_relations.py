"""Scoped document relations over a real disposable PostgreSQL database."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from sci_rag.citations import build_citation_edges
from sci_rag.db import Chunk, Document, DocumentCitation, get_session_factory
from sci_rag.db.models import DocumentEmbedding, Project
from sci_rag.relate.mentions import build_mentions
from sci_rag.relate.read import document_versions, related_documents
from sci_rag.retrieve import RetrievalScope
from sci_rag.server.service import RagService

pytestmark = pytest.mark.integration

# `resolve_key` treats a relative link as relative to the source document, and
# only when that source path is absolute by the host's own rules. A literal
# `d:\records\...` is not absolute on POSIX, so the fixtures build their paths
# from a platform-appropriate base.
RECORDS = Path("d:/records") if os.name == "nt" else Path("/records")


async def _add(
    session,
    title,
    *,
    source="allowed",
    vector=None,
    content="Controlled source material.",
    path=None,
    doi=None,
    extra=None,
    project=None,
):  # type: ignore[no-untyped-def]
    marker = uuid4().hex
    row = Document(
        title=title,
        source=source,
        license_class="public",
        content_hash=hashlib.sha256(marker.encode()).hexdigest(),
        extra={"path": path or str(RECORDS / f"{marker}.md"), **(extra or {})},
        doi=doi,
        project_id=project,
        project_source="manual" if project else None,
    )
    session.add(row)
    await session.flush()
    chunk = Chunk(document_id=row.id, chunk_index=0, content=content, token_count=10)
    session.add(chunk)
    if vector is not None:
        session.add(
            DocumentEmbedding(
                document_id=row.id,
                embedding=[*vector, *([0.0] * (64 - len(vector)))],
                embedding_version="controlled-v1",
            )
        )
    await session.flush()
    return row, chunk


async def test_similarity_uses_visible_corpus_only_and_reflects_new_rows(clean_tables):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        a, _ = await _add(session, "A", vector=[1, 0])
        b, _ = await _add(session, "B", vector=[0.99, 0.01])
        await _add(session, "C", vector=[0, 1])
        await _add(session, "D", vector=[-1, 0])
        await session.commit()
        a_id, b_id = a.id, b.id
    scope = RetrievalScope(sources=("allowed",))
    first = await related_documents(factory, a_id, relation="similar", scope=scope)
    assert first["similar"][0]["document_id"] == b_id
    async with factory() as session:
        hidden, _ = await _add(
            session, "SECRET OUTSIDE SCOPE", source="forbidden", vector=[10000, 10000]
        )
        await session.commit()
        hidden_id = hidden.id
    assert await related_documents(factory, a_id, relation="similar", scope=scope) == first
    assert hidden_id not in json.dumps(first)
    async with factory() as session:
        new, _ = await _add(session, "New neighbor", vector=[0.999, 0.001])
        await session.commit()
        new_id = new.id
    assert new_id in [
        r["document_id"]
        for r in (await related_documents(factory, a_id, relation="similar", scope=scope))[
            "similar"
        ]
    ]


async def test_project_and_explicit_history_do_not_expose_hidden_ids(clean_tables):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        project = Project(name="Controlled", slug="controlled")
        session.add(project)
        await session.flush()
        old, _ = await _add(
            session, "Hidden prior revision", source="forbidden", project=project.id
        )
        old.is_current = False
        await session.flush()
        head, _ = await _add(session, "Visible current", project=project.id)
        head.identity_key, head.version_seq, head.version_of = old.identity_key, 2, old.id
        peer, _ = await _add(session, "Visible peer", project=project.id)
        await session.commit()
        head_id, old_id, peer_id = head.id, old.id, peer.id
    scope = RetrievalScope(sources=("allowed",))
    peers = await related_documents(factory, head_id, relation="projects", scope=scope)
    assert [r["document_id"] for r in peers["projects"]] == [peer_id]
    history = await document_versions(factory, head_id, scope=scope)
    assert len(history["versions"]) == 1 and history["versions"][0]["predecessor_id"] is None
    assert old_id not in json.dumps(history)
    with pytest.raises(LookupError):
        await related_documents(factory, old_id, scope=scope)


async def test_mentions_are_auditable_idempotent_and_resolve_later_targets(clean_tables):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        source, chunk = await _add(
            session,
            "Source",
            path=str(RECORDS / "source.md"),
            content="引用 [[目标计划]] 与 [资料](target.md),还有 [[重复标题]] 和 [[稍后资料]]。",
        )
        target, _ = await _add(session, "目标计划", path=str(RECORDS / "target.md"))
        await _add(session, "重复标题")
        await _add(session, "重复标题")
        await session.commit()
        source_id, target_id, chunk_id = source.id, target.id, chunk.id
    dry = await build_mentions(factory)
    assert dry["rows_written"] == 3 and dry["ambiguous"] == 1
    async with factory() as session:
        assert not list((await session.scalars(select(DocumentCitation))).all())
    await build_mentions(factory, apply=True)
    assert (await build_mentions(factory, apply=True))["rows_written"] == 0
    visible = (await related_documents(factory, source_id, relation="citations"))["citations"][
        "references"
    ]
    assert len(visible) == 3 and any(r["cited_document_id"] == target_id for r in visible)
    assert all(r["evidence_chunk_id"] == chunk_id for r in visible)
    assert all(r["title"] is None for r in visible if not r["resolved"])
    async with factory() as session:
        later, _ = await _add(session, "稍后资料")
        await session.commit()
        later_id = later.id
    await build_mentions(factory, apply=True)
    visible = (await related_documents(factory, source_id, relation="citations"))["citations"][
        "references"
    ]
    assert any(r["cited_document_id"] == later_id for r in visible)


async def test_crossref_replaces_same_pair_mention_without_unique_conflict(clean_tables):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        _source, _ = await _add(
            session,
            "Source",
            content="An explicit reference 10.1234/target.",
            extra={"crossref": {"reference_dois": ["10.1234/target"]}},
        )
        await _add(session, "Target", doi="10.1234/target")
        await session.commit()
    await build_mentions(factory, apply=True)
    assert (await build_citation_edges(factory, dry_run=False)).rows_removed == 1
    await build_mentions(factory, apply=True)
    async with factory() as session:
        rows = list((await session.scalars(select(DocumentCitation))).all())
        assert len(rows) == 1 and rows[0].source == "crossref"


async def test_legacy_citation_reader_accepts_scope_and_hides_other_endpoints(clean_tables):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        source, _ = await _add(session, "Visible source")
        hidden, _ = await _add(session, "Hidden target", source="forbidden")
        session.add(
            DocumentCitation(
                citing_document_id=source.id,
                cited_document_id=hidden.id,
                cited_doi="10.1234/hidden",
            )
        )
        await session.commit()
        source_id = source.id
    service = object.__new__(RagService)
    service.session_factory = factory
    result = await service.get_citations(source_id, scope=RetrievalScope(sources=("allowed",)))
    assert result["references"] == []


async def test_wrong_source_or_absent_literal_evidence_is_hidden_by_both_readers(clean_tables):  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        source, own_chunk = await _add(
            session, "Source", content="This source has no explicit matching reference."
        )
        _other, other_chunk = await _add(
            session, "Other", content="This unrelated source mentions [[Target]]."
        )
        target, _ = await _add(session, "Target")
        edge = DocumentCitation(
            citing_document_id=source.id,
            cited_document_id=target.id,
            cited_key="Target",
            evidence_chunk_id=other_chunk.id,
            source="mention",
            confidence=1.0,
        )
        session.add(edge)
        await session.commit()
        source_id, edge_id, own_chunk_id = source.id, edge.id, own_chunk.id
    service = object.__new__(RagService)
    service.session_factory = factory
    for phase in ["wrong_source", "absent_literal"]:
        if phase == "absent_literal":
            async with factory() as session:
                edge = await session.get(DocumentCitation, edge_id)
                edge.evidence_chunk_id = own_chunk_id
                await session.commit()
        assert (await related_documents(factory, source_id, relation="citations"))["citations"][
            "references"
        ] == []
        assert (await service.get_citations(source_id))["references"] == []
