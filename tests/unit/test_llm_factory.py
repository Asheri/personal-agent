"""Provider dispatch, model identity, and the shared retry predicate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sci_rag.config import Settings
from sci_rag.llm import MockLLM, get_llm
from sci_rag.llm.client import default_is_retryable, retry_async


def _stub_providers(monkeypatch):  # type: ignore[no-untyped-def]
    """Neutralize every SDK so dispatch can be observed without credentials."""
    import sci_rag.llm as llm_package
    import sci_rag.llm.anthropic as anthropic_provider
    import sci_rag.llm.deepseek as deepseek_provider
    import sci_rag.llm.openai_compat as openai_provider

    def fake(name):  # type: ignore[no-untyped-def]
        def build(settings, *, model=None, api_key_override=None):  # type: ignore[no-untyped-def]
            return SimpleNamespace(provider=name, model=model, spec=None, describe=lambda: model)

        return build

    monkeypatch.setattr(llm_package, "GoogleLLM", fake("google"))
    monkeypatch.setattr(anthropic_provider, "AnthropicLLM", fake("anthropic"))
    monkeypatch.setattr(deepseek_provider, "DeepSeekLLM", fake("deepseek"))
    monkeypatch.setattr(openai_provider, "OpenAICompatLLM", fake("openai-compatible"))


@pytest.mark.parametrize(
    ("spec", "expected_provider", "expected_model"),
    [
        ("gemini-2.5-flash", "google", "gemini-2.5-flash"),
        ("anthropic:claude-opus-5", "anthropic", "claude-opus-5"),
        (
            "openai-compatible:xai/grok-4.1-fast-reasoning",
            "openai-compatible",
            "xai/grok-4.1-fast-reasoning",
        ),
        ("deepseek:deepseek-flash", "deepseek", "deepseek-flash"),
    ],
)
def test_get_llm_dispatches_on_the_spec(monkeypatch, spec, expected_provider, expected_model):  # type: ignore[no-untyped-def]
    _stub_providers(monkeypatch)
    client = get_llm(Settings(llm_provider=expected_provider, llm_model=spec))
    assert client.provider == expected_provider
    # Only the bare id goes on the wire; the provider is stripped.
    assert client.model == expected_model


def test_roles_select_different_providers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_providers(monkeypatch)
    settings = Settings(
        llm_provider="google",
        llm_model="anthropic:claude-opus-5",
        extraction_model="gemini-2.5-flash",
        judge_model="openai-compatible:xai/grok-4.1-fast-reasoning",
    )
    assert get_llm(settings, role="answer").provider == "anthropic"
    assert get_llm(settings, role="extraction").provider == "google"
    assert get_llm(settings, role="judge").provider == "openai-compatible"


def test_explicit_model_overrides_the_role(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # This is what --judge-model does.
    _stub_providers(monkeypatch)
    settings = Settings(llm_model="gemini-2.5-flash", judge_model="gemini-2.5-pro")
    client = get_llm(settings, role="judge", model="anthropic:claude-opus-5")
    assert client.provider == "anthropic"


def test_describe_names_the_provider() -> None:
    # Reports and traces need to say who answered, not just which model id.
    client = get_llm(
        Settings(llm_provider="google", google_api_key="k", llm_model="gemini-2.5-flash")
    )
    assert client.describe() == "google:gemini-2.5-flash"
    assert client.model == "gemini-2.5-flash"
    # Hand-built clients have no spec and fall back to the bare id.
    assert MockLLM().describe() == "mock"


class _Status(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (_Status(429), True),
        (_Status(503), True),
        (_Status(400), False),
        (_Status(404), False),
        (RuntimeError("503 UNAVAILABLE"), True),
        (RuntimeError("429 slow down"), True),
        (RuntimeError("RESOURCE_EXHAUSTED"), True),
        (RuntimeError("400 invalid argument"), False),
        # A status code embedded in a longer number is not a status code.
        (RuntimeError("the query returned 1500 rows"), False),
    ],
)
def test_retry_predicate(exc, retryable) -> None:  # type: ignore[no-untyped-def]
    assert default_is_retryable(exc) is retryable


async def test_retry_async_stops_on_non_retryable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import sci_rag.llm.client as llm_client

    async def no_sleep(_seconds):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(llm_client.asyncio, "sleep", no_sleep)
    attempts = []

    async def always_fails():  # type: ignore[no-untyped-def]
        attempts.append(1)
        raise _Status(400)

    with pytest.raises(_Status):
        await retry_async(always_fails)
    assert len(attempts) == 1
