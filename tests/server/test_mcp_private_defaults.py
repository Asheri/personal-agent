"""External tools must not expose unknown-rights sources through alternate reads."""

import pytest

from sci_rag.db import Chunk, Document, get_session_factory
from sci_rag.server.errors import ApiError
from sci_rag.server.mcp_server import build_mcp_server


async def test_unknown_rights_never_leak_from_external_tools(service):
    async with get_session_factory()() as session:
        private = Document(
            title="Private controlled title",
            source="private-canary",
            license_class="unknown",
            content_hash="f" * 64,
        )
        session.add(private)
        await session.flush()
        session.add(
            Chunk(
                document_id=private.id,
                chunk_index=0,
                content="PRIVATE_MCP_CANARY only.",
                token_count=10,
            )
        )
        await session.commit()
    _, tools = build_mcp_server(service)
    for name in ["get_document", "get_citations", "get_document_versions", "get_related_documents"]:
        with pytest.raises(ApiError) as caught:
            await tools[name](private.id)
        assert caught.value.status == 404
    for dimension in ["documents", "facets", "project", "time", "topic"]:
        result = await tools["browse_corpus"](dimension=dimension)
        assert private.id not in str(result) and "private-canary" not in str(result)
    result = await tools["search_corpus"]("PRIVATE_MCP_CANARY")
    assert private.id not in str(result) and "PRIVATE_MCP_CANARY only" not in str(result)
    result = await tools["corpus_stats"]()
    assert "private-canary" not in str(result["sources"])
    result = await tools["browse_corpus"](filters={"license_classes": ["unknown"]})
    assert result["total"] == 0
