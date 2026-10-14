"""The FastAPI application factory.

One process serves three doors onto the same :class:`RagService`:

* the versioned REST API under ``/v1`` (interactive docs at ``/docs``),
* the MCP server for agents, mounted at ``/mcp`` (streamable HTTP),
* the public corpus manifest at ``/v1/corpus-manifest``.

Auth wraps both REST and MCP with the same key backend, so an operator
configures access once.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

import sci_rag
from sci_rag.config import Settings, get_settings
from sci_rag.server.auth import (
    API_KEY_HEADER,
    AuthBackend,
    api_key_from_headers,
    build_auth_backend,
)
from sci_rag.server.errors import (
    ApiError,
    RequestIdMiddleware,
    install_error_handlers,
    problem_response,
)
from sci_rag.server.mcp_server import build_mcp_server
from sci_rag.server.routers import answer_router, documents_router, meta_router, query_router
from sci_rag.server.service import RagService

API_DESCRIPTION = """
Retrieval-augmented generation, built around your scientific domain.
Built with
[sci-rag-kit](https://github.com/sustainability-software-lab/sci-rag-kit).

* `POST /v1/query`: retrieval only; ranked evidence with per-layer traces.
* `POST /v1/answer`: grounded, cited answers; Server-Sent Events by default.
* `GET /v1/documents`: the corpus catalog with provenance and licenses.
* `GET /v1/corpus-manifest`: public machine-readable descriptor (no auth).
* `/mcp`: the same capabilities as MCP tools for agents.

Authenticate with `Authorization: Bearer <key>` when the operator has
configured keys; errors come back as RFC 9457 `application/problem+json`.
"""


class _BearerAuthASGI:
    """Applies the API-key backend to the mounted MCP app (all of /mcp)."""

    def __init__(self, app: ASGIApp, backend: AuthBackend, required_scope: str) -> None:
        self.app = app
        self.backend = backend
        self.required_scope = required_scope

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # Fail closed: nothing behind this wrapper speaks websocket (or
            # anything else) today, and an unknown scope type must never
            # slide past authentication.
            if scope["type"] == "websocket":
                await receive()  # the websocket.connect event
                await send({"type": "websocket.close", "code": 1008})
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        token = api_key_from_headers(
            headers.get("authorization", ""), headers.get(API_KEY_HEADER.lower())
        )
        try:
            context = self.backend.authenticate(token)
            if not context.has_scope(self.required_scope):
                raise ApiError(403, "insufficient_scope", "Insufficient scope")
            self.backend.check_rate(context)
        except ApiError as exc:
            response = problem_response(exc.status, exc.code, exc.title, exc.detail, exc.headers)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(*, settings: Settings | None = None, service: RagService | None = None) -> FastAPI:
    settings = settings or get_settings()
    service = service or RagService(settings=settings)
    auth_backend = build_auth_backend(settings.api_keys, cors_origins=settings.cors_origins)

    mcp, _tools = build_mcp_server(service)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/",
        # The API-key layer above is the access control; DNS-rebinding
        # protection would reject the arbitrary Host headers seen behind
        # Cloud Run and other proxies, so it stays off here.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Starlette does not run nested lifespans under Mount, so the parent
        # app drives the MCP session manager itself.
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title=service.domain.name,
        version=sci_rag.__version__,
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.auth_backend = auth_backend

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestIdMiddleware)

    app.include_router(meta_router)
    app.include_router(query_router)
    app.include_router(answer_router)
    app.include_router(documents_router)
    app.mount("/mcp", _BearerAuthASGI(mcp_app, auth_backend, required_scope="retrieval:query"))

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/docs")

    return app
