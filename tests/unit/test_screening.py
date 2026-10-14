from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.campaigns.discovery import CandidateWork
from sci_rag.campaigns.prisma import build_prisma_counts
from sci_rag.campaigns.screen import (
    ScreeningDecision,
    apply_human_review,
    screen_campaign,
)
from sci_rag.campaigns.state import CampaignState
from sci_rag.domain import load_domain
from sci_rag.llm import MockLLM


def _work(doi: str, title: str, abstract: str | None = "Relevant abstract.") -> CandidateWork:
    return CandidateWork(
        doi=doi,
        title=title,
        abstract=abstract,
        source="fixture",
    )


@pytest.mark.asyncio
async def test_screen_campaign_parses_batched_decisions_and_persists_reasons(
    tmp_path: Path,
) -> None:
    works = [
        _work("10.1000/included", "Included work"),
        _work("10.1000/excluded", "Excluded work"),
    ]
    llm = MockLLM(
        responses=[
            json.dumps(
                {
                    "decisions": [
                        {
                            "index": 1,
                            "decision": "include",
                            "confidence": 0.94,
                            "reason": "Matches the population and outcome.",
                        },
                        {
                            "index": 2,
                            "decision": "exclude",
                            "confidence": 0.91,
                            "reason": "Uses an ineligible study design.",
                        },
                    ]
                }
            )
        ]
    )
    state = CampaignState(tmp_path / "state.jsonl")

    report = await screen_campaign(
        works,
        criteria="Include field studies. Exclude reviews.",
        llm=llm,
        domain=load_domain(Path("domain")),
        state=state,
        confidence_threshold=0.8,
        batch_size=20,
        report_path=tmp_path / "screening-report.json",
    )

    assert [decision.decision for decision in report.decisions] == ["include", "exclude"]
    assert [decision.reason for decision in report.decisions] == [
        "Matches the population and outcome.",
        "Uses an ineligible study design.",
    ]
    assert report.prisma.included == 1
    assert report.prisma.excluded == 1
    assert report.prisma.awaiting_review == 0
    assert len(llm.calls) == 1
    assert "Relevant abstract." in llm.calls[0]["prompt"]
    assert {record.status for record in state.records} == {
        "screen_included",
        "screen_excluded",
    }
    saved = json.loads((tmp_path / "screening-report.json").read_text(encoding="utf-8"))
    assert saved["prisma"]["screened"] == 2


@pytest.mark.asyncio
async def test_low_confidence_and_missing_abstract_route_to_review(tmp_path: Path) -> None:
    works = [
        _work("10.1000/uncertain", "Uncertain work"),
        _work("10.1000/no-abstract", "No abstract", abstract=None),
    ]
    llm = MockLLM(
        responses=[
            json.dumps(
                {
                    "decisions": [
                        {
                            "index": 1,
                            "decision": "exclude",
                            "confidence": 0.55,
                            "reason": "Probably the wrong population.",
                        }
                    ]
                }
            )
        ]
    )

    report = await screen_campaign(
        works,
        criteria="Include studies of adults.",
        llm=llm,
        domain=load_domain(Path("domain")),
        state=CampaignState(tmp_path / "state.jsonl"),
        confidence_threshold=0.8,
    )

    assert [decision.decision for decision in report.review_queue] == ["review", "review"]
    assert report.review_queue[0].model_decision == "exclude"
    assert report.review_queue[1].reason == "Abstract unavailable; human review required."
    assert report.missing_abstracts == 1
    assert report.prisma.awaiting_review == 2
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_malformed_model_response_is_counted_and_never_excludes(tmp_path: Path) -> None:
    state = CampaignState(tmp_path / "state.jsonl")
    report = await screen_campaign(
        [_work("10.1000/malformed", "Malformed response work")],
        criteria="Include eligible studies.",
        llm=MockLLM(responses=["not json"]),
        domain=load_domain(Path("domain")),
        state=state,
    )

    assert report.malformed_responses == 1
    assert report.prisma.excluded == 0
    assert report.prisma.awaiting_review == 1
    assert report.decisions[0].failure is True
    assert state.records[-1].status == "screen_review"


@pytest.mark.asyncio
async def test_resume_preserves_failure_counts_and_threshold_change_rescreens(
    tmp_path: Path,
) -> None:
    work = _work("10.1000/resume", "Resume work")
    state = CampaignState(tmp_path / "state.jsonl")
    report_path = tmp_path / "screening-report.json"
    first_llm = MockLLM(responses=["not json"])
    first = await screen_campaign(
        [work],
        criteria="Include eligible studies.",
        llm=first_llm,
        domain=load_domain(Path("domain")),
        state=state,
        confidence_threshold=0.8,
        report_path=report_path,
    )
    resumed_llm = MockLLM(responses=["this response must remain unused"])

    resumed = await screen_campaign(
        [work],
        criteria="Include eligible studies.",
        llm=resumed_llm,
        domain=load_domain(Path("domain")),
        state=state,
        confidence_threshold=0.8,
        report_path=report_path,
    )

    assert first.malformed_responses == resumed.malformed_responses == 1
    assert resumed_llm.calls == []

    changed_threshold_llm = MockLLM(
        responses=[
            '{"decisions":[{"index":1,"decision":"include",'
            '"confidence":0.7,"reason":"Eligible under the reviewed floor."}]}'
        ]
    )
    changed = await screen_campaign(
        [work],
        criteria="Include eligible studies.",
        llm=changed_threshold_llm,
        domain=load_domain(Path("domain")),
        state=state,
        confidence_threshold=0.6,
        report_path=report_path,
    )

    assert changed.decisions[0].decision == "include"
    assert len(changed_threshold_llm.calls) == 1
    assert changed.malformed_responses == 0


def test_prisma_counts_reconcile_and_break_down_exclusion_reasons() -> None:
    decisions = [
        ScreeningDecision(
            doi="10.1000/included",
            title="Included",
            decision="include",
            confidence=0.95,
            reason="Eligible.",
            source="model",
        ),
        ScreeningDecision(
            doi="10.1000/design",
            title="Wrong design",
            decision="exclude",
            confidence=0.94,
            reason="Ineligible study design",
            source="model",
        ),
        ScreeningDecision(
            doi="10.1000/design-2",
            title="Wrong design again",
            decision="exclude",
            confidence=None,
            reason="Ineligible study design",
            source="human",
        ),
        ScreeningDecision(
            doi="10.1000/review",
            title="Needs review",
            decision="review",
            confidence=0.5,
            reason="Uncertain.",
            source="model",
        ),
    ]

    counts = build_prisma_counts(decisions, discovered_total=4, duplicates_removed=2)

    assert counts.identified == 6
    assert counts.duplicates_removed == 2
    assert counts.screened == 4
    assert counts.included == 1
    assert counts.excluded == 2
    assert counts.awaiting_review == 1
    assert counts.excluded_by_reason == {"Ineligible study design": 2}
    assert counts.reconciles(discovered_total=4)


@pytest.mark.asyncio
async def test_human_review_replaces_pending_decision_without_erasing_history(
    tmp_path: Path,
) -> None:
    state = CampaignState(tmp_path / "state.jsonl")
    report = await screen_campaign(
        [_work("10.1000/review", "Needs review")],
        criteria="Include eligible studies.",
        llm=MockLLM(
            responses=[
                '{"decisions":[{"index":1,"decision":"include",'
                '"confidence":0.4,"reason":"Uncertain fit."}]}'
            ]
        ),
        domain=load_domain(Path("domain")),
        state=state,
        confidence_threshold=0.8,
    )

    reviewed = apply_human_review(
        state,
        doi="10.1000/review",
        criteria_sha256=report.criteria_sha256,
        confidence_threshold=report.confidence_threshold,
        decision="exclude",
        reason="Full text confirms an ineligible population.",
    )

    assert reviewed.decision == "exclude"
    assert reviewed.source == "human"
    assert [record.status for record in state.records] == [
        "screen_review",
        "screen_excluded",
    ]
