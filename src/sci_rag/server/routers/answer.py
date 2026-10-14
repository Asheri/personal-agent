"""POST /v1/answer: grounded answers, streaming by default.

With ``stream: true`` (the default) the response is Server-Sent Events:

    event: retrieval_started   {"profile": "deep"}
    event: retrieval_done      {"item_count": 8, "degraded_stages": [], "traces": [...]}
    event: generation_started  {"model": "gemini-3.6-flash"}
    event: delta               {"text": "..."}          (repeats)
    event: citations           {"citations": [...]}
    event: done                {"finish_reason": "stop"}
    event: error               {"code": "...", "message": "..."}  (only on failure)

``finish_reason`` is ``stop``, ``no_sources``, ``no_relevant_sources``, or
``retrieval_timeout``. The last one carries ``timed_out_stages`` and is
separate from ``no_sources`` on purpose: a corpus nobody could reach inside
the stage budget is not an empty corpus, and reporting it as one sends a
reader to look at their data instead of at their timeouts.

With ``stream: false`` the same work returns as one JSON body.

Bring-your-own-key: a request may carry ``llm_api_key`` (requires the
``byo_llm`` scope), or the API key itself may be bound to an LLM key by the
operator. Either way the credential is used for this call only and never
logged.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from sci_rag.answer import AnswerEvent
from sci_rag.server.auth import AuthContext, require_scopes
from sci_rag.server.errors import ApiError, request_id_var
from sci_rag.server.routers.query import result_to_models
from sci_rag.server.schemas import (
    AnswerRequest,
    AnswerResponse,
    CitationModel,
    StageTraceModel,
)
from sci_rag.server.service import RagService

router = APIRouter(tags=["answers"])


def _public_data(event: AnswerEvent) -> dict:
    return {k: v for k, v in event.data.items() if not k.startswith("_")}


def _resolve_byo_key(body: AnswerRequest, auth: AuthContext) -> str | None:
    if body.llm_api_key is not None:
        if not auth.has_scope("byo_llm"):
            raise ApiError(
                403,
                "insufficient_scope",
                "Bring-your-own-key not allowed",
                "This API key lacks the byo_llm scope, so llm_api_key cannot be used.",
            )
        return body.llm_api_key.get_secret_value()
    return auth.llm_api_key


@router.post("/v1/answer", response_model=None)
async def answer(
    body: AnswerRequest, request: Request, auth: AuthContext = require_scopes("retrieval:answer")
) -> EventSourceResponse | AnswerResponse:
    service: RagService = request.app.state.service
    api_key_override = _resolve_byo_key(body, auth)
    events = service.answer_stream(
        body.query,
        profile=body.profile,
        top_k=body.top_k,
        max_tokens=body.max_tokens,
        license_classes=body.license_classes,
        sources=body.sources,
        year_min=body.year_min,
        year_max=body.year_max,
        authors=body.authors,
        journals=body.journals,
        exclude_dois=body.exclude_dois,
        api_key_override=api_key_override,
        include_compression=body.include_compression,
    )
    if body.stream:
        return EventSourceResponse(_sse_events(events))
    return await _collect(events, request_id_var.get())


async def _sse_events(events: AsyncIterator[AnswerEvent]) -> AsyncIterator[ServerSentEvent]:
    async for event in events:
        yield ServerSentEvent(event=event.type, data=json.dumps(_public_data(event)))


async def _collect(events: AsyncIterator[AnswerEvent], request_id: str) -> AnswerResponse:
    text_parts: list[str] = []
    citations: list[CitationModel] = []
    traces: list[StageTraceModel] = []
    degraded: list[str] = []
    model = ""
    prompt_tokens_before = 0
    prompt_tokens_after = 0
    compression_failure_count = 0
    compression_dropped_count = 0
    async for event in events:
        if event.type == "delta":
            text_parts.append(event.data["text"])
        elif event.type == "retrieval_done":
            _items, traces = result_to_models(event.data["_result"])
            degraded = event.data["degraded_stages"]
        elif event.type == "generation_started":
            model = event.data["model"]
        elif event.type == "compression_done":
            prompt_tokens_before = event.data["prompt_tokens_before"]
            prompt_tokens_after = event.data["prompt_tokens_after"]
            compression_failure_count = event.data["failure_count"]
            compression_dropped_count = event.data["dropped_count"]
        elif event.type == "citations":
            citations = [CitationModel(**c) for c in event.data["citations"]]
        elif event.type == "error":
            code = event.data.get("code", "generation_failed")
            status = 503 if code == "llm_unavailable" else 502
            raise ApiError(status, code, "Answer generation failed", event.data.get("message", ""))
    return AnswerResponse(
        request_id=request_id,
        answer="".join(text_parts),
        model=model,
        citations=citations,
        traces=traces,
        degraded_stages=degraded,
        prompt_tokens_before=prompt_tokens_before,
        prompt_tokens_after=prompt_tokens_after,
        compression_failure_count=compression_failure_count,
        compression_dropped_count=compression_dropped_count,
    )
