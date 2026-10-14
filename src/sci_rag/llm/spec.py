"""Parsing for the ``provider:model`` strings that select a generation model.

A spec names both halves of the choice in one value::

    deepseek-flash                         # the default provider
    anthropic:claude-opus-5                # Claude, on Vertex or the direct API
    openai-compatible:xai/grok-4.1-fast-reasoning
    deepseek:deepseek-flash                # DeepSeek

Leaving the provider off means "whatever ``SCI_RAG_LLM_PROVIDER`` says", so a
configuration written before this module existed keeps working unchanged.

``:`` is a safe separator because no provider puts one in a model id: Vertex
publisher prefixes use ``/`` (``xai/grok-4.1-fast-reasoning``) and Anthropic's
dated snapshots use ``@`` (``claude-opus-4-5@20251101``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from sci_rag.config import LLMProviderName

#: Every provider ``get_llm`` knows how to build, for validation and errors.
KNOWN_PROVIDERS: tuple[LLMProviderName, ...] = get_args(LLMProviderName)


class UnknownProviderError(ValueError):
    """A spec named a provider the kit has no adapter for."""


@dataclass(frozen=True)
class ModelSpec:
    """A provider plus the model id to ask it for."""

    provider: LLMProviderName
    model: str

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


def parse_model_spec(spec: str, *, default_provider: LLMProviderName) -> ModelSpec:
    """Split ``provider:model``, falling back to ``default_provider``.

    A bare model id (no ``:``) takes the default provider. A ``:`` whose left
    side is not a known provider is an error rather than a model id that
    happens to contain a colon -- guessing there would turn a typo into a
    confusing 404 from whichever provider was configured.
    """
    text = spec.strip()
    if not text:
        raise ValueError("Model spec is empty. Use 'model' or 'provider:model'.")
    provider, separator, model = text.partition(":")
    if not separator:
        return ModelSpec(default_provider, text)
    if provider not in KNOWN_PROVIDERS:
        raise UnknownProviderError(
            f"Unknown model provider {provider!r} in {spec!r}. "
            f"Valid providers are: {', '.join(KNOWN_PROVIDERS)}."
        )
    if not model:
        raise ValueError(f"Model spec {spec!r} names a provider but no model.")
    return ModelSpec(provider, model)
