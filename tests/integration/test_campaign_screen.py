from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from sci_rag.campaigns.build import load_discovered_candidates
from sci_rag.campaigns.discovery import CandidateWork
from sci_rag.campaigns.screen import screen_campaign
from sci_rag.campaigns.state import CampaignState
from sci_rag.domain import load_domain
from sci_rag.llm import MockLLM

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_fixture_campaign_writes_reconciling_report_and_review_queue(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaigns" / "fixture-review"
    state = CampaignState(campaign_dir / "state.jsonl")
    works = [
        CandidateWork(
            doi="10.1000/include",
            title="Eligible field study",
            abstract="A field study measuring the requested outcome.",
            source="fixture",
        ),
        CandidateWork(
            doi="10.1000/review",
            title="Unclear study",
            abstract="The population is not stated clearly.",
            source="fixture",
        ),
    ]
    for work in works:
        state.append(doi=work.doi, status="discovered", payload=asdict(work))

    report = await screen_campaign(
        load_discovered_candidates(state),
        criteria="Include field studies that measure the requested outcome.",
        llm=MockLLM(
            responses=[
                json.dumps(
                    {
                        "decisions": [
                            {
                                "index": 1,
                                "decision": "include",
                                "confidence": 0.96,
                                "reason": "Directly measures the requested outcome.",
                            },
                            {
                                "index": 2,
                                "decision": "exclude",
                                "confidence": 0.52,
                                "reason": "Population is unclear.",
                            },
                        ]
                    }
                )
            ]
        ),
        domain=load_domain(Path("domain")),
        state=state,
        confidence_threshold=0.8,
        report_path=campaign_dir / "screening-report.json",
    )

    assert report.prisma.screened == 2
    assert report.prisma.included == 1
    assert report.prisma.excluded == 0
    assert report.prisma.awaiting_review == 1
    assert report.prisma.reconciles(discovered_total=2)
    assert [decision.doi for decision in report.review_queue] == ["10.1000/review"]
    payload = json.loads((campaign_dir / "screening-report.json").read_text(encoding="utf-8"))
    assert payload["prisma"]["included"] == 1
    assert payload["prisma"]["awaiting_review"] == 1
