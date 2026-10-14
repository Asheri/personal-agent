"""Per-request answer keys stay on the provider selected for the answer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sci_rag.answer.generator import AnswerEngine
from sci_rag.config import Settings


class _Retriever:
    domain = None


@pytest.mark.parametrize(
    ("provider", "model", "key_field", "other_field"),
    [
        ("deepseek", "deepseek-flash", "deepseek_api_key", "google_api_key"),
        ("google", "gemini-3.6-flash", "google_api_key", "deepseek_api_key"),
        ("anthropic", "claude-haiku-4-5", "anthropic_api_key", "google_api_key"),
        (
            "openai-compatible",
            "xai/grok-4.1-fast",
            "openai_api_key",
            "deepseek_api_key",
        ),
    ],
)
def test_answer_byo_key_is_written_to_the_answer_provider_field(
    monkeypatch,
    provider: str,
    model: str,
    key_field: str,
    other_field: str,
) -> None:
    captured: dict[str, object] = {}

    def build(settings, **kwargs):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured.update(kwargs)
        return SimpleNamespace(provider=provider)

    monkeypatch.setattr("sci_rag.answer.generator.get_llm", build)
    settings = Settings(
        _env_file=None,
        llm_provider=provider,
        llm_model=model,
        google_api_key=None,
        gcp_project=None,
        anthropic_api_key=None,
        openai_api_key=None,
        deepseek_api_key=None,
    )
    engine = AnswerEngine(settings=settings, retriever=_Retriever())  # type: ignore[arg-type]

    client = engine._resolve_llm("byo-answer-key")

    assert client.provider == provider
    routed_settings = captured["settings"]
    assert getattr(routed_settings, key_field) == "byo-answer-key"
    assert getattr(routed_settings, other_field) is None
    assert captured.get("api_key_override") is None


def test_answer_scoped_deepseek_byo_succeeds_with_ambient_google_key(monkeypatch) -> None:
    from sci_rag.llm.deepseek import DeepSeekLLM
    from sci_rag.llm.openai_compat import OpenAICompatLLM

    captured: dict[str, object] = {}

    def capture_init(
        self,
        settings,
        *,
        model=None,
        api_key_override=None,
    ):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured["api_key_override"] = api_key_override
        self.model = model or settings.llm_model

    monkeypatch.setattr(OpenAICompatLLM, "__init__", capture_init)
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        llm_model="deepseek-flash",
        google_api_key="ambient-google-secret",
        deepseek_api_key=None,
    )
    engine = AnswerEngine(settings=settings, retriever=_Retriever())  # type: ignore[arg-type]

    client = engine._resolve_llm("deepseek-request-key")

    assert isinstance(client, DeepSeekLLM)
    routed_settings = captured["settings"]
    assert routed_settings.deepseek_api_key == "deepseek-request-key"
    assert routed_settings.openai_api_key == "deepseek-request-key"
    assert captured["api_key_override"] is None
    assert routed_settings.google_api_key == "ambient-google-secret"
    assert routed_settings.openai_api_key != routed_settings.google_api_key


def test_generic_override_to_google_is_rejected_with_ambient_google_adc(
    monkeypatch,
) -> None:
    from sci_rag.llm import get_llm

    def should_not_build(_settings, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("a generic override must not bypass the credential guard")

    monkeypatch.setattr("sci_rag.llm.GoogleLLM", should_not_build)
    settings = Settings(
        _env_file=None,
        llm_provider="google",
        llm_model="gemini-3.6-flash",
        google_api_key=None,
        gcp_project="ambient-google-project",
        deepseek_api_key=None,
    )

    with pytest.raises(RuntimeError) as caught:
        get_llm(settings, api_key_override="deepseek-request-key")

    message = str(caught.value)
    assert "generic API key" in message
    assert "SCI_RAG_GOOGLE_API_KEY" in message
    assert "deepseek-request-key" not in message
    assert "ambient-google-project" not in message


def test_generic_override_is_ignored_when_target_and_other_credentials_exist(
    monkeypatch,
) -> None:
    from sci_rag.llm import get_llm

    captured: dict[str, object] = {}

    class CapturingDeepSeek:
        def __init__(self, settings, *, model=None, api_key_override=None):  # type: ignore[no-untyped-def]
            captured["settings"] = settings
            captured["api_key_override"] = api_key_override
            self.model = model

    monkeypatch.setattr("sci_rag.llm.deepseek.DeepSeekLLM", CapturingDeepSeek)
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        llm_model="deepseek-flash",
        google_api_key="ambient-google-secret",
        deepseek_api_key="target-deepseek-key",
    )

    client = get_llm(settings, api_key_override="generic-request-key")

    assert client.spec.provider == "deepseek"
    assert captured["settings"].deepseek_api_key == "target-deepseek-key"
    assert captured["api_key_override"] is None


def test_generic_override_is_ordinary_byo_without_other_credentials(monkeypatch) -> None:
    from sci_rag.llm import get_llm

    captured: dict[str, object] = {}

    class CapturingDeepSeek:
        def __init__(self, settings, *, model=None, api_key_override=None):  # type: ignore[no-untyped-def]
            captured["api_key_override"] = api_key_override
            self.model = model

    monkeypatch.setattr("sci_rag.llm.deepseek.DeepSeekLLM", CapturingDeepSeek)
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        llm_model="deepseek-flash",
        google_api_key=None,
        gcp_project=None,
        anthropic_api_key=None,
        openai_api_key=None,
        deepseek_api_key=None,
    )

    client = get_llm(settings, api_key_override="byo-only-key")

    assert client.spec.provider == "deepseek"
    assert captured["api_key_override"] == "byo-only-key"
