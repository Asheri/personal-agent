"""Exporting the corpus, and what a license scope does to the graph on the way out.

The round trip is the easy half. The half worth testing is that a scoped
export stays fail-closed through the knowledge graph, which needs a different
rule than the rows do: a `KgEntity` description is written from every document
the entity was extracted from, so an entity that straddles the scope boundary
would carry restricted content out inside a summary that looks like metadata.
`test_an_entity_straddling_the_scope_boundary_is_not_exported` is the one that
would catch that leak.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.db import get_session_factory, session_scope
from sci_rag.db.models import KgEntity, KgRelationship
from sci_rag.export import export_corpus, exported_columns
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.retrieve.types import RetrievalScope

pytestmark = pytest.mark.integration


@pytest.fixture()
def mixed_rights_corpus(tmp_path: Path) -> list[CorpusEntry]:
    """One public document and one restricted one, so a scope has work to do."""
    entries = []
    for name, text, license_class in (
        ("public_report", "Rice straw availability is near 310,000 tons per year.", "public"),
        (
            "paywalled_paper",
            "Almond prunings are chipped in winter, per the publisher.",
            "restricted",
        ),
    ):
        path = tmp_path / f"{name}.md"
        path.write_text(text)
        entries.append(
            CorpusEntry(path=path, title=name, license_class=license_class, source="tests")
        )
    return entries


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def _document_ids_by_title() -> dict[str, str]:
    from sqlalchemy import select

    from sci_rag.db.models import Document

    async with session_scope() as session:
        rows = (await session.execute(select(Document.id, Document.title))).all()
    return {row.title: row.id for row in rows}


async def test_jsonl_export_round_trips_the_corpus(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)

    outdir = tmp_path / "export"
    result = await export_corpus(get_session_factory(), directory=outdir, fmt="jsonl")

    assert result.counts["documents"] == 2
    assert result.counts["chunks"] >= 2
    assert not result.scoped

    documents = _read_jsonl(outdir / "documents.jsonl")
    assert {d["title"] for d in documents} == {"public_report", "paywalled_paper"}
    assert {d["license_class"] for d in documents} == {"public", "restricted"}

    chunks = _read_jsonl(outdir / "chunks.jsonl")
    assert all(chunk["document_id"] in {d["id"] for d in documents} for chunk in chunks)
    assert any("310,000" in chunk["content"] for chunk in chunks)

    # Every table gets a file, even the graph ones nothing has populated yet.
    for table in ("documents", "chunks", "entities", "relationships"):
        assert (outdir / f"{table}.jsonl").is_file()


async def test_embeddings_are_omitted_unless_asked_for(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)

    lean = tmp_path / "lean"
    await export_corpus(get_session_factory(), directory=lean, fmt="jsonl")
    assert all("embedding" not in chunk for chunk in _read_jsonl(lean / "chunks.jsonl"))

    full = tmp_path / "full"
    await export_corpus(get_session_factory(), directory=full, fmt="jsonl", include_embeddings=True)
    chunks = _read_jsonl(full / "chunks.jsonl")
    assert chunks and all(isinstance(chunk["embedding"], list) for chunk in chunks)
    assert len(chunks[0]["embedding"]) == 64, "the test embedder is 64-dimensional"


async def test_a_license_scope_excludes_the_documents_and_their_chunks(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)

    outdir = tmp_path / "public-only"
    result = await export_corpus(
        get_session_factory(),
        directory=outdir,
        fmt="jsonl",
        scope=RetrievalScope(license_classes=("public",)),
    )

    assert result.scoped
    documents = _read_jsonl(outdir / "documents.jsonl")
    assert [d["title"] for d in documents] == ["public_report"]

    chunks = _read_jsonl(outdir / "chunks.jsonl")
    assert chunks, "the public document has chunks"
    assert all(chunk["document_id"] == documents[0]["id"] for chunk in chunks)
    assert not any("publisher" in chunk["content"] for chunk in chunks)


async def test_a_scope_that_names_nothing_exports_nothing(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    """An empty allowlist means deny, never "no filter". Same asymmetry as retrieval."""
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)

    outdir = tmp_path / "denied"
    result = await export_corpus(
        get_session_factory(),
        directory=outdir,
        fmt="jsonl",
        scope=RetrievalScope(license_classes=()),
    )

    assert result.counts == {"documents": 0, "chunks": 0, "entities": 0, "relationships": 0}
    assert (outdir / "documents.jsonl").read_text() == ""


async def test_unknown_rights_are_excluded_by_a_scope_that_does_not_name_them(
    clean_tables, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    """`unknown` is the default for "nobody said", and an export is a redistribution."""
    path = tmp_path / "undeclared.md"
    path.write_text("Nobody recorded the rights on this one.")
    await ingest_entries(
        [CorpusEntry(path=path, title="undeclared", source="tests")], embedder=local_embedder
    )

    outdir = tmp_path / "scoped"
    await export_corpus(
        get_session_factory(),
        directory=outdir,
        fmt="jsonl",
        scope=RetrievalScope(license_classes=("public", "open_commercial")),
    )

    assert _read_jsonl(outdir / "documents.jsonl") == []


async def test_an_entity_straddling_the_scope_boundary_is_not_exported(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    """Its description was written from both documents, so one of them is enough to bar it."""
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)
    ids = await _document_ids_by_title()

    async with session_scope() as session:
        session.add_all(
            [
                KgEntity(
                    id="e_public",
                    name="Rice Straw",
                    entity_type="Feedstock",
                    description="Written from the public report only.",
                    document_ids=[ids["public_report"]],
                ),
                KgEntity(
                    id="e_straddling",
                    name="Residue Handling",
                    entity_type="Process",
                    description="Written from both, including the restricted paper.",
                    document_ids=[ids["public_report"], ids["paywalled_paper"]],
                ),
                KgEntity(
                    id="e_unattributed",
                    name="Orphan",
                    entity_type="Concept",
                    description="No evidence pointers at all.",
                    document_ids=[],
                ),
            ]
        )
        await session.commit()

    outdir = tmp_path / "public-only"
    await export_corpus(
        get_session_factory(),
        directory=outdir,
        fmt="jsonl",
        scope=RetrievalScope(license_classes=("public",)),
    )

    exported = _read_jsonl(outdir / "entities.jsonl")
    assert [entity["id"] for entity in exported] == ["e_public"]
    assert not any("restricted" in (entity["description"] or "") for entity in exported)


async def test_an_unscoped_export_keeps_every_entity(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    """The strict rule is a property of scoping, not a permanent filter."""
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)
    ids = await _document_ids_by_title()

    async with session_scope() as session:
        session.add_all(
            [
                KgEntity(
                    id="e_straddling",
                    name="Residue Handling",
                    entity_type="Process",
                    document_ids=[ids["public_report"], ids["paywalled_paper"]],
                ),
                KgEntity(id="e_unattributed", name="Orphan", entity_type="Concept"),
            ]
        )
        await session.commit()

    outdir = tmp_path / "everything"
    await export_corpus(get_session_factory(), directory=outdir, fmt="jsonl")

    exported = {entity["id"] for entity in _read_jsonl(outdir / "entities.jsonl")}
    assert exported == {"e_straddling", "e_unattributed"}


async def test_a_relationship_survives_only_with_its_document_and_both_endpoints(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)
    ids = await _document_ids_by_title()

    async with session_scope() as session:
        session.add_all(
            [
                KgEntity(id="e_a", name="A", entity_type="C", document_ids=[ids["public_report"]]),
                KgEntity(id="e_b", name="B", entity_type="C", document_ids=[ids["public_report"]]),
                KgEntity(
                    id="e_restricted",
                    name="R",
                    entity_type="C",
                    document_ids=[ids["paywalled_paper"]],
                ),
            ]
        )
        session.add_all(
            [
                KgRelationship(
                    id="r_keep",
                    source_entity_id="e_a",
                    target_entity_id="e_b",
                    relation_type="RELATED_TO",
                    document_id=ids["public_report"],
                ),
                KgRelationship(
                    id="r_endpoint_out_of_scope",
                    source_entity_id="e_a",
                    target_entity_id="e_restricted",
                    relation_type="RELATED_TO",
                    document_id=ids["public_report"],
                ),
                KgRelationship(
                    id="r_evidence_out_of_scope",
                    source_entity_id="e_a",
                    target_entity_id="e_b",
                    relation_type="RELATED_TO",
                    document_id=ids["paywalled_paper"],
                ),
                KgRelationship(
                    id="r_unattributed",
                    source_entity_id="e_a",
                    target_entity_id="e_b",
                    relation_type="RELATED_TO",
                ),
            ]
        )
        await session.commit()

    outdir = tmp_path / "public-only"
    await export_corpus(
        get_session_factory(),
        directory=outdir,
        fmt="jsonl",
        scope=RetrievalScope(license_classes=("public",)),
    )

    kept = [row["id"] for row in _read_jsonl(outdir / "relationships.jsonl")]
    assert kept == ["r_keep"]


async def test_parquet_export_reads_back_with_the_same_columns(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    pq = pytest.importorskip("pyarrow.parquet")
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)

    outdir = tmp_path / "parquet"
    result = await export_corpus(get_session_factory(), directory=outdir, fmt="parquet")

    assert result.counts["documents"] == 2
    documents = pq.read_table(outdir / "documents.parquet")
    assert documents.num_rows == 2
    assert set(documents.column_names) == set(exported_columns("documents"))
    assert set(documents.column("title").to_pylist()) == {"public_report", "paywalled_paper"}

    # `extra` is JSONB whose keys differ row to row, so it lands as one stable
    # string column rather than a struct whose schema changes with the corpus.
    # It still has to survive the trip: parse back to a dict, contents intact.
    assert str(documents.schema.field("extra").type) == "string"
    decoded = [json.loads(value) for value in documents.column("extra").to_pylist()]
    assert all(isinstance(value, dict) for value in decoded)
    assert all(value["parser"] == "text" for value in decoded), (
        "ingestion records which parser ran; the export must not lose it"
    )


async def test_an_empty_table_still_writes_a_parquet_file_with_its_columns(
    clean_tables, mixed_rights_corpus, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    """A reader should see "no rows", not "no such column"."""
    pq = pytest.importorskip("pyarrow.parquet")
    await ingest_entries(mixed_rights_corpus, embedder=local_embedder)

    outdir = tmp_path / "parquet"
    await export_corpus(get_session_factory(), directory=outdir, fmt="parquet")

    entities = pq.read_table(outdir / "entities.parquet")
    assert entities.num_rows == 0
    assert set(entities.column_names) == set(exported_columns("entities"))
