"""Generation providers and the factory that selects one.

``get_llm`` is the only place a provider is chosen. Keeping the supported set
visible in a single ``if`` chain -- rather than behind a plug-in loader -- is
the same trade-off ``sci_rag.embed`` makes, and it means a reader can see
every backend the kit talks to without leaving this file.
"""

from sci_rag.config import LLMProviderName, LLMRole, Settings
from sci_rag.llm.client import (
    LLMClient,
    MockLLM,
    parse_json_loosely,
    retry_async,
)
from sci_rag.llm.google import GoogleLLM
from sci_rag.llm.spec import ModelSpec, UnknownProviderError, parse_model_spec

_PROVIDER_API_KEY_FIELDS: dict[LLMProviderName, str] = {
    "google": "google_api_key",
    "anthropic": "anthropic_api_key",
    "openai-compatible": "openai_api_key",
    "deepseek": "deepseek_api_key",
}
_PROVIDER_CREDENTIAL_FIELDS = (
    "google_api_key",
    "gcp_project",
    "anthropic_api_key",
    "openai_api_key",
    "deepseek_api_key",
)
_PROVIDER_API_KEY_ENV: dict[LLMProviderName, str] = {
    "google": "SCI_RAG_GOOGLE_API_KEY",
    "anthropic": "SCI_RAG_ANTHROPIC_API_KEY",
    "openai-compatible": "SCI_RAG_OPENAI_API_KEY",
    "deepseek": "SCI_RAG_DEEPSEEK_API_KEY",
}


def _provider_api_key_field(provider: LLMProviderName) -> str:
    field = _PROVIDER_API_KEY_FIELDS.get(provider)
    if field is None:
        raise ValueError(f"Unsupported LLM provider: {provider!r}.")
    return field


def resolve_llm_api_key_override(
    settings: Settings,
    provider: LLMProviderName,
    api_key_override: str | None,
) -> str | None:
    """Resolve an unscoped override without letting it cross a credential boundary.

    A target-specific field wins when another ambient credential is present.
    Without a target field, the ambient credential makes the generic value
    ambiguous, so construction fails instead of choosing an endpoint for the
    caller. With no ambient credential, the override remains ordinary BYO.
    """
    if not api_key_override:
        return None

    target_field = _provider_api_key_field(provider)
    other_fields = [
        field
        for field in _PROVIDER_CREDENTIAL_FIELDS
        if field != target_field and getattr(settings, field)
    ]
    if getattr(settings, target_field):
        return None if other_fields else api_key_override
    if other_fields:
        raise RuntimeError(
            f"{provider} cannot use a generic API key while another credential is "
            f"configured. Set {_PROVIDER_API_KEY_ENV[provider]} or remove the other "
            "credential."
        )
    return api_key_override


def settings_with_llm_api_key(
    settings: Settings,
    provider: LLMProviderName,
    api_key: str,
) -> Settings:
    """Place a per-request key on the selected provider's own credential field.

    This is the provider-scoped path used by request-level BYO. It intentionally
    writes only the selected provider's field and leaves ambient settings intact;
    callers passing an unscoped generic value must first use
    :func:`resolve_llm_api_key_override`.
    """
    field = _provider_api_key_field(provider)
    return settings.model_copy(update={field: api_key})


def get_llm(
    settings: Settings,
    *,
    role: LLMRole = "answer",
    model: str | None = None,
    api_key_override: str | None = None,
) -> LLMClient:
    """Build the client for a call site.

    ``role`` picks which configured model spec applies -- answers, high-volume
    extraction, or the evaluation judge. ``model`` overrides it with an
    explicit spec (``"model"`` or ``"provider:model"``), which is what the
    ``--judge-model`` flag passes.
    """
    spec = (
        parse_model_spec(model, default_provider=settings.llm_provider)
        if model
        else settings.model_spec_for(role)
    )
    resolved_override = resolve_llm_api_key_override(
        settings,
        spec.provider,
        api_key_override,
    )

    client: LLMClient
    if spec.provider == "anthropic":
        # Imported lazily: these providers are optional extras, and offline
        # runs must never need their SDKs installed.
        from sci_rag.llm.anthropic import AnthropicLLM

        client = AnthropicLLM(settings, model=spec.model, api_key_override=resolved_override)
    elif spec.provider == "openai-compatible":
        from sci_rag.llm.openai_compat import OpenAICompatLLM

        client = OpenAICompatLLM(settings, model=spec.model, api_key_override=resolved_override)
    elif spec.provider == "deepseek":
        from sci_rag.llm.deepseek import DeepSeekLLM

        client = DeepSeekLLM(settings, model=spec.model, api_key_override=resolved_override)
    else:
        client = GoogleLLM(settings, model=spec.model, api_key_override=resolved_override)

    client.spec = spec
    return client


__all__ = [
    "GoogleLLM",
    "LLMClient",
    "MockLLM",
    "ModelSpec",
    "UnknownProviderError",
    "get_llm",
    "parse_json_loosely",
    "parse_model_spec",
    "resolve_llm_api_key_override",
    "retry_async",
    "settings_with_llm_api_key",
]
