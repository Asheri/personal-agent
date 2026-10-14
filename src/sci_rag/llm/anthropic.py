"""Claude generation, on Vertex AI or the direct Anthropic API.

Two credential modes, mirroring how the Google provider works:

* **Vertex AI** (``SCI_RAG_GCP_PROJECT`` plus application-default
  credentials). Claude is a Vertex partner model, so a lab already on Google
  Cloud needs no new key and no new billing relationship.
* **Direct API** (``SCI_RAG_ANTHROPIC_API_KEY``), which wins when both are
  set, matching the Google provider's "explicit key beats project" rule.

``temperature`` is deliberately *not* forwarded. The SDK dropped it from
``messages.create`` (passing it raises ``TypeError``), and current-generation
models reject it at the API too -- ``claude-sonnet-5`` answers a request
carrying one with ``400: `temperature` is deprecated for this model``. Older
models such as ``claude-haiku-4-5`` still accept it, so this is a
forward-compatibility choice as much as a correctness one. The intent behind a
low temperature (cheap, terse, structured output) maps onto ``effort``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sci_rag.config import Settings
from sci_rag.llm.client import LLMClient, default_is_retryable, retry_async

#: Effort level for JSON-mode calls. Graph extraction and judging are
#: high-volume and structured, so they do not need deep reasoning. Note this
#: lowers effort rather than disabling thinking: disabled thinking on current
#: Claude models can leak reasoning tags or write a tool call into visible
#: text, which would corrupt the JSON these call sites parse.
#:
#: Support varies by model -- ``claude-sonnet-5`` accepts the knob and
#: ``claude-haiku-4-5`` rejects it with a 400 -- so the adapter probes once
#: per client and remembers the answer.
_JSON_EFFORT = "low"


def _is_retryable(exc: Exception) -> bool:
    """Transient-error test that also covers the SDK's connection errors."""
    if type(exc).__name__ in ("APIConnectionError", "APITimeoutError"):
        return True
    return default_is_retryable(exc)


def make_anthropic_client(settings: Settings, *, api_key_override: str | None = None) -> Any:
    """Build an async Anthropic client for whichever credentials are set.

    ``api_key_override`` supports the server's bring-your-own-key flow. It is
    meaningless on Vertex, which authenticates with Google credentials, so
    that combination raises instead of silently ignoring the caller's key.
    """
    try:
        from anthropic import AsyncAnthropic, AsyncAnthropicVertex
    except ImportError as exc:  # pragma: no cover - exercised by the extra
        raise RuntimeError(
            "The anthropic provider needs the 'anthropic' extra. "
            "Install it with: uv sync --extra anthropic"
        ) from exc

    if api_key_override:
        # Bring-your-own-key only makes sense against the direct API. On
        # Vertex the request would be authenticated with the operator's Google
        # credentials, so the caller's key would be silently ignored -- which
        # looks exactly like it worked.
        if not settings.anthropic_api_key and settings.gcp_project:
            raise RuntimeError(
                "A per-request llm_api_key was supplied, but the anthropic provider is "
                "configured for Vertex AI, which authenticates with Google application-default "
                "credentials and cannot use it. Set SCI_RAG_ANTHROPIC_API_KEY to enable "
                "bring-your-own-key for Claude."
            )
        # max_retries=0: sci_rag.llm.client.retry_async owns retry policy, so
        # the SDK's own backoff would compound with it.
        return AsyncAnthropic(api_key=api_key_override, max_retries=0)
    if settings.anthropic_api_key:
        return AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)
    if settings.gcp_project:
        return AsyncAnthropicVertex(
            project_id=settings.gcp_project, region=settings.gcp_location, max_retries=0
        )
    raise RuntimeError(
        "No Anthropic credentials configured. Set SCI_RAG_GCP_PROJECT to use Claude as a "
        "Vertex AI partner model (after `gcloud auth application-default login`), or "
        "SCI_RAG_ANTHROPIC_API_KEY to call the Anthropic API directly."
    )


class AnthropicLLM(LLMClient):
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        api_key_override: str | None = None,
    ) -> None:
        self._client = make_anthropic_client(settings, api_key_override=api_key_override)
        self.model = model or settings.llm_model
        # Whether this model accepts the effort knob: None until the first
        # JSON-mode call finds out. Remembering it matters -- graph extraction
        # makes one call per chunk, and re-learning a rejection every time
        # would double the request count for a whole corpus.
        self._effort_supported: bool | None = None

    def _request(
        self, prompt: str, system: str | None, max_tokens: int, effort: str | None
    ) -> dict[str, Any]:
        """Build request kwargs. ``temperature`` is intentionally absent."""
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            request["system"] = system
        if effort is not None:
            request["output_config"] = {"effort": effort}
        return request

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        want_effort = json_mode and self._effort_supported is not False

        async def call() -> str:
            effort = _JSON_EFFORT if want_effort else None
            try:
                response = await self._client.messages.create(
                    **self._request(prompt, system, max_tokens, effort)
                )
            except Exception as exc:
                # Not every Claude model accepts the effort knob -- Haiku 4.5
                # rejects it outright while Sonnet 5 takes it. Drop it and
                # retry rather than failing the call, the same way the Google
                # adapter handles a rejected thinking budget, and remember the
                # answer so the next call does not pay for it again.
                if effort is not None and _mentions_effort(exc):
                    self._effort_supported = False
                    response = await self._client.messages.create(
                        **self._request(prompt, system, max_tokens, None)
                    )
                else:
                    raise
            else:
                if effort is not None:
                    self._effort_supported = True
            return _text_of(response)

        return await retry_async(call, is_retryable=_is_retryable)

    async def _stream_impl(
        self, prompt: str, system: str | None, max_tokens: int
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            **self._request(prompt, system, max_tokens, None)
        ) as stream:
            async for text in stream.text_stream:
                yield text

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        return self._stream_impl(prompt, system, max_tokens)


def _mentions_effort(exc: Exception) -> bool:
    return "effort" in str(exc).lower() or "output_config" in str(exc).lower()


def _text_of(response: Any) -> str:
    """Join the text blocks of a Messages response.

    A safety decline arrives as a normal 200 with ``stop_reason="refusal"``
    and no text, which would otherwise surface as a confusing empty answer.
    """
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) or "unspecified"
        raise RuntimeError(f"The model declined to answer (refusal category: {category}).")
    parts = [block.text for block in getattr(response, "content", []) or [] if block.type == "text"]
    return "".join(parts)
