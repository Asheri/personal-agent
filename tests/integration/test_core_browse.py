"""Core browsing must preserve scope, empty buckets, dates, and named provenance."""

from datetime import date

from sci_rag.db import Chunk, Document, KgEntity, get_session_factory
from sci_rag.db.models import Project
from sci_rag.retrieve import RetrievalScope
from sci_rag.retrieve.stages.keyword import keyword_stage


async def test_identifier_search_crosses_language_and_punctuation(clean_tables):
    factory = get_session_factory()
    async with factory() as session:
        for number, body in enumerate(
            ["编号 TYPES2026。", "English source TYPES2026", "实验编号TYPES2026。"]
        ):
            doc = Document(
                title=f"Controlled {number}",
                source="allowed",
                content_hash=str(number) * 64,
                license_class="public",
            )
            session.add(doc)
            await session.flush()
            session.add(Chunk(document_id=doc.id, chunk_index=0, content=body, token_count=15))
        await session.commit()
    scope = RetrievalScope(sources=("allowed",), license_classes=("public",))
    assert len(await keyword_stage(factory, "TYPES2026", scope, 20)) == 3
    assert len(await keyword_stage(factory, "编号 TYPES2026", scope, 20)) == 3
    assert await keyword_stage(factory, "TYPES2026", RetrievalScope(sources=()), 20) == []


async def test_explicit_identifier_ranks_before_common_question_words(clean_tables):
    factory = get_session_factory()
    expected = set()
    async with factory() as session:
        for index in range(43):
            key = f"{index:032x}"
            body = (
                "编号 unrelated filler record."
                if index < 40
                else ["编号 RANKID2026。", "English RANKID2026", "实验编号RANKID2026。"][index - 40]
            )
            doc = Document(
                id=key, title="Controlled rank", content_hash=key.zfill(64), license_class="public"
            )
            session.add(doc)
            await session.flush()
            session.add(Chunk(id=key, document_id=key, chunk_index=0, content=body, token_count=15))
            if index >= 40:
                expected.add(key)
        await session.commit()
    hits = await keyword_stage(
        factory, "编号 RANKID2026", RetrievalScope(license_classes=("public",)), 3
    )
    assert {key for _, key in hits} == expected


async def test_browse_scope_buckets_pagination_and_dates(clean_tables):
    from sci_rag.browse import browse_documents, facet_counts

    factory = get_session_factory()
    async with factory() as session:
        docs = []
        project = Project(name="Controlled project", slug="controlled-project")
        session.add(project)
        await session.flush()
        for number in range(5):
            doc = Document(
                title=f"Visible {number}",
                source="allowed" if number < 3 else "hidden",
                content_hash=str(number) * 64,
                doc_date=date(2026, 1, number + 1) if number else None,
                tags=["manual"] if number == 1 else [],
                auto_tags=["automatic"] if number == 2 else [],
                is_current=number != 4,
            )
            session.add(doc)
            if number == 1:
                doc.project_id = project.id
                doc.project_source = "manual"
            docs.append(doc)
        await session.flush()
        chunk = Chunk(
            document_id=docs[1].id,
            chunk_index=0,
            content="Controlled topic evidence.",
            token_count=10,
        )
        session.add(chunk)
        await session.flush()
        session.add(
            KgEntity(
                name="Controlled topic",
                entity_type="Topic",
                document_ids=[docs[1].id],
                chunk_ids=[chunk.id],
            )
        )
        await session.commit()
    scope = RetrievalScope(sources=("allowed",))
    facets = await facet_counts(factory, scope)
    assert facets["total"] == 3
    assert sum(row["count"] for row in facets["dimensions"]["time"]) == 3
    assert (
        next(row for row in facets["dimensions"]["project"] if row["value"] is None)["count"] == 2
    )
    assert next(row for row in facets["dimensions"]["time"] if row["value"] is None)["count"] == 1
    assert sum(row["count"] for row in facets["dimensions"]["project"]) == 3
    assert (
        next(row for row in facets["dimensions"]["topic"] if row["value"] == "Controlled topic")[
            "count"
        ]
        == 1
    )
    assert (await browse_documents(factory, RetrievalScope(projects=(project.id,))))["total"] == 1
    pages = [await browse_documents(factory, scope, page=n, page_size=1) for n in range(1, 4)]
    assert len({page["documents"][0]["id"] for page in pages}) == 3
    assert pages[-1]["documents"][0]["doc_date"] is None
    filtered = await browse_documents(
        factory, RetrievalScope(sources=("allowed",), date_min=date(2026, 1, 3))
    )
    assert filtered["total"] == 2
    for field, tag in [("tags", "manual"), ("auto_tags", "automatic")]:
        result = await browse_documents(
            factory, RetrievalScope(sources=("allowed",), **{field: (tag,)})
        )
        assert result["total"] == 1
    result = await browse_documents(factory, RetrievalScope(entity_names=("Controlled topic",)))
    assert result["total"] == 1 and result["documents"][0]["title"] == "Visible 1"
    denied = await facet_counts(factory, RetrievalScope(license_classes=()))
    assert denied["total"] == 0 and all(not rows for rows in denied["dimensions"].values())
