"""Offline tests for the Anthropic provider, via a scripted stub client.

The load-bearing assertion is that ``temperature`` never reaches the wire:
current Claude models removed the sampling parameters and reject the field
with a 400, but ``LLMClient.generate`` passes one on every call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import sci_rag.llm.client as llm_client
from sci_rag.config import Settings
from sci_rag.llm.anthropic import AnthropicLLM, make_anthropic_client

# The provider is unusable without its extra; CI installs it.
pytest.importorskip("anthropic")


def _settings(**overrides):  # type: ignore[no-untyped-def]
    values = {"gcp_project": "demo-project", "llm_model": "claude-opus-5"}
    values.update(overrides)
    return Settings(**values)


class StubMessages:
    """Records every request; can reject the effort knob or rate-limit."""

    def __init__(self, *, reject_effort=False, failures=0, text="hello", stop_reason="end_turn"):  # type: ignore[no-untyped-def]
        self.reject_effort = reject_effort
        self.failures = failures
        self.text = text
        self.stop_reason = stop_reason
        self.requests: list[dict] = []

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.requests.append(kwargs)
        if self.reject_effort and "output_config" in kwargs:
            raise RuntimeError("output_config.effort is not supported for this model")
        if self.failures:
            self.failures -= 1
            raise RuntimeError("503 UNAVAILABLE")
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(category="harmful_content"),
            content=[SimpleNamespace(type="text", text=self.text)],
        )

    def stream(self, **kwargs):  # type: ignore[no-untyped-def]
        self.requests.append(kwargs)
        return _StubStream(self.text)


class _StubStream:
    def __init__(self, text: str) -> None:
        self._text = text

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
        return False

    @property
    def text_stream(self):  # type: ignore[no-untyped-def]
        async def gen():  # type: ignore[no-untyped-def]
            for start in range(0, len(self._text), 3):
                yield self._text[start : start + 3]

        return gen()


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):  # type: ignore[no-untyped-def]
    async def no_sleep(_seconds):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(llm_client.asyncio, "sleep", no_sleep)


def _llm_with(monkeypatch, messages, settings=None):  # type: ignore[no-untyped-def]
    import sci_rag.llm.anthropic as provider

    monkeypatch.setattr(
        provider, "make_anthropic_client", lambda *a, **k: SimpleNamespace(messages=messages)
    )
    return AnthropicLLM(settings or _settings())


async def test_temperature_is_never_sent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    messages = StubMessages(text='{"ok": true}')
    llm = _llm_with(monkeypatch, messages)

    await llm.generate("hi", temperature=0.7)
    await llm.generate_json("give me json")  # generate_json asks for 0.0

    assert messages.requests, "expected the stub to receive a request"
    assert all("temperature" not in request for request in messages.requests)


async def test_json_mode_lowers_effort_instead_of_disabling_thinking(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    messages = StubMessages(text='{"ok": true}')
    llm = _llm_with(monkeypatch, messages)

    assert await llm.generate_json("json please") == {"ok": True}
    assert messages.requests[0]["output_config"] == {"effort": "low"}
    # Prose calls leave the model's default reasoning alone.
    await llm.generate("prose please")
    assert "output_config" not in messages.requests[1]


async def test_effort_rejection_falls_back(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    messages = StubMessages(reject_effort=True, text='{"ok": 1}')
    llm = _llm_with(monkeypatch, messages)

    assert await llm.generate_json("json please") == {"ok": 1}
    assert "output_config" in messages.requests[0]
    assert "output_config" not in messages.requests[-1]


async def test_effort_rejection_is_remembered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Claude Haiku 4.5 rejects the effort knob while Sonnet 5 accepts it, so
    # the fallback is unavoidable -- but re-learning it on every call would
    # double the request count for a whole graph-extraction run.
    messages = StubMessages(reject_effort=True, text='{"ok": 1}')
    llm = _llm_with(monkeypatch, messages)

    for _ in range(3):
        await llm.generate_json("json please")

    with_effort = [r for r in messages.requests if "output_config" in r]
    assert len(with_effort) == 1, "effort should be attempted once, then remembered"
    assert len(messages.requests) == 4, "one probe plus three real calls"


async def test_effort_support_is_remembered_when_accepted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    messages = StubMessages(text='{"ok": 1}')
    llm = _llm_with(monkeypatch, messages)

    for _ in range(3):
        await llm.generate_json("json please")

    assert all("output_config" in request for request in messages.requests)
    assert len(messages.requests) == 3, "no wasted calls when the model accepts it"


async def test_system_prompt_is_a_top_level_field(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    messages = StubMessages()
    llm = _llm_with(monkeypatch, messages)

    await llm.generate("hi", system="be terse", max_tokens=64)
    request = messages.requests[0]
    assert request["system"] == "be terse"
    assert request["max_tokens"] == 64
    assert request["messages"] == [{"role": "user", "content": "hi"}]


async def test_generate_retries_transient_errors(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    messages = StubMessages(failures=1, text="recovered")
    llm = _llm_with(monkeypatch, messages)

    assert await llm.generate("q") == "recovered"
    assert len(messages.requests) == 2


async def test_refusal_is_not_reported_as_an_empty_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    messages = StubMessages(stop_reason="refusal", text="")
    llm = _llm_with(monkeypatch, messages)

    with pytest.raises(RuntimeError, match="declined"):
        await llm.generate("q")


async def test_stream_yields_deltas(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    messages = StubMessages(text="streamed answer")
    llm = _llm_with(monkeypatch, messages)

    chunks = [chunk async for chunk in llm.stream("q")]
    assert "".join(chunks) == "streamed answer"
    assert len(chunks) > 1


def test_vertex_project_selects_the_vertex_client(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import anthropic

    built: dict = {}
    monkeypatch.setattr(
        anthropic, "AsyncAnthropicVertex", lambda **kw: built.update(kw) or SimpleNamespace()
    )
    make_anthropic_client(_settings(gcp_location="europe-west1"))
    assert built == {"project_id": "demo-project", "region": "europe-west1", "max_retries": 0}


def test_explicit_key_beats_a_vertex_project(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import anthropic

    built: dict = {}
    monkeypatch.setattr(
        anthropic, "AsyncAnthropic", lambda **kw: built.update(kw) or SimpleNamespace()
    )
    make_anthropic_client(_settings(anthropic_api_key="sk-test"))
    assert built["api_key"] == "sk-test"
    # retry_async owns the retry policy; the SDK must not compound it.
    assert built["max_retries"] == 0


def test_byo_key_on_vertex_fails_loudly() -> None:
    # Silently ignoring the caller's key would look exactly like success.
    with pytest.raises(RuntimeError, match="bring-your-own-key"):
        make_anthropic_client(_settings(), api_key_override="sk-caller")


def test_missing_credentials_names_both_options() -> None:
    with pytest.raises(RuntimeError, match="SCI_RAG_ANTHROPIC_API_KEY"):
        make_anthropic_client(_settings(gcp_project=None))
