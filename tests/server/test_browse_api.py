"""REST and actual registered MCP tools share one visible corpus."""

import json

from sci_rag.server.mcp_server import build_mcp_server


async def test_browse_rest_mcp_parity_and_validation(client, service):
    _, tools = build_mcp_server(service)
    filters = {"sources": ["demo_fixture"], "license_classes": ["public"]}
    for dimension in ["documents", "facets", "project", "time", "topic"]:
        route = "/v1/corpus/facets" if dimension == "facets" else "/v1/corpus/browse"
        response = await client.get(
            route, params={"dimension": dimension, "filters": json.dumps(filters)}
        )
        assert response.status_code == 200, response.text
        assert response.json().get("total", 0) > 0
        assert response.json() == await tools["browse_corpus"](dimension=dimension, filters=filters)
    assert (await client.get("/v1/corpus/projects")).json() == await tools["list_projects"]()
    assert (await client.get("/v1/corpus/browse", params={"filters": "[]"})).status_code == 422
    assert (
        await client.get("/v1/corpus/browse", params={"filters": '{"unknown":true}'})
    ).status_code == 422
    assert (
        await client.get("/v1/corpus/browse", params={"dimension": "made-up"})
    ).status_code == 422


async def test_browse_read_scope_is_required(secured_client):
    response = await secured_client.get(
        "/v1/corpus/facets", headers={"Authorization": "Bearer query-key"}
    )
    assert response.status_code == 403


async def test_drilldown_intersects_existing_scope(service):
    from datetime import date

    from sci_rag.db import Document, get_session_factory
    from sci_rag.db.models import Project

    async with get_session_factory()() as session:
        first = Project(name="First controlled project", slug="first-controlled")
        second = Project(name="Second controlled project", slug="second-controlled")
        session.add_all([first, second])
        await session.flush()
        for index, project in enumerate([first, second]):
            session.add(
                Document(
                    title="Drill " + str(index),
                    source="drill",
                    license_class="public",
                    content_hash=str(index) * 64,
                    project_id=project.id,
                    project_source="manual",
                    doc_date=date(2026, 10, 5 if index == 0 else 25),
                )
            )
        await session.commit()
    result = await service.browse_corpus(
        dimension="project", by=second.id, filters={"projects": [first.id]}
    )
    assert result["total"] == 0
    result = await service.browse_corpus(
        dimension="time", by="2026-10", filters={"sources": ["drill"], "date_min": "2026-10-20"}
    )
    assert result["total"] == 1 and result["documents"][0]["project_id"] == second.id
