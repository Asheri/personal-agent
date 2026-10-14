"""The LLM interface used everywhere generation happens.

One abstraction covers answer generation, graph extraction, HyDE passages,
community summaries, reranking, query routing, and the evaluation judge. The
adapters that implement it live in sibling modules -- one per provider, the
same layout ``sci_rag.embed`` uses -- and are selected by
:func:`sci_rag.llm.get_llm`. Tests use :class:`MockLLM`, which replays canned
responses and records every prompt it saw.
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import structlog

from sci_rag.llm.spec import ModelSpec

log = structlog.get_logger(__name__)

_MAX_ATTEMPTS = 3
T = TypeVar("T")

#: HTTP statuses worth a second attempt: throttling and server-side faults.
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})

#: gRPC/Google status names that mean the same thing.
_RETRYABLE_MARKERS = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED")

#: Matches a status code as a standalone token, so an error whose *text*
#: happens to contain "500" is not mistaken for a server error.
_STATUS_IN_TEXT = re.compile(r"\b(?:" + "|".join(str(s) for s in sorted(RETRYABLE_STATUS)) + r")\b")


def status_code_of(exc: Exception) -> int | None:
    """The HTTP status an SDK exception carries, if it carries one."""
    for attribute in ("status_code", "code", "status"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    return None


def default_is_retryable(exc: Exception) -> bool:
    """Whether a provider error is worth retrying.

    Typed SDK exceptions expose a status code, which is authoritative. Plain
    exceptions fall back to scanning the message, matching status codes only
    as whole tokens.
    """
    code = status_code_of(exc)
    if code is not None:
        return code in RETRYABLE_STATUS
    text = str(exc)
    return any(marker in text for marker in _RETRYABLE_MARKERS) or bool(
        _STATUS_IN_TEXT.search(text)
    )


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    is_retryable: Callable[[Exception], bool] = default_is_retryable,
    max_attempts: int = _MAX_ATTEMPTS,
) -> T:
    """Run ``operation`` with exponential backoff on transient provider errors.

    Every adapter shares this loop, and the SDK clients are built with their
    own retries disabled, so the kit has exactly one retry policy to reason
    about and one ``llm_retry`` event to watch in the logs.
    """
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            if attempt == max_attempts or not is_retryable(exc):
                raise
            log.warning("llm_retry", attempt=attempt, delay_s=delay, error=type(exc).__name__)
            await asyncio.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


class LLMClient(ABC):
    #: The provider's own model id, exactly as sent on the wire.
    model: str = ""
    #: Which provider serves that id. Set by :func:`sci_rag.llm.get_llm`;
    #: ``None`` for hand-built clients such as :class:`MockLLM`.
    spec: ModelSpec | None = None

    def describe(self) -> str:
        """Identity for traces and reports: ``provider:model`` when known.

        Answers and eval reports record which model produced them. With more
        than one provider in play, the bare model id is no longer enough to
        say who was asked.
        """
        return str(self.spec) if self.spec is not None else self.model

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        """Return the model's full text response."""

    @abstractmethod
    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Yield the response incrementally as text deltas."""

    async def generate_json(
        self, prompt: str, *, system: str | None = None, max_tokens: int = 4096
    ) -> Any:
        """Generate and parse a JSON response, tolerating code fences."""
        raw = await self.generate(
            prompt, system=system, temperature=0.0, max_tokens=max_tokens, json_mode=True
        )
        return parse_json_loosely(raw)


def parse_json_loosely(raw: str) -> Any:
    """Parse model output as JSON, stripping markdown fences if present."""
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


@dataclass
class MockLLM(LLMClient):
    """Deterministic stand-in for tests: replays queued responses in order.

    When the queue runs dry it returns ``default_response``, so tests only
    queue what they assert on.
    """

    responses: list[str] = field(default_factory=list)
    default_response: str = "{}"
    calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = "mock"

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        self.calls.append(
            {"prompt": prompt, "system": system, "temperature": temperature, "json_mode": json_mode}
        )
        if self.responses:
            return self.responses.pop(0)
        return self.default_response

    async def _stream_impl(self, text: str) -> AsyncIterator[str]:
        # Stream in small pieces so consumers exercise their delta handling.
        for start in range(0, len(text), 24):
            yield text[start : start + 24]

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        self.calls.append({"prompt": prompt, "system": system, "stream": True})
        text = self.responses.pop(0) if self.responses else self.default_response
        return self._stream_impl(text)
