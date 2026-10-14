"""专用 DeepSeek 适配器的离线测试。"""

from __future__ import annotations

import pytest
from test_openai_compat_provider import StubCompletions, StubOpenAI

from sci_rag.config import Settings
from sci_rag.llm.deepseek import DeepSeekLLM

pytest.importorskip("openai")


def _deepseek_with(monkeypatch, completions, settings=None, *, api_key_override=None):
    import openai

    monkeypatch.setattr(
        openai,
        "AsyncOpenAI",
        lambda **kwargs: StubOpenAI(_completions=completions, **kwargs),
    )
    return DeepSeekLLM(
        settings or Settings(_env_file=None, deepseek_api_key="sk-deepseek"),
        api_key_override=api_key_override,
    )


def test_deepseek_uses_dedicated_key_and_endpoint(monkeypatch):
    settings = Settings(_env_file=None, deepseek_api_key="sk-deepseek")
    llm = _deepseek_with(monkeypatch, StubCompletions(), settings)
    assert llm._client.api_key == "sk-deepseek"
    assert llm._client.base_url == "https://api.deepseek.com"
    assert llm.model == "deepseek-flash"
    assert llm.describe() == "deepseek:deepseek-flash"


def test_deepseek_missing_key_fails_closed():
    with pytest.raises(RuntimeError) as caught:
        DeepSeekLLM(Settings(_env_file=None))

    message = str(caught.value)
    assert message == "DeepSeek cannot generate without SCI_RAG_DEEPSEEK_API_KEY."
    assert "sk-" not in message


def test_deepseek_byo_key_overrides_environment_key(monkeypatch):
    settings = Settings(_env_file=None, deepseek_api_key="env-key")
    llm = _deepseek_with(
        monkeypatch,
        StubCompletions(),
        settings,
        api_key_override="byo-key",
    )
    assert llm._client.api_key == "byo-key"
    assert "byo-key" not in llm.describe()
    assert "env-key" not in llm.describe()


def test_deepseek_accepts_byo_only_key(monkeypatch):
    settings = Settings(_env_file=None)
    llm = _deepseek_with(
        monkeypatch,
        StubCompletions(),
        settings,
        api_key_override="byo-only",
    )
    assert llm._client.api_key == "byo-only"
    assert "byo-only" not in llm.describe()


def test_deepseek_rejects_a_generic_override_when_another_provider_is_configured(monkeypatch):
    import openai

    def should_not_construct(**_kwargs):
        raise AssertionError("a generic override must not become a DeepSeek credential")

    monkeypatch.setattr(openai, "AsyncOpenAI", should_not_construct)
    settings = Settings(
        _env_file=None,
        google_api_key="ambient-google-secret",
        deepseek_api_key=None,
    )

    with pytest.raises(RuntimeError) as caught:
        DeepSeekLLM(settings, api_key_override="generic-google-secret")

    message = str(caught.value)
    assert "SCI_RAG_DEEPSEEK_API_KEY" in message
    assert "ambient-google-secret" not in message
    assert "generic-google-secret" not in message


def test_deepseek_ignores_generic_override_when_target_and_other_credentials_exist(monkeypatch):
    settings = Settings(
        _env_file=None,
        google_api_key="ambient-google-secret",
        deepseek_api_key="target-deepseek-key",
    )

    llm = _deepseek_with(
        monkeypatch,
        StubCompletions(),
        settings,
        api_key_override="generic-request-key",
    )

    assert llm._client.api_key == "target-deepseek-key"
    assert "generic-request-key" not in llm.describe()


def test_deepseek_construction_error_does_not_leak_keys(monkeypatch):
    import openai

    def fail_to_construct(**_kwargs):
        raise RuntimeError("SDK initialization failed")

    monkeypatch.setattr(openai, "AsyncOpenAI", fail_to_construct)
    settings = Settings(_env_file=None, deepseek_api_key="env-key")
    with pytest.raises(RuntimeError) as caught:
        DeepSeekLLM(settings, api_key_override="byo-key")

    message = str(caught.value)
    assert message == "SDK initialization failed"
    assert "env-key" not in message
    assert "byo-key" not in message


async def test_deepseek_stream_yields_deltas_and_closes(monkeypatch):
    completions = StubCompletions(text="streamed answer")
    llm = _deepseek_with(monkeypatch, completions)
    chunks = [chunk async for chunk in llm.stream("q")]
    assert "".join(chunks) == "streamed answer"
    assert completions.stream_obj.closed


async def test_deepseek_retries_one_transient_error(monkeypatch):
    completions = StubCompletions(failures=1, text="recovered")
    llm = _deepseek_with(monkeypatch, completions)
    assert await llm.generate("q") == "recovered"
    assert len(completions.requests) == 2


async def test_deepseek_json_mode_sets_response_format(monkeypatch):
    completions = StubCompletions(text='{"ok": true}')
    llm = _deepseek_with(monkeypatch, completions)
    assert await llm.generate_json("q") == {"ok": True}
    assert completions.requests[0]["response_format"] == {"type": "json_object"}
