"""Offline tests for the OpenAI-compatible provider.

Two behaviours carry the most risk and are covered first: deriving the Vertex
Model Garden endpoint from the project and location, and refreshing the
application-default token, which expires roughly hourly and would otherwise
make a long-running server start returning 401s.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import sci_rag.llm.client as llm_client
from sci_rag.config import Settings
from sci_rag.llm.openai_compat import OpenAICompatLLM, vertex_base_url

# The provider is unusable without its extra; CI installs it.
pytest.importorskip("openai")


def _settings(**overrides):  # type: ignore[no-untyped-def]
    values = {"gcp_project": "demo-project", "llm_model": "xai/grok-4.1-fast-reasoning"}
    values.update(overrides)
    return Settings(**values)


class StubCompletions:
    def __init__(self, *, reject_json=False, failures=0, text="hello"):  # type: ignore[no-untyped-def]
        self.reject_json = reject_json
        self.failures = failures
        self.text = text
        self.requests: list[dict] = []
        self.keys_seen: list[str] = []

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.requests.append(kwargs)
        if self.reject_json and "response_format" in kwargs:
            raise RuntimeError("response_format is not supported by this model")
        if self.failures:
            self.failures -= 1
            raise RuntimeError("429 too many requests")
        if kwargs.get("stream"):
            self.stream_obj = _StubStream(self.text)
            return self.stream_obj
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))]
        )


class _StubStream:
    """Mimics openai's AsyncStream: iterable, and an async context manager.

    Records closure so the test can assert the adapter returns the connection
    to the pool rather than leaking it.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self.closed = False

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
        self.closed = True
        return False

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for start in range(0, len(self._text), 3):
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(delta=SimpleNamespace(content=self._text[start : start + 3]))
                ]
            )


class StubOpenAI:
    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        self.init_kwargs = kwargs
        self.api_key = kwargs.get("api_key")
        self.base_url = kwargs.get("base_url")
        self.chat = SimpleNamespace(completions=kwargs.pop("_completions"))


class StubCredentials:
    """Invalid on first use, then valid, so refresh() is observable."""

    def __init__(self) -> None:
        self.valid = False
        self.token = "stale-token"
        self.refreshes = 0

    def refresh(self, _request) -> None:  # type: ignore[no-untyped-def]
        self.refreshes += 1
        self.valid = True
        self.token = f"fresh-token-{self.refreshes}"


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):  # type: ignore[no-untyped-def]
    async def no_sleep(_seconds):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(llm_client.asyncio, "sleep", no_sleep)


def _llm_with(monkeypatch, completions, settings=None, credentials=None):  # type: ignore[no-untyped-def]
    import google.auth
    import openai

    monkeypatch.setattr(
        openai, "AsyncOpenAI", lambda **kw: StubOpenAI(_completions=completions, **kw)
    )
    monkeypatch.setattr(
        google.auth, "default", lambda **kw: (credentials or StubCredentials(), "demo-project")
    )
    return OpenAICompatLLM(settings or _settings())


def test_vertex_base_url_shape() -> None:
    assert vertex_base_url("demo-project", "us-central1") == (
        "https://us-central1-aiplatform.googleapis.com/v1/"
        "projects/demo-project/locations/us-central1/endpoints/openapi"
    )


def test_gcp_project_derives_the_vertex_endpoint(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    llm = _llm_with(monkeypatch, StubCompletions(), _settings(gcp_location="europe-west1"))
    assert llm._client.base_url == vertex_base_url("demo-project", "europe-west1")
    # retry_async owns the retry policy; the SDK must not compound it.
    assert llm._client.init_kwargs["max_retries"] == 0


async def test_expired_vertex_token_is_refreshed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    credentials = StubCredentials()
    completions = StubCompletions()
    llm = _llm_with(monkeypatch, completions, credentials=credentials)

    await llm.generate("q")
    assert credentials.refreshes == 1
    assert llm._client.api_key == "fresh-token-1"

    # Still valid, so the second call reuses it rather than refreshing again.
    await llm.generate("q")
    assert credentials.refreshes == 1

    # Once it expires, the next call picks up a new one.
    credentials.valid = False
    await llm.generate("q")
    assert credentials.refreshes == 2
    assert llm._client.api_key == "fresh-token-2"


async def test_json_mode_sets_response_format(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    completions = StubCompletions(text='{"ok": true}')
    llm = _llm_with(monkeypatch, completions)

    assert await llm.generate_json("json please") == {"ok": True}
    assert completions.requests[0]["response_format"] == {"type": "json_object"}


async def test_response_format_rejection_falls_back(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Not every Vertex partner model implements JSON mode; the prompt and
    # loose parsing still get us there.
    completions = StubCompletions(reject_json=True, text='{"ok": 1}')
    llm = _llm_with(monkeypatch, completions)

    assert await llm.generate_json("json please") == {"ok": 1}
    assert "response_format" not in completions.requests[-1]


async def test_system_prompt_leads_the_messages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    completions = StubCompletions()
    llm = _llm_with(monkeypatch, completions)

    await llm.generate("hi", system="be terse", temperature=0.5, max_tokens=64)
    request = completions.requests[0]
    assert request["messages"][0] == {"role": "system", "content": "be terse"}
    assert request["messages"][1] == {"role": "user", "content": "hi"}
    # Unlike Anthropic, this surface still accepts sampling parameters.
    assert request["temperature"] == 0.5
    assert request["model"] == "xai/grok-4.1-fast-reasoning"


async def test_generate_retries_transient_errors(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    completions = StubCompletions(failures=1, text="recovered")
    llm = _llm_with(monkeypatch, completions)

    assert await llm.generate("q") == "recovered"
    assert len(completions.requests) == 2


async def test_stream_yields_deltas(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    completions = StubCompletions(text="streamed answer")
    llm = _llm_with(monkeypatch, completions)

    chunks = [chunk async for chunk in llm.stream("q")]
    assert "".join(chunks) == "streamed answer"
    assert len(chunks) > 1
    # The stream holds an open HTTP response; leaving it open leaks a
    # connection per call in a long-running server.
    assert completions.stream_obj.closed


def test_explicit_key_skips_vertex(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    llm = _llm_with(
        monkeypatch,
        StubCompletions(),
        _settings(openai_api_key="sk-test", openai_base_url="https://example.test/v1"),
    )
    assert llm._client.api_key == "sk-test"
    assert llm._vertex is None


def test_base_url_without_a_key_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(RuntimeError, match="SCI_RAG_OPENAI_API_KEY"):
        _llm_with(
            monkeypatch, StubCompletions(), _settings(openai_base_url="https://example.test/v1")
        )


def test_no_endpoint_at_all_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(RuntimeError, match="SCI_RAG_GCP_PROJECT"):
        _llm_with(monkeypatch, StubCompletions(), _settings(gcp_project=None))
