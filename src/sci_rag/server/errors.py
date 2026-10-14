"""Errors as RFC 9457 problem+json, with a request id on everything.

Machine-readable ``code`` values (stable, documented) plus a human ``title``
and ``detail``. Integrators branch on ``code``; humans read ``detail``.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        super().__init__(detail or title)


def problem_response(
    status: int, code: str, title: str, detail: str = "", headers: dict[str, str] | None = None
) -> JSONResponse:
    request_id = request_id_var.get()
    # Stamp the header here rather than relying on RequestIdMiddleware. That
    # middleware adds the header on the way back out, so a response built
    # after an unhandled exception unwound past it never got one: the body
    # quoted an id the caller could not read off the response. A 500 is the
    # response that most needs the id, since its detail sends the reader to
    # the server logs to look it up.
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=response_headers,
        content={
            "type": f"https://github.com/sustainability-software-lab/sci-rag-kit/blob/main/docs/api.md#{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            "request_id": request_id,
        },
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request_id_var.set(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return problem_response(exc.status, exc.code, exc.title, exc.detail, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem_response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            422, "invalid_request", "Request validation failed", detail=str(exc.errors()[:3])
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        return problem_response(
            500,
            "internal_error",
            "Internal server error",
            detail=f"{type(exc).__name__} (see server logs, request_id={request_id_var.get()})",
        )
