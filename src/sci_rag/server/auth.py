"""Authentication: static API keys by default, a clean seam for OAuth later.

The default backend reads ``SCI_RAG_API_KEYS``, a JSON map of key to
settings::

    {"team-key-1": {"scopes": ["retrieval:query", "retrieval:answer"],
                    "rate_limit_per_minute": 60},
     "agent-key":  {"scopes": ["retrieval:query", "retrieval:answer",
                                "corpus:read", "byo_llm"]}}

With no keys configured the server runs OPEN (every request gets every
scope) and warns loudly at startup; that is the right default for
localhost development and the wrong one for anything public.

The seam for a real identity provider is the :class:`AuthBackend`
interface plus one line in the app factory; swap in an OAuth token
verifier without touching any route. Scopes are the contract:

* ``retrieval:query``: run retrieval
* ``retrieval:answer``: generate answers (spends LLM tokens)
* ``corpus:read``: browse the document catalog
* ``byo_llm``: allowed to supply a per-request LLM key
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog
from fastapi import Depends, Request
from fastapi.security.utils import get_authorization_scheme_param

from sci_rag.server.errors import ApiError

log = structlog.get_logger(__name__)

ALL_SCOPES = ("retrieval:query", "retrieval:answer", "corpus:read", "byo_llm")


# Rate limit accounting needs an identity that tells two credentials apart.
# A truncated key does not: two keys beginning alike collapse into one bucket
# and either caller can throttle the other, which is what F-017 reproduced.
#
# The salt is generated once per process and never written down. The limiter
# keeps its windows in process memory and drops them on restart, so identity
# only has to be stable for that long, and nothing durable derived from a raw
# key exists to be attacked offline.
_LIMITER_SALT = secrets.token_bytes(32)


def limiter_identity(token: str) -> str:
    """An opaque per process identity for the whole token.

    Distinct tokens get distinct identities and the same token always gets
    the same one, without the raw credential being stored anywhere.
    """
    digest = hmac.new(_LIMITER_SALT, token.encode("utf-8"), hashlib.blake2s).hexdigest()
    return f"key:{digest}"


@dataclass
class AuthContext:
    key_id: str
    scopes: tuple[str, ...]
    llm_api_key: str | None = None  # per-key BYO binding; never logged
    rate_limit_per_minute: int | None = None
    # Defaults to key_id so a backend with nothing to tell apart, such as the
    # open one, keeps its single shared bucket.
    rate_limit_id: str | None = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    @property
    def limiter_key(self) -> str:
        """What the rate limiter counts against."""
        return self.rate_limit_id or self.key_id


class AuthBackend(ABC):
    @abstractmethod
    def authenticate(self, token: str | None) -> AuthContext:
        """Return the context for a bearer token, or raise :class:`ApiError`."""

    @abstractmethod
    def check_rate(self, context: AuthContext) -> None:
        """Raise :class:`ApiError` (429) when the key is over its limit."""


class OpenBackend(AuthBackend):
    """No keys configured: everything allowed. Development only."""

    def authenticate(self, token: str | None) -> AuthContext:
        return AuthContext(key_id="anonymous", scopes=ALL_SCOPES)

    def check_rate(self, context: AuthContext) -> None:
        return


class _MinuteWindowLimiter:
    """A small fixed-window limiter, per key, in process memory. Good enough
    for a single instance; put a shared limiter in front for fleets.

    The window is wall-clock: it starts at the top of a minute rather than at
    the caller's first request, so a caller that arrives late in a minute gets
    a short one. That is the accepted trade for a limiter this small, and it
    is why the clock is injectable. A test that spends a budget and asserts
    the refusal would otherwise pass or fail on when in the minute it ran, and
    two of them did.
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._windows: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    def allow(self, key_id: str, per_minute: int) -> tuple[bool, int]:
        now = self._clock()
        window = int(now // 60)
        if len(self._windows) > 1024:
            # Keys rotate; stale windows must not accumulate forever.
            stale = [k for k, (w, _) in self._windows.items() if w != window]
            for k in stale:
                del self._windows[k]
        current_window, used = self._windows[key_id]
        if current_window != window:
            current_window, used = window, 0
        if used >= per_minute:
            retry_after = 60 - int(now % 60)
            return False, max(retry_after, 1)
        self._windows[key_id] = (current_window, used + 1)
        return True, 0


@dataclass
class StaticKeyBackend(AuthBackend):
    keys: dict[str, dict]
    default_rate_limit_per_minute: int = 120
    _limiter: _MinuteWindowLimiter = field(default_factory=_MinuteWindowLimiter)

    @classmethod
    def from_json(cls, raw: str) -> StaticKeyBackend:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SCI_RAG_API_KEYS is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict) or not parsed:
            raise RuntimeError(
                "SCI_RAG_API_KEYS must be a non-empty JSON object of key -> settings."
            )
        return cls(keys=parsed)

    def authenticate(self, token: str | None) -> AuthContext:
        if not token:
            raise ApiError(
                401,
                "missing_key",
                "Authentication required",
                "Send an API key: Authorization: Bearer <key>.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        entry = self.keys.get(token)
        if entry is None:
            raise ApiError(
                401,
                "invalid_key",
                "Unknown API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scopes = tuple(entry.get("scopes") or ALL_SCOPES)
        return AuthContext(
            # A short label a human can read in a log without it being the key.
            key_id=f"key:{token[:6]}...",
            rate_limit_id=limiter_identity(token),
            scopes=scopes,
            llm_api_key=entry.get("llm_api_key"),
            rate_limit_per_minute=entry.get(
                "rate_limit_per_minute", self.default_rate_limit_per_minute
            ),
        )

    def check_rate(self, context: AuthContext) -> None:
        if not context.rate_limit_per_minute:
            return
        allowed, retry_after = self._limiter.allow(
            context.limiter_key, context.rate_limit_per_minute
        )
        if not allowed:
            raise ApiError(
                429,
                "rate_limited",
                "Rate limit exceeded",
                f"This key allows {context.rate_limit_per_minute} requests per minute.",
                headers={"Retry-After": str(retry_after)},
            )


def build_auth_backend(api_keys_json: str | None, *, cors_origins: str = "*") -> AuthBackend:
    if api_keys_json:
        if cors_origins.strip() == "*":
            log.warning(
                "cors_wide_open_with_auth",
                note="API keys are configured but SCI_RAG_CORS_ORIGINS is '*'. "
                "Consider restricting origins for browser-facing deployments.",
            )
        return StaticKeyBackend.from_json(api_keys_json)
    log.warning(
        "auth_disabled",
        note="No SCI_RAG_API_KEYS configured; the server is open. Fine on localhost, not in public.",
    )
    return OpenBackend()


#: A header no platform claims. Google's Cloud Run frontend inspects
#: `Authorization: Bearer` and rejects anything that is not one of its own
#: identity tokens before the request reaches the container, so on the
#: platform this repository documents deploying to, the documented header
#: cannot carry the kit's own keys. This is the way in that survives.
API_KEY_HEADER = "X-API-Key"


def api_key_from_headers(authorization: str, api_key_header: str | None) -> str | None:
    """The caller's API key, from whichever header carried it.

    `X-API-Key` wins when both are present, because `Authorization` is not
    always the caller's to spend. A private Cloud Run service requires a
    Google identity token in `Authorization`, so preferring that header made
    authentication impossible on exactly the deployment `docs/deploy-gcp.md`
    describes: the identity token shadowed the key and every request came
    back 401 `invalid_key`. An explicit `X-API-Key` is a caller stating which
    credential it means; `Authorization` may have been set by infrastructure.

    Callers that send only `Authorization: Bearer <key>`, which is every local
    and single-header client, are unaffected.

    Shared rather than duplicated because the REST routes and the MCP mount
    extract this in different files, and two copies of an auth rule is one too
    many.
    """
    if api_key_header:
        return api_key_header
    scheme, token = get_authorization_scheme_param(authorization or "")
    if scheme.lower() == "bearer" and token:
        return token
    return None


def require_scopes(*scopes: str):  # type: ignore[no-untyped-def]
    """FastAPI dependency: authenticate the bearer token and check scopes."""

    async def dependency(request: Request) -> AuthContext:
        backend: AuthBackend = request.app.state.auth_backend
        token = api_key_from_headers(
            request.headers.get("Authorization", ""), request.headers.get(API_KEY_HEADER)
        )
        context = backend.authenticate(token)
        for scope in scopes:
            if not context.has_scope(scope):
                raise ApiError(
                    403,
                    "insufficient_scope",
                    "Insufficient scope",
                    f"This operation requires the {scope!r} scope.",
                )
        backend.check_rate(context)
        return context

    return Depends(dependency)
