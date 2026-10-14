from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sci_rag.campaigns.resolve import resolve_unpaywall

FIXTURES = Path(__file__).parents[1] / "fixtures" / "campaigns"


class StubClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[str] = []

    async def get_json(self, url: str, *, params=None):  # type: ignore[no-untyped-def]
        self.calls.append(url)
        return self.payload


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_resolve_unpaywall_reads_best_oa_location() -> None:
    client = StubClient(_fixture("unpaywall_cc_by.json"))

    resolution = await resolve_unpaywall(client, "10.7717/PEERJ.4375")

    assert resolution.doi == "10.7717/peerj.4375"
    assert resolution.is_oa is True
    assert resolution.oa_status == "gold"
    assert resolution.license_string == "cc-by"
    assert resolution.license_class == "open_commercial"
    assert resolution.pdf_url == "https://peerj.com/articles/4375.pdf"
    assert resolution.landing_page_url == "https://peerj.com/articles/4375"
    assert client.calls[0].endswith("10.7717/peerj.4375")


@pytest.mark.asyncio
async def test_resolve_unpaywall_keeps_oa_without_license_unknown() -> None:
    resolution = await resolve_unpaywall(
        StubClient(_fixture("unpaywall_green_no_license.json")),
        "10.1038/s41586-020-2649-2",
    )

    assert resolution.is_oa is True
    assert resolution.license_class == "unknown"
    assert resolution.pdf_url == "https://repository.example.org/numpy.pdf"


@pytest.mark.asyncio
async def test_resolve_unpaywall_handles_closed_record_without_location() -> None:
    resolution = await resolve_unpaywall(
        StubClient(_fixture("unpaywall_closed.json")),
        "10.1000/closed",
    )

    assert resolution.is_oa is False
    assert resolution.license_class == "unknown"
    assert resolution.pdf_url is None


@pytest.mark.asyncio
async def test_resolve_unpaywall_rejects_mismatched_or_malformed_records() -> None:
    with pytest.raises(ValueError, match="DOI"):
        await resolve_unpaywall(StubClient({"doi": "10.1000/other", "is_oa": True}), "10.1000/a")
    with pytest.raises(ValueError, match="is_oa"):
        await resolve_unpaywall(StubClient({"doi": "10.1000/a", "is_oa": "yes"}), "10.1000/a")
