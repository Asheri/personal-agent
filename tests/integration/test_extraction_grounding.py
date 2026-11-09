"""Model text must not become unsupported aliases, passages, or graph edges."""

from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import select

from sci_rag.db import Chunk, Document, KgEntity, KgRelationship, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.graph import extract_graph


async def test_extraction_rejects_invented_aliases_and_unquoted_edges(clean_tables):
    factory = get_session_factory()
    async with factory() as session:
        doc = Document(title="source", content_hash="e" * 64, license_class="public")
        session.add(doc)
        await session.flush()
        session.add(
            Chunk(
                document_id=doc.id,
                chunk_index=0,
                token_count=30,
                content="陈林负责远山项目。远山项目采用激光定位。",
            )
        )
        await session.commit()
    llm = AsyncMock()
    llm.generate_json.return_value = {
        "entities": [
            {"name": "陈林", "type": "Person", "passages": [1], "aliases": ["Invented Name"]},
            {"name": "远山", "type": "Project", "passages": [1], "aliases": ["远山项目"]},
            {"name": "激光定位", "type": "Technology", "passages": [1]},
            {"name": "虚构人物", "type": "Person", "passages": [1]},
        ],
        "relationships": [
            {
                "source": "陈林",
                "target": "远山",
                "type": "PART_OF",
                "passage": 1,
                "evidence": "陈林负责远山项目",
            },
            {
                "source": "远山",
                "target": "激光定位",
                "type": "USES",
                "passage": 1,
                "evidence": "This quote was invented",
            },
        ],
    }
    stats = await extract_graph(
        session_factory=factory,
        llm=llm,
        domain=load_domain(Path(__file__).parents[2] / "domain-personal"),
        rate_limit_s=0,
    )
    async with factory() as session:
        entities = list((await session.scalars(select(KgEntity))).all())
        assert {e.name for e in entities} == {"陈林", "远山", "激光定位"}
        assert next(e for e in entities if e.name == "陈林").aliases == []
        assert next(e for e in entities if e.name == "远山").aliases == ["远山项目"]
        relationships = list((await session.scalars(select(KgRelationship))).all())
        assert len(relationships) == 1 and relationships[0].relation_type == "PART_OF"
    assert stats.entities_dropped == 1 and stats.relationships_dropped == 1
