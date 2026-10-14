"""Gemini generation via the google-genai SDK.

Works in either credential mode without code changes -- an AI Studio API key
or Vertex AI application-default credentials -- by reusing the same client
factory the Google embedder uses.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sci_rag.config import Settings
from sci_rag.llm.client import LLMClient, retry_async

# The google-genai SDK logs an advisory about automatic function calling on
# every generate_content call; we do not use AFC, so keep the noise down.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)


#: Markers for "you sent an argument I will not accept". Captured from real
#: responses rather than paraphrased: Gemini 3.x answers a `thinking_budget`
#: it dislikes with a generic invalid-argument error that never names the
#: field, which is why matching the field name alone missed it entirely.
_REJECTED_ARGUMENT_MARKERS = (
    "thinking",
    "invalid argument",
    "invalid_argument",
    "400",
)


def _looks_like_a_rejected_knob(exc: Exception) -> bool:
    """Did the provider refuse the request itself, rather than fail to serve it?

    Deliberately narrow. This is only ever consulted on a call that carried a
    thinking budget, so the question is whether to retry that same call once
    without it. A rate limit or a server error is not a rejected argument and
    must keep propagating, or the real cause disappears behind a second
    failure.
    """
    message = str(exc).lower()
    if any(code in message for code in ("429", "resource_exhausted", "503", "500", "unavailable")):
        return False
    return any(marker in message for marker in _REJECTED_ARGUMENT_MARKERS)


def _text_or_raise(response: object) -> str:
    """The completion, or an exception naming why there is not one.

    `response.text or ""` made an empty completion indistinguishable from a
    real answer. For a grounded-answer system that is the worst possible
    silence: returning nothing looks exactly like "the corpus does not cover
    this", which the kit deliberately supports and reports as a legitimate
    outcome. A safety block and a genuine refusal rendered identically.

    Raising puts it on the path that already exists. `answer/generator.py`
    catches provider exceptions and emits a `generation_failed` event, so the
    failure becomes visible without a new mechanism.
    """
    text = getattr(response, "text", None)
    if text:
        return str(text)

    reason = None
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        reason = getattr(candidates[0], "finish_reason", None)
    if reason is not None:
        raise RuntimeError(f"the model returned no text (finish_reason={reason})")
    raise RuntimeError("the model returned an empty completion and gave no reason")


class GoogleLLM(LLMClient):
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        api_key_override: str | None = None,
    ) -> None:
        # Imported here so offline paths never load the SDK.
        from sci_rag.embed.google import make_genai_client

        self._client = make_genai_client(
            settings, api_key_override=api_key_override, purpose="generation"
        )
        self.model = model or settings.llm_model

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        from google.genai import types

        # Gemini 2.5 models "think" by default, and thought tokens count
        # against max_output_tokens. On high-volume structured calls
        # (extraction, judging) that turns into minutes of latency and
        # sometimes an empty response once the budget is spent on thought.
        # JSON-mode calls therefore ask for as little thinking as possible. A
        # model that rejects this spelling gets the step-down below.
        thinking_config = types.ThinkingConfig(thinking_budget=0) if json_mode else None
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else None,
            thinking_config=thinking_config,
        )
        # How to ask for as little reasoning as possible, most preferred first.
        # `thinking_budget=0` is the 2.5 spelling and 3.x rejects it outright;
        # `thinking_level` is the 3.x spelling. Dropping the knob entirely is
        # the last resort rather than the first fallback, because reasoning
        # tokens come out of `max_output_tokens`, and at the 512-token budgets
        # retrieval and the judge use that truncates the reply mid-value.
        step_down = [
            types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            None,
        ]
        state = {"thinking": thinking_config is not None}

        async def call() -> str:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
            except Exception as exc:
                # Some models reject the thinking knob outright; drop it and
                # try again rather than failing the whole call.
                #
                # Matching on the word "thinking" was not enough. Gemini 3.x
                # rejects `thinking_budget=0` with a bare "Request contains an
                # invalid argument", never naming the knob, so this fallback
                # existed and silently never fired for those models. An
                # unfired fallback is worse than none: it reads as covered.
                # A rejected argument on a request we know carried an unusual
                # one is the signal, not the provider's choice of words. Rate
                # limits and server errors still propagate, because retrying
                # those without the knob would hide their cause.
                if not (state["thinking"] and _looks_like_a_rejected_knob(exc)):
                    raise
                # Walk down the spellings until one is accepted. Each rejection
                # has to look like a refused argument, so a rate limit part way
                # through still surfaces as itself.
                while step_down:
                    config.thinking_config = step_down.pop(0)
                    state["thinking"] = config.thinking_config is not None
                    try:
                        response = await self._client.aio.models.generate_content(
                            model=self.model, contents=prompt, config=config
                        )
                        break
                    except Exception as retry_exc:
                        if not (state["thinking"] and _looks_like_a_rejected_knob(retry_exc)):
                            raise
                else:
                    raise
            return _text_or_raise(response)

        return await retry_async(call)

    async def _stream_impl(
        self, prompt: str, system: str | None, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        stream = await self._client.aio.models.generate_content_stream(
            model=self.model, contents=prompt, config=config
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        return self._stream_impl(prompt, system, temperature, max_tokens)
