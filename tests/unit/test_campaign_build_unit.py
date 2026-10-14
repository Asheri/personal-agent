from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from sci_rag.campaigns.build import build_campaign
from sci_rag.campaigns.discovery import CandidateWork
from sci_rag.campaigns.http import PoliteHttpClient
from sci_rag.campaigns.state import CampaignState
from sci_rag.ingest import load_manifest

FIXTURES = Path(__file__).parents[1] / "fixtures" / "campaigns"


class StubClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    async def get_json(self, _url: str, *, params=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.payloads.pop(0)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _work(doi: str, title: str) -> CandidateWork:
    return CandidateWork(doi=doi, title=title, source="openalex")


@pytest.mark.asyncio
async def test_campaign_build_dry_run_resolves_and_writes_only_state(tmp_path: Path) -> None:
    works = [
        _work("10.7717/peerj.4375", "The state of OA"),
        _work("10.1038/s41586-020-2649-2", "Array programming with NumPy"),
    ]
    client = StubClient(
        [_fixture("unpaywall_cc_by.json"), _fixture("unpaywall_green_no_license.json")]
    )
    campaign_dir = tmp_path / "campaign"
    state = CampaignState(campaign_dir / "state.jsonl")

    report = await build_campaign(
        works,
        campaign_dir=campaign_dir,
        state=state,
        client=client,
        dry_run=True,
    )

    assert report.candidates == 2
    assert report.resolved == 2
    assert report.direct_pdfs == 2
    assert report.license_counts == {"open_commercial": 1, "unknown": 1}
    assert report.downloaded == 0
    assert report.manifest_path is None
    assert not (campaign_dir / "pdfs").exists()
    assert not (campaign_dir / "corpus.jsonl").exists()
    assert {record.status for record in state.records} == {"resolved"}

    cached = await build_campaign(
        works,
        campaign_dir=campaign_dir,
        state=state,
        client=StubClient([]),
        dry_run=True,
    )
    assert cached.resolved == 2


@pytest.mark.asyncio
async def test_campaign_build_dry_run_counts_records_without_direct_pdf(tmp_path: Path) -> None:
    state = CampaignState(tmp_path / "campaign" / "state.jsonl")

    report = await build_campaign(
        [_work("10.1000/closed", "Closed article")],
        campaign_dir=tmp_path / "campaign",
        state=state,
        client=StubClient([_fixture("unpaywall_closed.json")]),
        dry_run=True,
    )

    assert report.resolved == 1
    assert report.direct_pdfs == 0
    assert report.unavailable == 1


@pytest.mark.asyncio
async def test_campaign_build_downloads_pdf_and_writes_ingestible_manifest(tmp_path: Path) -> None:
    unpaywall = _fixture("unpaywall_cc_by.json")
    pdf_bytes = b"%PDF-1.7\ncampaign fixture\n%%EOF"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.unpaywall.org":
            return httpx.Response(200, json=unpaywall)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=pdf_bytes,
        )

    campaign_dir = tmp_path / "campaign"
    state = CampaignState(campaign_dir / "state.jsonl")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org",
            client=transport,
            requests_per_second=None,
        )
        report = await build_campaign(
            [_work("10.7717/peerj.4375", "The state of OA")],
            campaign_dir=campaign_dir,
            state=state,
            client=client,
            dry_run=False,
        )

    assert report.downloaded == 1
    assert report.manifest_path == campaign_dir / "corpus.jsonl"
    assert report.manifest_path is not None
    [entry] = load_manifest(report.manifest_path)
    assert entry.path.read_bytes() == pdf_bytes
    assert entry.license_class == "open_commercial"
    assert entry.license_source == "unpaywall:cc-by"


@pytest.mark.asyncio
async def test_campaign_build_records_resolution_failure_and_continues(tmp_path: Path) -> None:
    works = [
        _work("10.1000/bad", "Malformed"),
        _work("10.7717/peerj.4375", "The state of OA"),
    ]
    client = StubClient([{"doi": "10.1000/bad", "is_oa": "yes"}, _fixture("unpaywall_cc_by.json")])
    state = CampaignState(tmp_path / "campaign" / "state.jsonl")

    report = await build_campaign(
        works,
        campaign_dir=tmp_path / "campaign",
        state=state,
        client=client,
        dry_run=True,
    )

    assert report.resolved == 1
    assert report.failed == 1
    assert state.latest["10.1000/bad"].status == "resolution_failed"
    assert state.latest["10.7717/peerj.4375"].status == "resolved"


@pytest.mark.asyncio
async def test_campaign_build_state_redacts_contact_from_http_failures(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "bad path"})

    state = CampaignState(tmp_path / "campaign" / "state.jsonl")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="private-contact@example.org",
            client=transport,
            requests_per_second=None,
        )
        report = await build_campaign(
            [_work("10.1000/bad", "Bad path")],
            campaign_dir=tmp_path / "campaign",
            state=state,
            client=client,
            dry_run=True,
        )

    stored_error = state.latest["10.1000/bad"].payload["error"]
    assert report.failed == 1
    assert "private-contact@example.org" not in stored_error
    assert "422" in stored_error
