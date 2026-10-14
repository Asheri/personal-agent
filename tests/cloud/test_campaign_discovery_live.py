from __future__ import annotations

import os

import pytest

from sci_rag.campaigns.discovery import discover_by_topic
from sci_rag.campaigns.http import PoliteHttpClient

pytestmark = [
    pytest.mark.cloud,
    pytest.mark.skipif(
        os.environ.get("SCI_RAG_RUN_CLOUD_TESTS") != "1",
        reason="set SCI_RAG_RUN_CLOUD_TESTS=1 for live API checks",
    ),
]


async def test_live_openalex_discovery_is_bounded_and_deduplicated() -> None:
    mailto = os.environ.get("SCI_RAG_CAMPAIGN_MAILTO")
    if not mailto:
        pytest.fail("SCI_RAG_CAMPAIGN_MAILTO is required for the live discovery check")

    async with PoliteHttpClient(mailto=mailto) as client:
        report = await discover_by_topic(
            client,
            "rice straw valorization",
            max_results=10,
            per_page=10,
            api_key=os.environ.get("OPENALEX_API_KEY") or None,
        )

    assert 1 <= len(report.works) <= 10
    assert len({work.doi for work in report.works}) == len(report.works)
