"""One relation service behind REST and the actual MCP tool registration."""

import json

import pytest

from sci_rag.server.mcp_server import build_mcp_server

pytestmark = pytest.mark.integration


async def test_rest_relations_and_versions_obey_scope(client, service):  # type: ignore[no-untyped-def]
    rows, _ = await service.list_documents()
    document_id = rows[0].id
    response = await client.get(f"/v1/documents/{document_id}/related?relation=similar")
    assert response.status_code == 200 and response.json()["document"]["document_id"] == document_id
    response = await client.get(f"/v1/documents/{document_id}/related?sources=not-visible")
    assert response.status_code == 404
    response = await client.get(f"/v1/documents/{document_id}/versions")
    assert (
        response.status_code == 200 and response.json()["versions"][0]["document_id"] == document_id
    )


async def test_registered_agent_tools_follow_documents_without_inventing_relations(service):  # type: ignore[no-untyped-def]
    mcp, tools = build_mcp_server(service)
    rows, _ = await service.list_documents()
    document_id = rows[0].id
    related = await tools["get_related_documents"](document_id, relation="all")
    assert related["document"]["document_id"] == document_id
    assert "similar" in related and "citations" in related and "projects" in related
    versions = await tools["get_document_versions"](document_id)
    assert versions["versions"][0]["is_current"]
    protocol = await mcp.call_tool(
        "get_related_documents", {"document_id": document_id, "relation": "projects"}
    )
    assert not protocol.is_error
    assert json.loads(protocol.content[0].text)["document"]["document_id"] == document_id
    protocol = await mcp.call_tool("get_document_versions", {"document_id": document_id})
    assert not protocol.is_error
    assert json.loads(protocol.content[0].text)["versions"][0]["is_current"]
