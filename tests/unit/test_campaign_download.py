from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from sci_rag.campaigns.download import download_pdf, pdf_filename
from sci_rag.campaigns.http import PoliteHttpClient
from sci_rag.campaigns.resolve import OaResolution
from sci_rag.campaigns.state import CampaignState


def _resolution(
    *,
    doi: str = "10.7717/peerj.4375",
    is_oa: bool = True,
    pdf_url: str | None = "https://example.org/article.pdf",
) -> OaResolution:
    return OaResolution(
        doi=doi,
        is_oa=is_oa,
        oa_status="gold" if is_oa else "closed",
        license_string="cc-by" if is_oa else None,
        license_class="open_commercial" if is_oa else "unknown",
        pdf_url=pdf_url,
        landing_page_url="https://example.org/article",
    )


@pytest.mark.asyncio
async def test_non_oa_record_is_never_fetched(tmp_path: Path) -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org", client=transport, requests_per_second=None
        )
        state = CampaignState(tmp_path / "state.jsonl")
        outcome = await download_pdf(
            _resolution(is_oa=False, pdf_url=None),
            pdf_dir=tmp_path / "pdfs",
            state=state,
            client=client,
        )

    assert outcome.status == "unavailable"
    assert outcome.path is None
    assert requests == 0
    assert state.latest[outcome.doi].status == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "body", "detail"),
    [
        ({"Content-Type": "text/html"}, b"<html>paywall</html>", "content type"),
        (
            {"Content-Type": "application/pdf", "Content-Length": "1000"},
            b"%PDF-small",
            "size limit",
        ),
        ({"Content-Type": "application/pdf"}, b"not really a pdf", "signature"),
    ],
)
async def test_invalid_or_oversized_download_is_rejected(
    tmp_path: Path,
    headers: dict[str, str],
    body: bytes,
    detail: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org", client=transport, requests_per_second=None
        )
        state = CampaignState(tmp_path / "state.jsonl")
        outcome = await download_pdf(
            _resolution(),
            pdf_dir=tmp_path / "pdfs",
            state=state,
            client=client,
            max_bytes=100,
        )

    assert outcome.status == "rejected"
    assert detail in outcome.detail
    assert list((tmp_path / "pdfs").glob("*")) == []
    assert state.latest[outcome.doi].status == "rejected"


@pytest.mark.asyncio
async def test_pdf_download_is_atomic_and_resumes_from_existing_file(tmp_path: Path) -> None:
    requests = 0
    pdf_bytes = b"%PDF-1.7\nsmall fixture\n%%EOF"

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=pdf_bytes)

    state = CampaignState(tmp_path / "state.jsonl")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org", client=transport, requests_per_second=None
        )
        first = await download_pdf(
            _resolution(), pdf_dir=tmp_path / "pdfs", state=state, client=client
        )
        second = await download_pdf(
            _resolution(), pdf_dir=tmp_path / "pdfs", state=state, client=client
        )

    assert first.status == "downloaded"
    assert second.status == "resumed"
    assert first.path == second.path
    assert first.path is not None and first.path.read_bytes() == pdf_bytes
    assert requests == 1
    assert not list((tmp_path / "pdfs").glob("*.part"))


@pytest.mark.asyncio
async def test_existing_pdf_without_state_is_reused_after_interrupted_run(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    path = pdf_dir / pdf_filename("10.7717/peerj.4375")
    path.write_bytes(b"%PDF-1.7\ncompleted before state append")
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    state = CampaignState(tmp_path / "state.jsonl")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org", client=transport, requests_per_second=None
        )
        outcome = await download_pdf(_resolution(), pdf_dir=pdf_dir, state=state, client=client)

    assert outcome.status == "resumed"
    assert requests == 0
    assert state.latest[outcome.doi].status == "downloaded"
