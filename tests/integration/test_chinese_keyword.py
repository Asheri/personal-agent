"""Chinese retrieval must use current, in-scope evidence on native Postgres."""

import hashlib

from sci_rag.db import Chunk, Document, get_session_factory
from sci_rag.retrieve.stages.keyword import keyword_stage
from sci_rag.retrieve.types import RetrievalScope


async def test_chinese_keyword_obeys_visibility_and_handles_updates(clean_tables):
    factory = get_session_factory()
    async with factory() as session:
        ids = []
        for source, rights, current in [
            ("allowed", "public", True),
            ("hidden", "public", True),
            ("allowed", "unknown", True),
            ("allowed", "public", False),
        ]:
            doc = Document(
                title="record",
                source=source,
                license_class=rights,
                is_current=current,
                content_hash=hashlib.sha256(str(len(ids)).encode()).hexdigest(),
            )
            session.add(doc)
            await session.flush()
            chunk = Chunk(
                document_id=doc.id,
                chunk_index=0,
                content="陈林负责当前项目并整理新的实验记录。",
                token_count=20,
            )
            session.add(chunk)
            await session.flush()
            ids.append(chunk.id)
        await session.commit()
    scope = RetrievalScope(sources=("allowed",), license_classes=("public",))
    assert await keyword_stage(factory, "陈林", scope, 20) == [("chunk", ids[0])]
    assert await keyword_stage(factory, "陈林", scope, 0) == []
    async with factory() as session:
        chunk = await session.get(Chunk, ids[0])
        chunk.content = "王宁负责新的项目记录。"
        await session.commit()
    assert await keyword_stage(factory, "陈林", scope, 20) == []
    assert await keyword_stage(factory, "王宁", scope, 20) == [("chunk", ids[0])]


async def test_mixed_identifier_query_and_no_match(clean_tables):
    factory = get_session_factory()
    async with factory() as session:
        doc = Document(title="report", content_hash="f" * 64, license_class="public")
        session.add(doc)
        await session.flush()
        chunk = Chunk(
            document_id=doc.id,
            chunk_index=0,
            content="王宁提交了编号 PC-2026-047 的项目报告。",
            token_count=20,
        )
        session.add(chunk)
        await session.flush()
        key = chunk.id
        await session.commit()
    scope = RetrievalScope(license_classes=("public",))
    assert ("chunk", key) in await keyword_stage(factory, "查找 PC-2026-047 报告", scope, 20)
    assert await keyword_stage(factory, "不存在的火星基地", scope, 20) == []
