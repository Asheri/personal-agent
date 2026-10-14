"""Health, stats, and the public corpus manifest.

``/v1/corpus-manifest`` is deliberately unauthenticated: it is the
descriptor a multi-RAG router (a "switchboard" across several sci-rag-kit
deployments) reads to decide whether this knowledge base fits a query. It
exposes counts and configuration, never content.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

import sci_rag
from sci_rag.server.auth import AuthContext, require_scopes
from sci_rag.server.schemas import CorpusManifest, HealthResponse, StatsResponse
from sci_rag.server.service import RagService

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    service: RagService = request.app.state.service
    database_ok = await service.database_healthy()
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        version=sci_rag.__version__,
        database=database_ok,
    )


@router.get("/v1/status", response_model=StatsResponse)
async def status(
    request: Request, auth: AuthContext = require_scopes("corpus:read")
) -> StatsResponse:
    service: RagService = request.app.state.service
    stats = await service.stats()
    return StatsResponse(**stats)


@router.get("/v1/corpus-manifest", response_model=CorpusManifest)
async def corpus_manifest(request: Request) -> CorpusManifest:
    service: RagService = request.app.state.service
    base_url = str(request.base_url).rstrip("/")
    return CorpusManifest(**await service.corpus_manifest(base_url=base_url))
