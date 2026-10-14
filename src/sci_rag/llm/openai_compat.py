"""Generation through any OpenAI-compatible chat-completions endpoint.

This is the widest of the three adapters, and on Google Cloud it is the only
route to the non-Google partner models: Grok, Llama, Mistral, and DeepSeek are
served from Vertex Model Garden behind an OpenAI-compatible surface rather
than a native API. One adapter therefore covers every current partner model
and every future one that lands on the same endpoint.

Two modes:

* **Vertex AI** (the default when ``SCI_RAG_GCP_PROJECT`` is set and no base
  URL is given). The endpoint is derived from the project and location, and
  requests are authenticated with an application-default OAuth token. Model
  ids carry their publisher prefix, e.g. ``xai/grok-4.1-fast-reasoning``.
* **Anything else** (``SCI_RAG_OPENAI_BASE_URL`` plus
  ``SCI_RAG_OPENAI_API_KEY``): OpenAI itself, or a self-hosted vLLM or Ollama
  server. Leaving the base URL unset with a key present targets OpenAI.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from sci_rag.config import Settings
from sci_rag.llm.client import LLMClient, default_is_retryable, retry_async

if TYPE_CHECKING:
    from openai import AsyncStream
    from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam

#: Scope an application-default token needs to call Vertex AI.
_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def vertex_base_url(project: str, location: str) -> str:
    """The OpenAI-compatible endpoint Vertex serves partner models from.

    The ``global`` location is served by the unprefixed host; every regional
    location prefixes it. That distinction is not cosmetic -- some partner
    models, Grok among them, are *only* offered globally, so getting this
    wrong makes them unreachable rather than merely slower.
    """
    host = (
        "aiplatform.googleapis.com"
        if location == "global"
        else f"{location}-aiplatform.googleapis.com"
    )
    return f"https://{host}/v1/projects/{project}/locations/{location}/endpoints/openapi"


def _is_retryable(exc: Exception) -> bool:
    if type(exc).__name__ in ("APIConnectionError", "APITimeoutError"):
        return True
    return default_is_retryable(exc)


class _VertexToken:
    """An application-default credential, refreshed when it expires.

    Vertex access tokens last about an hour. A long-running ``sci-rag serve``
    process outlives that, so the token is refreshed on demand rather than
    captured once at construction -- otherwise the server starts returning
    401s an hour after boot.
    """

    def __init__(self) -> None:
        import google.auth

        self._credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])

    def _refresh(self) -> None:
        from google.auth.transport.requests import Request

        self._credentials.refresh(Request())

    async def token(self) -> str:
        if not self._credentials.valid:
            # refresh() makes a blocking HTTP call; keep it off the event loop.
            await asyncio.to_thread(self._refresh)
        return str(self._credentials.token)


def _text_or_raise(response: object) -> str:
    """The completion, or an exception naming why there is not one.

    Same reasoning as the Google adapter: an empty string reads as a real
    answer, and for a grounded-answer system that is indistinguishable from
    the legitimate "the corpus does not cover this". Both adapters raise so
    the answer route's existing `generation_failed` path can report it.
    """
    choices = getattr(response, "choices", None) or []
    if choices:
        content = getattr(getattr(choices[0], "message", None), "content", None)
        if content:
            return str(content)
        reason = getattr(choices[0], "finish_reason", None)
        if reason is not None:
            raise RuntimeError(f"the model returned no text (finish_reason={reason})")
    raise RuntimeError("the model returned an empty completion and gave no reason")


class OpenAICompatLLM(LLMClient):
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        api_key_override: str | None = None,
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - exercised by the extra
            raise RuntimeError(
                "The openai-compatible provider needs the 'openai' extra. "
                "Install it with: uv sync --extra openai"
            ) from exc

        key = api_key_override or settings.openai_api_key
        base_url = settings.openai_base_url
        self._vertex: _VertexToken | None = None

        if base_url is None and not key:
            if not settings.gcp_project:
                raise RuntimeError(
                    "The openai-compatible provider has no endpoint configured. Set "
                    "SCI_RAG_GCP_PROJECT to use Vertex AI Model Garden partner models "
                    "(after `gcloud auth application-default login`), or set "
                    "SCI_RAG_OPENAI_API_KEY and optionally SCI_RAG_OPENAI_BASE_URL."
                )
            base_url = vertex_base_url(settings.gcp_project, settings.gcp_location)
            self._vertex = _VertexToken()
            # Replaced per request from the refreshed credential.
            key = "placeholder-replaced-per-request"
        elif not key:
            raise RuntimeError(
                "SCI_RAG_OPENAI_BASE_URL is set but SCI_RAG_OPENAI_API_KEY is not. "
                "Set a key, or unset the base URL to use Vertex AI credentials."
            )

        # max_retries=0: sci_rag.llm.client.retry_async owns retry policy.
        self._client = AsyncOpenAI(api_key=key, base_url=base_url, max_retries=0)
        self.model = model or settings.llm_model

    async def _authorize(self) -> None:
        if self._vertex is not None:
            self._client.api_key = await self._vertex.token()

    def _messages(self, prompt: str, system: str | None) -> list[ChatCompletionMessageParam]:
        messages: list[ChatCompletionMessageParam] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        state = {"json": json_mode}

        def request(json_format: bool) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": self._messages(prompt, system),
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_format:
                payload["response_format"] = {"type": "json_object"}
            return payload

        async def call() -> str:
            await self._authorize()
            try:
                response = await self._client.chat.completions.create(**request(state["json"]))
            except Exception as exc:
                # Not every partner model on Vertex implements JSON mode. Drop
                # the hint and rely on the prompt, the same way the Google
                # adapter falls back when a thinking budget is rejected --
                # generate_json parses loosely either way.
                if state["json"] and "response_format" in str(exc).lower():
                    state["json"] = False
                    response = await self._client.chat.completions.create(**request(False))
                else:
                    raise
            return _text_or_raise(response)

        return await retry_async(call, is_retryable=_is_retryable)

    async def _stream_impl(
        self, prompt: str, system: str | None, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        await self._authorize()
        stream: AsyncStream[ChatCompletionChunk] = await self._client.chat.completions.create(
            model=self.model,
            messages=self._messages(prompt, system),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        # The stream holds an open HTTP response. Closing it is what returns
        # the connection to the pool, so a consumer that stops early (a
        # cancelled SSE request, say) does not leak one per call.
        async with stream:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        return self._stream_impl(prompt, system, temperature, max_tokens)
