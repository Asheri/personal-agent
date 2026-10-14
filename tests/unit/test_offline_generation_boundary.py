"""What an offline project is told when it asks for something a model does.

Offline is a supported mode: the deterministic embedder ingests, retrieves,
and scores without a single model call. The boundary is generation. Crossing
it has to be quick and has to name the thing that is missing, because the two
ways it used to go wrong both cost a reader real time. The deep profile ran
two model-only layers into the credential failure, one stage timeout each,
and then the refusal repeated the embedder's advice: set
``SCI_RAG_EMBEDDING_PROVIDER=local-hash``, which an offline project already
has and which cannot generate an answer whatever its value.
"""

from __future__ import annotations

from typing import Any

import pytest

from sci_rag.config import Settings

_CREDENTIAL_VARS = (
    "SCI_RAG_GOOGLE_API_KEY",
    "SCI_RAG_GCP_PROJECT",
    "SCI_RAG_ANTHROPIC_API_KEY",
    "SCI_RAG_OPENAI_API_KEY",
    "SCI_RAG_OPENAI_BASE_URL",
    "SCI_RAG_DEEPSEEK_API_KEY",
    "SCI_RAG_DEEPSEEK_BASE_URL",
)
_GENERATION_VARS = (
    "SCI_RAG_LLM_PROVIDER",
    "SCI_RAG_LLM_MODEL",
    "SCI_RAG_EXTRACTION_MODEL",
    "SCI_RAG_JUDGE_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _CREDENTIAL_VARS + _GENERATION_VARS:
        monkeypatch.delenv(name, raising=False)


def _offline(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"embedding_provider": "local-hash", **overrides}
    return Settings(_env_file=None, **values)


# --- the message ------------------------------------------------------------


def test_a_missing_generation_credential_names_generation() -> None:
    """The refusal has to describe the capability the reader asked for.

    `GoogleLLM` builds its client through the embedder's factory, so an
    offline `sci-rag answer` used to end on the embedder's advice.
    """
    from sci_rag.embed.google import make_genai_client

    with pytest.raises(RuntimeError) as caught:
        make_genai_client(_offline(), purpose="generation")

    message = str(caught.value)
    assert "generate" in message
    assert "SCI_RAG_GOOGLE_API_KEY" in message
    assert "SCI_RAG_GCP_PROJECT" in message
    # The setting an offline project already has, and the one it cannot fix
    # this with. Naming it as the repair is what sent readers in a circle.
    assert "SCI_RAG_EMBEDDING_PROVIDER=local-hash" not in message
    # Say what still works, so "no credential" does not read as "nothing works".
    assert "retrieval" in message


def test_a_missing_embedding_credential_still_names_the_offline_embedder() -> None:
    """The embedder's own advice is correct and stays."""
    from sci_rag.embed.google import make_genai_client

    with pytest.raises(RuntimeError) as caught:
        make_genai_client(_offline(embedding_provider="google"))

    message = str(caught.value)
    assert "SCI_RAG_EMBEDDING_PROVIDER=local-hash" in message


# --- the stages -------------------------------------------------------------


def test_an_offline_project_cannot_reach_a_generation_model() -> None:
    """The predicate the retriever branches on, without a database.

    It asks whether a client is reachable, not whether the settings look
    offline: an injected client means generation is available whatever the
    environment says, which is how the test suite and the evaluation harness
    run graph and HyDE with a `MockLLM` under exactly these settings.
    """
    from sci_rag.llm import MockLLM
    from sci_rag.retrieve import Retriever

    offline = Retriever(
        settings=_offline(),
        domain=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
        session_factory=object(),  # type: ignore[arg-type]
    )
    assert offline.can_generate() is False

    injected = Retriever(
        settings=_offline(),
        domain=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
        llm=MockLLM(),
        session_factory=object(),  # type: ignore[arg-type]
    )
    assert injected.can_generate() is True

    credentialed = Retriever(
        settings=_offline(embedding_provider="google", google_api_key="k"),
        domain=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
        session_factory=object(),  # type: ignore[arg-type]
    )
    assert credentialed.can_generate() is True


# --- a timed-out retrieval is not an empty knowledge base -------------------


def _traced(statuses: dict[str, str]):  # type: ignore[no-untyped-def]
    from sci_rag.retrieve.types import RetrievalResult, StageTrace

    return RetrievalResult(
        items=[],
        traces=[StageTrace(stage=stage, status=status) for stage, status in statuses.items()],
        profile="deep",
    )


async def test_a_retrieval_that_timed_out_says_so_instead_of_claiming_no_material() -> None:
    """The two refusals mean opposite things and used to read identically.

    An empty corpus and a corpus nobody could reach both produced "The
    knowledge base has no material matching this question". On a live Vertex
    project the second was the truth, and the reader was told the first.
    """
    from sci_rag.answer import AnswerEngine

    class _Retriever:
        domain = None

        async def retrieve(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            return _traced({"vector": "timeout", "keyword": "empty", "hyde": "timeout"})

    engine = AnswerEngine(settings=_offline(), retriever=_Retriever())  # type: ignore[arg-type]
    events = [event async for event in engine.answer_stream("anything")]

    text = "".join(e.data["text"] for e in events if e.type == "delta")
    assert "timed out" in text
    assert "SCI_RAG_PROVIDER_CALL_TIMEOUT_S" in text
    assert "no material" not in text

    done = next(e for e in events if e.type == "done")
    assert done.data["finish_reason"] == "retrieval_timeout"


async def test_an_actually_empty_corpus_still_gets_the_no_material_refusal() -> None:
    """The honest empty answer is the one this must not swallow."""
    from sci_rag.answer import AnswerEngine

    class _Retriever:
        domain = None

        async def retrieve(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            return _traced({"vector": "empty", "keyword": "empty"})

    engine = AnswerEngine(settings=_offline(), retriever=_Retriever())  # type: ignore[arg-type]
    events = [event async for event in engine.answer_stream("anything")]

    text = "".join(e.data["text"] for e in events if e.type == "delta")
    assert "no material matching this question" in text
    assert "timed out" not in text

    done = next(e for e in events if e.type == "done")
    assert done.data["finish_reason"] == "no_sources"
