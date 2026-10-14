"""The `internal_error` row of the documented REST error table.

`docs/api.md` promises that every error is RFC 9457 `application/problem+json`
carrying a stable code and the request id, and it lists `internal_error` as the
catch-all. Nothing in the product can be asked to fail that way on purpose,
which is why the row went unqualified in the route audit: inducing it live
would mean shipping a way to break the server, and that is a defect rather
than a test.

So the seam lives here. A fixture swaps one `RagService` coroutine for one
that raises. No production file gains a trigger, an environment variable, or
a debug route, and the substitution dies with the fixture.

The injected failure carries a fake credential, a verbatim corpus sentence,
and a SQL fragment, because the property under test is not only the shape of
the envelope but what the envelope withholds. REST and MCP sit on the same
`RagService`, so the same fault is driven through both front doors: an
unexpected failure must not reveal more on one surface than on the other.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
import pytest_asyncio

from sci_rag.config import Settings
from sci_rag.server import build_mcp_server, create_app

pytestmark = pytest.mark.integration

# Decoys planted in the fault so the leak assertions have something real to
# catch. None of these is a credential; the point is that a string shaped
# like one must not survive the boundary.
FAULT_SECRET = "sk-decoy-not-a-real-key-8f2c1d"
FAULT_CHUNK = "Rice straw availability was measured at 302,000 dry tons."
FAULT_SQL = "SELECT content FROM chunks WHERE document_id = 'd0'"
FAULT_MESSAGE = f"{FAULT_CHUNK} {FAULT_SQL} api_key={FAULT_SECRET}"

SENTINELS = (FAULT_SECRET, FAULT_CHUNK, FAULT_SQL)


class InjectedFault(RuntimeError):
    """Test only. Stands in for any unexpected failure below the service."""


@pytest.fixture()
def faulting_service(service, monkeypatch):  # type: ignore[no-untyped-def]
    """The real service with one coroutine replaced by a raiser.

    `retrieve` is the shared entry point behind `POST /v1/query` and the
    `search_corpus` MCP tool, so one substitution reaches both surfaces.
    """

    async def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise InjectedFault(FAULT_MESSAGE)

    monkeypatch.setattr(service, "retrieve", _raise)
    return service


@pytest_asyncio.fixture()
async def faulting_client(faulting_service):  # type: ignore[no-untyped-def]
    app = create_app(settings=Settings(api_keys=None), service=faulting_service)
    # Starlette's ServerErrorMiddleware re-raises after handing the handler's
    # response to the client, so that a real server can log the traceback.
    # Swallowing it here is what lets the test read the response the client
    # would have received.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def _query(client, **headers: str) -> httpx.Response:  # type: ignore[no-untyped-def]
    return await client.post("/v1/query", json={"query": "rice straw"}, headers=headers)


async def test_internal_error_matches_the_documented_envelope(faulting_client) -> None:  # type: ignore[no-untyped-def]
    response = await _query(faulting_client)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["title"] == "Internal server error"
    assert body["status"] == 500
    assert body["type"].endswith("/docs/api.md#internal_error")
    assert set(body) == {"type", "title", "status", "code", "detail", "request_id"}


async def test_internal_error_echoes_a_caller_supplied_request_id(faulting_client) -> None:  # type: ignore[no-untyped-def]
    """The header travels in both directions, and the body agrees with it.

    `docs/api.md` sells the request id as the handle a caller quotes when
    asking an operator to find the failure in the logs. That is worth
    nothing if the id is dropped on exactly the responses that send someone
    to the logs.
    """
    response = await _query(faulting_client, **{"X-Request-ID": "req-fault-0001"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-fault-0001"
    assert response.json()["request_id"] == "req-fault-0001"


async def test_internal_error_mints_a_request_id_when_the_caller_sends_none(
    faulting_client,
) -> None:  # type: ignore[no-untyped-def]
    response = await _query(faulting_client)

    minted = response.headers.get("X-Request-ID")
    assert minted
    assert response.json()["request_id"] == minted


async def test_internal_error_names_the_exception_type_and_nothing_else(faulting_client) -> None:  # type: ignore[no-untyped-def]
    response = await _query(faulting_client, **{"X-Request-ID": "req-fault-0002"})

    assert response.json()["detail"] == "InjectedFault (see server logs, request_id=req-fault-0002)"


async def test_internal_error_withholds_content_credentials_and_sql(  # type: ignore[no-untyped-def]
    faulting_client, caplog
) -> None:
    """Neither the response nor anything the application logs may carry the fault text.

    The log half is a forward guard. The application emits no record on this
    path today, so the assertion holds trivially; it starts earning its keep
    the moment someone adds a handler that logs the exception itself.
    """
    with caplog.at_level(logging.DEBUG):
        response = await _query(faulting_client)

    assert response.status_code == 500
    for sentinel in SENTINELS:
        assert sentinel not in response.text
    assert "Traceback" not in response.text
    assert "sci_rag/server" not in response.text

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for sentinel in SENTINELS:
        assert sentinel not in logged


async def test_mcp_withholds_what_rest_withholds(faulting_service) -> None:  # type: ignore[no-untyped-def]
    """The other front door on the same fault.

    `MCPServer.call_tool` raises on a crash, and the protocol handler turns
    that exception into the `is_error` result the client reads, using
    `str(exc)` verbatim. So asserting on this message is asserting on exactly
    the text an agent would see.
    """
    from mcp.server.mcpserver.exceptions import UnexpectedToolError

    mcp, _tools = build_mcp_server(faulting_service)

    with pytest.raises(UnexpectedToolError) as caught:
        await mcp.call_tool("search_corpus", {"query": "rice straw"})

    client_visible = str(caught.value)
    assert client_visible == "Error executing tool search_corpus"
    for sentinel in SENTINELS:
        assert sentinel not in client_visible
    # The detail stays server side, reachable only from the chained cause.
    assert isinstance(caught.value.__cause__, InjectedFault)
    assert FAULT_SECRET in str(caught.value.__cause__)


async def test_both_surfaces_agree_on_a_healthy_call(service) -> None:  # type: ignore[no-untyped-def]
    """The seam is inert unless a test asks for it.

    Without the faulting fixture the same tool answers normally, which is
    what proves the injection is scoped to the fixture rather than latent in
    the app.
    """
    mcp, _tools = build_mcp_server(service)

    result = await mcp.call_tool("search_corpus", {"query": "rice straw"})

    assert not result.is_error
    assert json.loads(result.content[0].text)["results"]
