"""Live smoke checks for each generation provider.

Run them with::

    SCI_RAG_RUN_CLOUD_TESTS=1 \
    SCI_RAG_GCP_PROJECT=<project> \
    SCI_RAG_GCP_LOCATION=global \
      uv run pytest tests/cloud/test_llm_providers_live.py

The project must be exported, not just set in ``.env``: ``tests/conftest.py``
blanks ``SCI_RAG_GCP_PROJECT`` so a developer's real configuration cannot leak
into the offline suite, and only an explicit export survives that. ``global``
is required because Claude and Grok are not served from ``us-central1``.

Each check skips when its own credentials are absent, so a Google-only setup
still runs the Google case.

These verify the things a stub cannot: that the model ids are real, that the
credentials resolve, and -- for Claude -- that dropping ``temperature`` and
sending ``output_config`` are actually accepted by the API rather than merely
matching our understanding of it.
"""

from __future__ import annotations

import os

import pytest

from sci_rag.config import Settings
from sci_rag.llm import get_llm

pytestmark = [
    pytest.mark.cloud,
    pytest.mark.skipif(
        os.environ.get("SCI_RAG_RUN_CLOUD_TESTS") != "1",
        reason="set SCI_RAG_RUN_CLOUD_TESTS=1 for live API checks",
    ),
]


def _settings(spec: str) -> Settings:
    settings = Settings(llm_model=spec)
    if settings.model_spec_for("answer").provider == "google":
        if settings.credentials_mode() == "none":
            pytest.skip("no Google credentials configured")
    elif not settings.gcp_project and not (settings.anthropic_api_key or settings.openai_api_key):
        pytest.skip("no credentials for this provider")
    return settings


@pytest.mark.parametrize(
    "spec",
    [
        "gemini-2.5-flash",
        "anthropic:claude-haiku-4-5",
        "openai-compatible:xai/grok-4.1-fast-non-reasoning",
    ],
)
async def test_live_generate_and_json_round_trip(spec: str) -> None:
    settings = _settings(spec)
    llm = get_llm(settings)

    # Budget generously: reasoning models spend output tokens on thought
    # before emitting any text, so a tight cap reads as an empty response.
    reply = await llm.generate("Reply with the single word: ready", max_tokens=2048)
    assert reply.strip(), f"{llm.describe()} returned no text"

    # generate_json is the high-volume path: extraction, routing, and judging
    # all parse the result, so a provider that ignores the JSON hint is a
    # problem worth catching here rather than mid-corpus.
    payload = await llm.generate_json(
        'Return only this JSON object and nothing else: {"ok": true}', max_tokens=512
    )
    assert payload == {"ok": True}


@pytest.mark.parametrize("spec", ["gemini-2.5-flash", "anthropic:claude-haiku-4-5"])
async def test_live_streaming_yields_text(spec: str) -> None:
    llm = get_llm(_settings(spec))
    chunks = [chunk async for chunk in llm.stream("Count to three.", max_tokens=2048)]
    assert "".join(chunks).strip()
