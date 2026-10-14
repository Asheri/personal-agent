"""Answer endpoint: SSE streaming, JSON mode, and bring-your-own-key rules."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select, update

from sci_rag.db import Document, get_session_factory

pytestmark = pytest.mark.integration


async def test_answer_json_mode(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/v1/answer",
        json={
            "query": "rice straw availability",
            "stream": False,
            "profile": "interactive",
            "include_compression": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "302,000 dry tons [1]" in body["answer"]
    assert body["model"] == "mock-llm"
    cited = [c for c in body["citations"] if c["cited"]]
    assert cited and cited[0]["index"] == 1
    assert body["traces"]
    assert body["prompt_tokens_before"] == body["prompt_tokens_after"]
    assert body["compression_failure_count"] == 0


async def test_answer_json_compression_override_reports_measured_tokens(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/v1/answer",
        json={
            "query": "rice straw availability",
            "stream": False,
            "profile": "interactive",
            "include_compression": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prompt_tokens_before"] > body["prompt_tokens_after"]
    assert body["compression_failure_count"] == 0


async def test_filtered_answer_still_excludes_retracted_documents(client) -> None:  # type: ignore[no-untyped-def]
    async with get_session_factory()() as session:
        document_id = await session.scalar(
            select(Document.id).where(Document.title.ilike("%Colusa Basin Rice Straw%"))
        )
        assert document_id is not None
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(extra={"crossref": {"is_retracted": True}})
        )
        await session.commit()

    response = await client.post(
        "/v1/answer",
        json={
            "query": "Colusa Basin rice straw resource assessment",
            "stream": False,
            "profile": "interactive",
            "year_min": 2023,
            "top_k": 10,
        },
    )

    assert response.status_code == 200
    assert all(citation["document_id"] != document_id for citation in response.json()["citations"])


async def test_answer_sse_event_sequence(client, demo_compression_enabled) -> None:  # type: ignore[no-untyped-def]
    events: list[tuple[str, dict]] = []
    async with client.stream(
        "POST",
        "/v1/answer",
        json={"query": "rice straw availability", "stream": True, "profile": "interactive"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        current_event = ""
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((current_event, json.loads(line.split(":", 1)[1].strip())))

    names = [name for name, _ in events]
    assert names[0] == "retrieval_started"
    assert "retrieval_done" in names
    assert "generation_started" in names
    assert "compression_done" in names
    assert any(name == "delta" for name in names)
    assert names[-2:] == ["citations", "done"]

    retrieval_done = next(data for name, data in events if name == "retrieval_done")
    assert retrieval_done["item_count"] >= 1
    assert not any(key.startswith("_") for key in retrieval_done)

    citations = next(data for name, data in events if name == "citations")
    assert any(c["cited"] for c in citations["citations"])

    compression = next(data for name, data in events if name == "compression_done")
    # The tuning belongs to the domain profile, not to the SSE contract; what
    # this pins is that the event is emitted and carries the configured value.
    assert compression["enabled"] is demo_compression_enabled
    assert not any(key.startswith("_") for key in compression)


async def test_byo_key_requires_scope(secured_client) -> None:  # type: ignore[no-untyped-def]
    denied = await secured_client.post(
        "/v1/answer",
        json={"query": "rice", "stream": False, "llm_api_key": "user-supplied-key"},
        headers={"Authorization": "Bearer answer-key"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "insufficient_scope"


async def test_byo_key_with_scope_passes_auth(secured_client) -> None:  # type: ignore[no-untyped-def]
    # The fake key sails past auth, then fails inside generation (it is not a
    # real Google key). What we are asserting is the auth seam and the error
    # surface: a problem+json failure, never a 403.
    response = await secured_client.post(
        "/v1/answer",
        json={"query": "rice", "stream": False, "llm_api_key": "user-supplied-key"},
        headers={"Authorization": "Bearer full-key"},
    )
    assert response.status_code in (502, 503)
    assert response.json()["code"] in ("generation_failed", "llm_unavailable")


async def test_secret_key_never_appears_in_repr(secured_client) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.server.schemas import AnswerRequest

    request = AnswerRequest(query="q", llm_api_key="super-secret-value")  # type: ignore[arg-type]
    assert "super-secret-value" not in repr(request)
    assert "super-secret-value" not in request.model_dump_json()
