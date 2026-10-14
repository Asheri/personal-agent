from __future__ import annotations

import os

import pytest

from sci_rag.campaigns.build import build_campaign
from sci_rag.campaigns.discovery import CandidateWork
from sci_rag.campaigns.http import PoliteHttpClient
from sci_rag.campaigns.state import CampaignState

pytestmark = [
    pytest.mark.cloud,
    pytest.mark.skipif(
        os.environ.get("SCI_RAG_RUN_CLOUD_TESTS") != "1",
        reason="set SCI_RAG_RUN_CLOUD_TESTS=1 for live API checks",
    ),
]


async def test_live_unpaywall_dry_run_resolves_known_open_work(tmp_path) -> None:  # type: ignore[no-untyped-def]
    mailto = os.environ.get("SCI_RAG_CAMPAIGN_MAILTO")
    if not mailto:
        pytest.fail("SCI_RAG_CAMPAIGN_MAILTO is required for the live build check")
    campaign_dir = tmp_path / "campaign"
    state = CampaignState(campaign_dir / "state.jsonl")

    async with PoliteHttpClient(mailto=mailto) as client:
        report = await build_campaign(
            [
                CandidateWork(
                    doi="10.7717/peerj.4375",
                    title="The state of OA",
                    source="crossref",
                )
            ],
            campaign_dir=campaign_dir,
            state=state,
            client=client,
            dry_run=True,
        )

    assert report.failed == 0
    assert report.resolved == 1
    assert report.license_counts["open_commercial"] == 1
    assert not (campaign_dir / "pdfs").exists()
    assert not (campaign_dir / "corpus.jsonl").exists()
