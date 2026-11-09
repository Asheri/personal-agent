"""The same scoped browse operations used by CLI and MCP."""

import json
from typing import Any

from fastapi import APIRouter, Query, Request

from sci_rag.server.auth import AuthContext, require_scopes
from sci_rag.server.errors import ApiError
from sci_rag.server.service import RagService

router = APIRouter(tags=["corpus"])


def _filters(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
        if not isinstance(parsed, dict):
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise ApiError(422, "invalid_browse_filter", "Filters must be a JSON object") from None


@router.get("/v1/corpus/facets")
async def facets(
    request: Request, filters: str | None = None, auth: AuthContext = require_scopes("corpus:read")
) -> dict[str, Any]:
    service: RagService = request.app.state.service
    return await service.browse_corpus(dimension="facets", filters=_filters(filters))


@router.get("/v1/corpus/browse")
async def browse(
    request: Request,
    dimension: str = "documents",
    by: str | None = None,
    filters: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth: AuthContext = require_scopes("corpus:read"),
) -> dict[str, Any]:
    service: RagService = request.app.state.service
    return await service.browse_corpus(
        dimension=dimension, by=by, filters=_filters(filters), page=page, page_size=page_size
    )


@router.get("/v1/corpus/projects")
async def projects(
    request: Request, filters: str | None = None, auth: AuthContext = require_scopes("corpus:read")
) -> dict[str, Any]:
    service: RagService = request.app.state.service
    return await service.list_projects(filters=_filters(filters))


@router.get("/v1/corpus/topics")
async def topics(
    request: Request, filters: str | None = None, auth: AuthContext = require_scopes("corpus:read")
) -> dict[str, Any]:
    service: RagService = request.app.state.service
    return await service.topic_overview(filters=_filters(filters))
