"""Download only direct Unpaywall PDF locations with bounded resources."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from sci_rag.campaigns.http import PoliteHttpClient
from sci_rag.campaigns.resolve import OaResolution
from sci_rag.campaigns.state import CampaignState


@dataclass(frozen=True)
class DownloadOutcome:
    doi: str
    status: str
    path: Path | None = None
    detail: str = ""


def pdf_filename(doi: str) -> str:
    readable = re.sub(r"[^a-z0-9._-]+", "_", doi.casefold()).strip("_")
    digest = hashlib.sha256(doi.casefold().encode("utf-8")).hexdigest()[:10]
    return f"{readable[:100]}-{digest}.pdf"


async def download_pdf(
    resolution: OaResolution,
    *,
    pdf_dir: Path,
    state: CampaignState,
    client: PoliteHttpClient,
    max_bytes: int = 25 * 1024 * 1024,
) -> DownloadOutcome:
    """Persist one verified direct OA PDF atomically, or record why not."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if not resolution.is_oa or resolution.pdf_url is None:
        return _record(
            state,
            DownloadOutcome(
                doi=resolution.doi,
                status="unavailable",
                detail="no direct open-access PDF location",
            ),
            resolution,
        )

    target = pdf_dir / pdf_filename(resolution.doi)
    if _valid_existing_pdf(target, max_bytes=max_bytes):
        outcome = DownloadOutcome(
            doi=resolution.doi,
            status="resumed",
            path=target,
            detail="verified existing PDF",
        )
        latest = state.latest.get(resolution.doi)
        if latest is None or latest.status != "downloaded":
            _append_downloaded(state, outcome, resolution)
        return outcome
    if target.exists():
        target.unlink()

    async with client.stream(resolution.pdf_url) as response:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/pdf":
            return _reject(
                state, resolution, f"unexpected content type {content_type or 'missing'}"
            )
        content_length = _content_length(response.headers.get("Content-Length"))
        if content_length is not None and content_length > max_bytes:
            return _reject(state, resolution, "declared size exceeds size limit")

        pdf_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".pdf.part")
        written = 0
        prefix = b""
        try:
            with temporary.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        return _reject(
                            state,
                            resolution,
                            "downloaded bytes exceed size limit",
                            temporary=temporary,
                        )
                    if len(prefix) < 5:
                        prefix = (prefix + chunk)[:5]
                    handle.write(chunk)
                handle.flush()
            if prefix != b"%PDF-":
                return _reject(
                    state,
                    resolution,
                    "content has no PDF signature",
                    temporary=temporary,
                )
            temporary.replace(target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    outcome = DownloadOutcome(
        doi=resolution.doi,
        status="downloaded",
        path=target,
        detail=f"{written} bytes",
    )
    _append_downloaded(state, outcome, resolution)
    return outcome


def _valid_existing_pdf(path: Path, *, max_bytes: int) -> bool:
    if not path.is_file() or path.stat().st_size > max_bytes:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError:
        return None
    return length if length >= 0 else None


def _reject(
    state: CampaignState,
    resolution: OaResolution,
    detail: str,
    *,
    temporary: Path | None = None,
) -> DownloadOutcome:
    if temporary is not None:
        temporary.unlink(missing_ok=True)
    return _record(
        state,
        DownloadOutcome(doi=resolution.doi, status="rejected", detail=detail),
        resolution,
    )


def _record(
    state: CampaignState,
    outcome: DownloadOutcome,
    resolution: OaResolution,
) -> DownloadOutcome:
    state.append(
        doi=outcome.doi,
        status=outcome.status,
        payload={"detail": outcome.detail, "resolution": asdict(resolution)},
    )
    return outcome


def _append_downloaded(
    state: CampaignState,
    outcome: DownloadOutcome,
    resolution: OaResolution,
) -> None:
    assert outcome.path is not None
    state.append(
        doi=outcome.doi,
        status="downloaded",
        payload={
            "path": str(outcome.path),
            "detail": outcome.detail,
            "resolution": asdict(resolution),
        },
    )
