"""Server test fixtures: a real service over the demo corpus, mock LLM,
and app instances with auth off and on."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from sci_rag.answer import AnswerEngine
from sci_rag.config import Settings
from sci_rag.db import KgEntity, KgRelationship, get_session_factory, session_scope
from sci_rag.domain import load_domain
from sci_rag.ingest import ingest_entries, load_manifest
from sci_rag.llm import LLMClient
from sci_rag.retrieve import Retriever
from sci_rag.server import RagService, create_app

REPO_ROOT = Path(__file__).parents[2]

SERVER_KEYS = {
    "full-key": {"scopes": ["retrieval:query", "retrieval:answer", "corpus:read", "byo_llm"]},
    "query-key": {"scopes": ["retrieval:query"]},
    "answer-key": {"scopes": ["retrieval:query", "retrieval:answer"]},
    "limited-key": {"scopes": ["retrieval:query"], "rate_limit_per_minute": 2},
    # F-017: two keys sharing a six character prefix. They used to land in one
    # rate limit bucket, so either one could throttle the other.
    "shared-prefix-first": {"scopes": ["retrieval:query"], "rate_limit_per_minute": 1},
    "shared-prefix-second": {"scopes": ["retrieval:query"], "rate_limit_per_minute": 1},
}


class ServerMockLLM(LLMClient):
    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        if "Passages JSON:" in prompt:
            passages = json.loads(prompt.split("Passages JSON:\n", 1)[1])
            return json.dumps(
                {
                    "snippets": [
                        {
                            "index": index,
                            "relevance_score": 0.9,
                            "summary": "Rice straw availability was measured at 302,000 dry tons.",
                        }
                        for index in (passage["index"] for passage in passages)
                    ]
                }
            )
        if '"entities"' in prompt:
            return '{"entities": []}'
        return "A hypothetical passage about residue availability."

    async def _stream_impl(self) -> AsyncIterator[str]:
        yield "Rice straw availability is documented at 302,000 dry tons [1]."

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self._stream_impl()


ServerMockLLM.model = "mock-llm"  # type: ignore[attr-defined]


@pytest_asyncio.fixture()
async def service(database, clean_tables, local_embedder):  # type: ignore[no-untyped-def]
    entries = load_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")
    report = await ingest_entries(entries, embedder=local_embedder)
    assert report.failed == 0
    # A tiny hand-planted graph so entity tools have something to serve.
    async with session_scope() as db:
        straw = KgEntity(
            name="rice straw",
            entity_type="Feedstock",
            description="residue",
            aliases=["paddy straw"],
        )
        digestion = KgEntity(name="anaerobic digestion", entity_type="ConversionProcess")
        db.add_all([straw, digestion])
        await db.flush()
        db.add(
            KgRelationship(
                source_entity_id=straw.id,
                target_entity_id=digestion.id,
                relation_type="CONVERTED_BY",
                evidence="rice straw can be digested",
            )
        )
    llm = ServerMockLLM()
    retriever = Retriever(
        domain=load_domain(REPO_ROOT / "domain"),
        embedder=local_embedder,
        llm=llm,
        session_factory=get_session_factory(),
    )
    return RagService(
        settings=Settings(),
        retriever=retriever,
        answer_engine=AnswerEngine(retriever=retriever, llm=llm),
    )


@pytest.fixture()
def open_app(service):  # type: ignore[no-untyped-def]
    return create_app(settings=Settings(api_keys=None), service=service)


@pytest.fixture()
def secured_app(service):  # type: ignore[no-untyped-def]
    return create_app(settings=Settings(api_keys=json.dumps(SERVER_KEYS)), service=service)


@pytest_asyncio.fixture()
async def client(open_app):  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=open_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class _FrozenMinute:
    """A clock that only moves when a test says so."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def frozen_minute(secured_app):  # type: ignore[no-untyped-def]
    """Pin the rate limiter's wall clock for the tests that spend a budget.

    The limiter's window starts at the top of a minute, not at the caller's
    first request, so three requests that straddle a boundary reset the
    counter. Two contract tests were failing on that, on diffs with no server
    code in them. Pinning the clock makes them assert the limit; the boundary
    itself is asserted separately by advancing this.
    """
    from sci_rag.server.auth import _MinuteWindowLimiter

    clock = _FrozenMinute()
    secured_app.state.auth_backend._limiter = _MinuteWindowLimiter(clock)
    return clock


@pytest_asyncio.fixture()
async def secured_client(secured_app):  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=secured_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def demo_compression_enabled() -> bool:
    """Whatever the shipped domain profile is tuned to, read at call time.

    Compression is an evidence-gated tuning decision that flips with the
    benchmark (see docs/benchmarks.md), so a server contract test must pin
    that the value is reported, not which value it currently is.
    """
    from pathlib import Path

    from sci_rag.config import get_settings
    from sci_rag.domain import load_domain

    return load_domain(Path(get_settings().domain_dir)).config.compression.enabled
