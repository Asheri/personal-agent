from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sci_rag.campaigns.discovery import (
    discover_by_dois,
    discover_by_topic,
    normalize_doi,
)
from sci_rag.campaigns.state import CampaignState

FIXTURES = Path(__file__).parents[1] / "fixtures" / "campaigns"


class StubClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str | int]]] = []

    async def get_json(
        self, url: str, *, params: dict[str, str | int] | None = None
    ) -> dict[str, Any]:
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.7717/PEERJ.4375", "10.7717/peerj.4375"),
        ("https://doi.org/10.7717/PEERJ.4375", "10.7717/peerj.4375"),
        ("doi:10.7717/peerj.4375", "10.7717/peerj.4375"),
        ("not a doi", None),
        ("", None),
    ],
)
def test_normalize_doi(raw: str, expected: str | None) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.asyncio
async def test_openalex_cursor_paging_deduplicates_and_counts_malformed_records() -> None:
    first_page = _fixture("openalex_page1.json")
    first_page["results"][0]["abstract_inverted_index"] = {
        "Open": [0],
        "access": [1],
        "improves": [2],
        "visibility.": [3],
    }
    client = StubClient([first_page, _fixture("openalex_page2.json")])

    report = await discover_by_topic(
        client,
        "open access",
        max_results=10,
        per_page=3,
    )

    assert [work.doi for work in report.works] == [
        "10.7717/peerj.4375",
        "10.1038/s41586-020-2649-2",
    ]
    assert report.malformed_records == 1
    assert report.duplicate_records == 1
    assert report.works[0].authors == ["Heather Piwowar", "Jason Priem"]
    assert report.works[0].journal == "PeerJ"
    assert report.works[0].oa_status_hint == "gold"
    assert report.works[0].abstract == "Open access improves visibility."
    assert "abstract_inverted_index" in client.calls[0][1]["select"]
    assert [params["cursor"] for _url, params in client.calls] == ["*", "cursor-page-2"]
    assert all(params["search"] == "open access" for _url, params in client.calls)


@pytest.mark.asyncio
async def test_doi_file_uses_crossref_metadata_and_collapses_duplicate_forms(
    tmp_path: Path,
) -> None:
    doi_file = tmp_path / "dois.txt"
    doi_file.write_text(
        "# seed list\n10.7717/PEERJ.4375\nhttps://doi.org/10.7717/peerj.4375\ninvalid\n",
        encoding="utf-8",
    )
    crossref = _fixture("crossref_work.json")
    crossref["message"]["abstract"] = "<jats:p>Open access &amp; citation impact.</jats:p>"
    client = StubClient([crossref])

    report = await discover_by_dois(client, doi_file)

    assert [work.doi for work in report.works] == ["10.7717/peerj.4375"]
    assert report.duplicate_records == 1
    assert report.malformed_records == 1
    assert report.works[0].title.startswith("The state of OA")
    assert report.works[0].year == 2018
    assert report.works[0].license_hint == "https://creativecommons.org/licenses/by/4.0/"
    assert report.works[0].abstract == "Open access & citation impact."
    assert client.calls[0][0].endswith("10.7717%2Fpeerj.4375")


@pytest.mark.asyncio
async def test_malformed_openalex_envelope_fails_visibly() -> None:
    client = StubClient([{"meta": {}, "results": "not-a-list"}])

    with pytest.raises(ValueError, match="results"):
        await discover_by_topic(client, "rice straw", max_results=2)


@pytest.mark.asyncio
async def test_topic_discovery_skips_dois_already_in_campaign_state(tmp_path: Path) -> None:
    state = CampaignState(tmp_path / "state.jsonl")
    state.append(doi="10.7717/peerj.4375", status="discovered")
    client = StubClient([_fixture("openalex_page1.json"), _fixture("openalex_page2.json")])

    report = await discover_by_topic(
        client,
        "open access",
        max_results=10,
        per_page=3,
        state=state,
    )

    assert [work.doi for work in report.works] == ["10.1038/s41586-020-2649-2"]
    assert report.skipped_processed == 1
    assert state.is_processed("10.1038/s41586-020-2649-2")


@pytest.mark.asyncio
async def test_topic_discovery_does_no_network_work_when_state_is_at_total_cap(
    tmp_path: Path,
) -> None:
    state = CampaignState(tmp_path / "state.jsonl")
    state.append(doi="10.7717/peerj.4375", status="discovered")
    state.append(doi="10.1038/s41586-020-2649-2", status="discovered")
    client = StubClient([])

    report = await discover_by_topic(
        client,
        "open access",
        max_results=2,
        state=state,
    )

    assert report.works == []
    assert report.skipped_processed == 2
    assert client.calls == []
