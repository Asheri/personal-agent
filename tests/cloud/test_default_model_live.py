"""Does the DeepSeek model we ship as the default actually answer?

The shipped default is ``deepseek:deepseek-flash``. This live check requires
``SCI_RAG_DEEPSEEK_API_KEY`` and proves that the configured model can answer
the same JSON and generation workloads used by the kit.

Run it with::

    SCI_RAG_RUN_CLOUD_TESTS=1 \
    SCI_RAG_DEEPSEEK_API_KEY=<key> \
      uv run pytest tests/cloud/test_default_model_live.py

The Google alternate remains in ``test_llm_providers_live.py`` and selects its
own credential instead of borrowing the default provider's.
"""

from __future__ import annotations

import json
import os

import pytest

from sci_rag.config import DEFAULT_LLM_MODEL, Settings
from sci_rag.llm import get_llm

pytestmark = [
    pytest.mark.cloud,
    pytest.mark.skipif(
        os.environ.get("SCI_RAG_RUN_CLOUD_TESTS") != "1",
        reason="set SCI_RAG_RUN_CLOUD_TESTS=1 for live API checks",
    ),
]


def _settings() -> Settings:
    settings = Settings(
        llm_provider=Settings.model_fields["llm_provider"].default,
        llm_model=DEFAULT_LLM_MODEL,
    )
    provider = settings.model_spec_for("answer").provider
    if provider == "deepseek" and not settings.deepseek_api_key:
        pytest.skip("no DeepSeek credential configured")
    if provider == "google" and settings.credentials_mode() == "none":
        pytest.skip("no Google credentials configured")
    return settings


async def test_the_shipped_default_model_answers() -> None:
    """At the budget the kit actually uses, not a token-starved one.

    Generation models can spend output tokens on reasoning before they emit
    visible text, so a tight budget can return an empty string rather than an
    error. Every call site in the kit passes 512 or more.
    """
    reply = await get_llm(_settings()).generate("Reply with exactly: ready", max_tokens=512)

    assert reply.strip()


async def test_the_shipped_default_model_returns_strict_json() -> None:
    """Structured output, not just prose.

    Graph extraction, HyDE, community summaries, and the judge all ask this
    model for JSON. A default that answers in prose but cannot hold a schema
    would pass the test above and still take out most of the pipeline.
    """
    reply = await get_llm(_settings()).generate(
        'Return only this JSON object and nothing else: {"status": "ok"}',
        json_mode=True,
        max_tokens=512,
    )

    assert json.loads(reply)["status"] == "ok"
