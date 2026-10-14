"""Offline tests for the Google providers, via a stub genai client.

Network code cannot run in CI, but its logic can: batching, Matryoshka
re-normalization, dimension assertions, retry/backoff, and the Gemini 2.5
thinking fallback are all exercised against a scripted stand-in.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

import sci_rag.embed.google as embed_google
import sci_rag.llm.client as llm_client
import sci_rag.llm.google as llm_google
from sci_rag.config import Settings
from sci_rag.embed import EmbeddingDimensionError
from sci_rag.embed.google import GoogleEmbedder, make_genai_client


def _settings(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "google_api_key": "test-key",
        "embedding_model": "gemini-embedding-001",
        "embedding_dim": 4,
        "llm_model": "gemini-2.5-flash",
    }
    values.update(overrides)
    return Settings(**values)


class StubEmbeddingClient:
    """Returns scripted vectors; records every call; can fail first."""

    def __init__(self, vectors_per_call, failures=0, failure_text="429 slow down"):  # type: ignore[no-untyped-def]
        self.vectors_per_call = list(vectors_per_call)
        self.failures = failures
        self.failure_text = failure_text
        self.calls: list[list[str]] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(embed_content=self._embed))

    async def _embed(self, *, model, contents, config):  # type: ignore[no-untyped-def]
        self.calls.append(list(contents))
        if self.failures:
            self.failures -= 1
            raise RuntimeError(self.failure_text)
        vectors = self.vectors_per_call.pop(0)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=vector) for vector in vectors])


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):  # type: ignore[no-untyped-def]
    async def no_sleep(_seconds):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(embed_google.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(llm_client.asyncio, "sleep", no_sleep)


async def test_embedder_batches_and_renormalizes() -> None:
    texts = [f"t{i}" for i in range(25)]  # crosses the 20-per-call batch line
    first = [[2.0, 0.0, 0.0, 0.0]] * 20
    second = [[0.0, 3.0, 0.0, 0.0]] * 5
    client = StubEmbeddingClient([first, second])
    embedder = GoogleEmbedder(_settings(), client=client)  # type: ignore[arg-type]

    vectors = await embedder.embed(texts, task="document")
    assert len(client.calls) == 2
    assert [len(call) for call in client.calls] == [20, 5]
    # Matryoshka-truncated vectors are not unit norm; the embedder must fix that.
    assert all(math.isclose(sum(v * v for v in vec), 1.0, rel_tol=1e-9) for vec in vectors)
    assert vectors[0][0] == 1.0 and vectors[24][1] == 1.0


async def test_embedder_rejects_wrong_dimension() -> None:
    client = StubEmbeddingClient([[[1.0, 0.0]]])  # 2 dims, settings say 4
    embedder = GoogleEmbedder(_settings(), client=client)  # type: ignore[arg-type]
    with pytest.raises(EmbeddingDimensionError, match="vector\\(4\\)"):
        await embedder.embed(["x"], task="query")


async def test_embedder_retries_transient_errors_then_succeeds() -> None:
    client = StubEmbeddingClient([[[0.0, 0.0, 1.0, 0.0]]], failures=2)
    embedder = GoogleEmbedder(_settings(), client=client)  # type: ignore[arg-type]
    [vector] = await embedder.embed(["x"], task="query")
    assert vector[2] == 1.0
    assert len(client.calls) == 3  # two failures plus the success


async def test_embedder_gives_up_on_non_retryable_errors() -> None:
    client = StubEmbeddingClient([], failures=5, failure_text="400 invalid argument")
    embedder = GoogleEmbedder(_settings(), client=client)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="400"):
        await embedder.embed(["x"], task="query")
    assert len(client.calls) == 1  # no retry on a caller error


def test_make_genai_client_requires_credentials() -> None:
    with pytest.raises(RuntimeError, match="local-hash"):
        make_genai_client(Settings(google_api_key=None, gcp_project=None))


class StubGenerateClient:
    """Scripted generate_content: can reject the thinking knob or rate-limit."""

    def __init__(self, *, reject_thinking=False, failures=0, text="hello", reject_message=None):  # type: ignore[no-untyped-def]
        self.reject_thinking = reject_thinking
        self.reject_message = reject_message or "thinking is not supported for this model"
        self.failures = failures
        self.text = text
        self.configs: list[object] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model, contents, config):  # type: ignore[no-untyped-def]
        # Snapshot the knob's value: the fallback path mutates the same
        # config object, so storing the reference would alias the history.
        self.configs.append(config.thinking_config)
        if self.reject_thinking and config.thinking_config is not None:
            raise RuntimeError(self.reject_message)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("503 UNAVAILABLE")
        return SimpleNamespace(text=self.text)


def _llm_with(monkeypatch, client):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(embed_google, "make_genai_client", lambda *a, **k: client)
    return llm_google.GoogleLLM(_settings())


async def test_json_mode_disables_thinking(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = StubGenerateClient(text='{"ok": true}')
    llm = _llm_with(monkeypatch, client)
    payload = await llm.generate_json("give me json")
    assert payload == {"ok": True}
    assert client.configs[0] is not None
    assert client.configs[0].thinking_budget == 0

    await llm.generate("plain prose")
    assert client.configs[1] is None


async def test_thinking_knob_rejection_falls_back(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = StubGenerateClient(reject_thinking=True, text='{"ok": 1}')
    llm = _llm_with(monkeypatch, client)
    payload = await llm.generate_json("json please")
    assert payload == {"ok": 1}
    # First attempt carried the knob, the fallback dropped it.
    assert client.configs[0] is not None
    assert client.configs[-1] is None


async def test_generate_retries_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = StubGenerateClient(failures=1, text="recovered")
    llm = _llm_with(monkeypatch, client)
    assert await llm.generate("q") == "recovered"
    assert len(client.configs) == 2


# Captured from Vertex and AI Studio on 2026-08-31, calling gemini-3.6-flash
# with ThinkingConfig(thinking_budget=0). Quoted rather than paraphrased,
# because the previous fallback matched on the word "thinking" and this
# message does not contain it.
GEMINI_3_REJECTION = (
    "400 INVALID_ARGUMENT. {'error': {'code': 400, "
    "'message': 'Request contains an invalid argument.', 'status': 'INVALID_ARGUMENT'}}"
)


async def test_the_fallback_fires_on_the_rejection_gemini_3_actually_sends(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The fallback existed and did not fire, which is worse than not having it.

    `gemini-3.x` rejects `thinking_budget=0` with a generic invalid-argument
    error that never names the knob. Matching on the word "thinking" meant
    every JSON-mode call against those models failed outright: graph
    extraction, HyDE, community summaries, and the judge together.

    The message below is captured from the provider, not written to match the
    code. That distinction is the whole point of this test.
    """
    client = StubGenerateClient(
        reject_thinking=True, text='{"ok": 1}', reject_message=GEMINI_3_REJECTION
    )
    llm = _llm_with(monkeypatch, client)

    payload = await llm.generate_json("json please")

    assert payload == {"ok": 1}
    assert client.configs[0].thinking_budget == 0, "first attempt asks for no thinking"
    assert client.configs[1] != client.configs[0], "the retry must not resend the rejected knob"


async def test_a_failure_unrelated_to_the_knob_is_not_retried_as_one(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Broadening the match must not swallow real failures.

    A rate limit is not a rejected knob, and retrying it without the knob
    would hide the cause and spend another call.
    """
    client = StubGenerateClient(
        reject_thinking=True, text="{}", reject_message="429 RESOURCE_EXHAUSTED"
    )
    llm = _llm_with(monkeypatch, client)

    with pytest.raises(Exception, match="RESOURCE_EXHAUSTED"):
        await llm.generate_json("json please")


async def test_a_model_that_rejects_the_budget_gets_a_thinking_level(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Step down, do not give up.

    #248 made the fallback fire for Gemini 3.x, but it dropped thinking
    control entirely, so reasoning tokens came out of `max_output_tokens` and
    structured replies truncated mid-value at the 512-token budgets retrieval
    and the judge use. `thinking_level` is the knob those models do accept,
    so the fallback steps to it rather than to nothing.
    """
    client = StubGenerateClient(
        reject_thinking=True, text='{"ok": 1}', reject_message=GEMINI_3_REJECTION
    )
    llm = _llm_with(monkeypatch, client)

    payload = await llm.generate_json("json please")

    assert payload == {"ok": 1}
    assert client.configs[0].thinking_budget == 0, "first attempt asks for no thinking at all"
    second = client.configs[1]
    assert second is not None, "thinking control was dropped rather than stepped down"
    assert second.thinking_level == "MINIMAL", "ask for the least reasoning first"


class RejectsEveryThinkingKnob(StubGenerateClient):
    """A model that accepts neither spelling, which must still complete."""

    async def _generate(self, *, model, contents, config):  # type: ignore[no-untyped-def]
        self.configs.append(config.thinking_config)
        if config.thinking_config is not None:
            raise RuntimeError(GEMINI_3_REJECTION)
        return SimpleNamespace(text=self.text)


async def test_a_model_that_rejects_both_knobs_still_completes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = RejectsEveryThinkingKnob(text='{"ok": 2}')
    llm = _llm_with(monkeypatch, client)

    payload = await llm.generate_json("json please")

    assert payload == {"ok": 2}
    assert client.configs[-1] is None, "the last attempt drops thinking control entirely"


class EmptyCompletionClient(StubGenerateClient):
    """A response that carries no text, with a reason attached."""

    def __init__(self, finish_reason=None, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self.finish_reason = finish_reason

    async def _generate(self, *, model, contents, config):  # type: ignore[no-untyped-def]
        self.configs.append(config.thinking_config)
        candidate = SimpleNamespace(finish_reason=self.finish_reason)
        return SimpleNamespace(text=None, candidates=[candidate])


async def test_an_empty_completion_raises_rather_than_reading_as_an_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`response.text or ""` made a failure indistinguishable from a refusal.

    A grounded-answer system returning nothing looks exactly like "the corpus
    does not cover this", which the kit deliberately supports. A safety block,
    a length cutoff, and a real answer of "" all rendered the same. AGENTS.md
    is direct about this: new failure modes must be visible.

    Raising puts it on the path that already exists, where the answer route
    turns it into a `generation_failed` event.
    """
    llm = _llm_with(monkeypatch, EmptyCompletionClient(finish_reason="SAFETY"))

    with pytest.raises(RuntimeError, match="SAFETY"):
        await llm.generate("anything")


async def test_an_empty_completion_says_so_even_without_a_reason(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Some providers give no finish reason. Silence is still not an answer."""
    llm = _llm_with(monkeypatch, EmptyCompletionClient(finish_reason=None))

    with pytest.raises(RuntimeError, match=r"(?i)empty"):
        await llm.generate("anything")
