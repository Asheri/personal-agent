"""POST /v1/query: retrieval only, with full transparency.

The response includes per-stage traces and degraded-stage flags, so an
integrator can always see which layers ran, how long they took, and
whether anything timed out. Nothing is hidden behind an opaque score.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from sci_rag.retrieve import RetrievalResult
from sci_rag.server.auth import AuthContext, require_scopes
from sci_rag.server.errors import request_id_var
from sci_rag.server.schemas import (
    QueryRequest,
    QueryResponse,
    RetrievedItemModel,
    StageTraceModel,
)
from sci_rag.server.service import RagService

router = APIRouter(tags=["retrieval"])


def result_to_models(
    result: RetrievalResult, *, include_content: bool = True
) -> tuple[list[RetrievedItemModel], list[StageTraceModel]]:
    items = [
        RetrievedItemModel(
            kind=item.kind,
            id=item.id,
            score=item.score,
            layers=item.layers,
            title=item.title,
            content=item.content if include_content else None,
            document_id=item.document_id,
            section_path=item.section_path,
            citation=item.citation,
            license_class=item.license_class,
            source=item.source,
            is_table=item.is_table,
        )
        for item in result.items
    ]
    traces = [
        StageTraceModel(
            stage=t.stage,
            status=t.status,
            duration_ms=t.duration_ms,
            candidate_count=t.candidate_count,
        )
        for t in result.traces
    ]
    return items, traces


@router.post("/v1/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    request: Request,
    auth: AuthContext = require_scopes("retrieval:query"),
) -> QueryResponse:
    service: RagService = request.app.state.service
    result = await service.retrieve(
        body.query,
        profile=body.profile,
        top_k=body.top_k,
        license_classes=body.license_classes,
        sources=body.sources,
        year_min=body.year_min,
        year_max=body.year_max,
        authors=body.authors,
        journals=body.journals,
        exclude_dois=body.exclude_dois,
        include_graph=body.include_graph,
        include_community=body.include_community,
        include_hyde=body.include_hyde,
        include_rerank=body.include_rerank,
    )
    items, traces = result_to_models(result, include_content=body.include_content)
    return QueryResponse(
        request_id=request_id_var.get(),
        profile=result.profile,
        items=items,
        traces=traces,
        degraded_stages=result.degraded_stages,
    )
