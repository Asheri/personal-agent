"""Orchestrate OA resolution, legal downloads, and manifest generation."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from sci_rag.campaigns.discovery import CandidateWork, normalize_doi
from sci_rag.campaigns.download import DownloadOutcome, download_pdf
from sci_rag.campaigns.http import PoliteHttpClient
from sci_rag.campaigns.manifest import ManifestItem, write_campaign_manifest
from sci_rag.campaigns.resolve import UNPAYWALL_API_URL, OaResolution, resolve_unpaywall
from sci_rag.campaigns.state import CampaignState
from sci_rag.licensing import LICENSE_CLASSES


@dataclass
class CampaignBuildReport:
    #: Candidates this invocation worked on, after the maximum was applied.
    candidates: int
    #: Candidates the campaign holds in state. Equal to ``candidates`` when no
    #: maximum applied. Reported separately because a trial that says
    #: "candidates 100" reads as having processed 100 of them.
    retained: int = 0
    resolutions: dict[str, OaResolution] = field(default_factory=dict)
    download_outcomes: list[DownloadOutcome] = field(default_factory=list)
    failed: int = 0
    manifest_path: Path | None = None

    @property
    def resolved(self) -> int:
        return len(self.resolutions)

    @property
    def direct_pdfs(self) -> int:
        return sum(
            1
            for resolution in self.resolutions.values()
            if resolution.is_oa and resolution.pdf_url is not None
        )

    @property
    def downloaded(self) -> int:
        return sum(1 for outcome in self.download_outcomes if outcome.status == "downloaded")

    @property
    def resumed(self) -> int:
        return sum(1 for outcome in self.download_outcomes if outcome.status == "resumed")

    @property
    def unavailable(self) -> int:
        return sum(
            1
            for resolution in self.resolutions.values()
            if not resolution.is_oa or resolution.pdf_url is None
        )

    @property
    def rejected(self) -> int:
        return sum(1 for outcome in self.download_outcomes if outcome.status == "rejected")

    @property
    def license_counts(self) -> dict[str, int]:
        return dict(Counter(resolution.license_class for resolution in self.resolutions.values()))


async def build_campaign(
    works: list[CandidateWork],
    *,
    campaign_dir: Path,
    state: CampaignState,
    client: PoliteHttpClient,
    dry_run: bool,
    max_pdf_bytes: int = 25 * 1024 * 1024,
    unpaywall_base_url: str = UNPAYWALL_API_URL,
    max_results: int | None = None,
) -> CampaignBuildReport:
    """Resolve candidates, then optionally download and write a manifest.

    ``max_results`` bounds how many retained candidates this invocation works
    on. It has to be applied here rather than only at discovery, because a
    campaign with state resumes from that state: a reader who discovers 100
    works and then runs a bounded trial over 20 was making 100 Unpaywall
    requests and would have attempted 100 downloads.

    The bound is a prefix of the candidate list, and campaign state is
    append-only, so the same candidates are in scope on every retry. A trial
    that resumed onto a different subset would resolve rights for more works
    than the reader authorized, one retry at a time.
    """
    retained = len(works)
    if max_results is not None:
        works = works[:max_results]
    report = CampaignBuildReport(candidates=len(works), retained=retained)
    manifest_items: list[ManifestItem] = []
    cached = _cached_resolutions(state)

    for work in works:
        resolution = cached.get(work.doi)
        if resolution is None:
            try:
                resolution = await resolve_unpaywall(
                    client,
                    work.doi,
                    base_url=unpaywall_base_url,
                    email=getattr(client, "mailto", None),
                )
            except Exception as exc:
                report.failed += 1
                state.append(
                    doi=work.doi,
                    status="resolution_failed",
                    payload={"error": _safe_error(exc)},
                )
                continue
            state.append(
                doi=work.doi,
                status="resolved",
                payload={"resolution": asdict(resolution)},
            )
        report.resolutions[work.doi] = resolution
        if dry_run:
            continue
        try:
            outcome = await download_pdf(
                resolution,
                pdf_dir=campaign_dir / "pdfs",
                state=state,
                client=client,
                max_bytes=max_pdf_bytes,
            )
        except Exception as exc:
            report.failed += 1
            state.append(
                doi=work.doi,
                status="download_failed",
                payload={"error": _safe_error(exc)},
            )
            continue
        report.download_outcomes.append(outcome)
        if outcome.path is not None and outcome.status in {"downloaded", "resumed"}:
            manifest_items.append(
                ManifestItem(work=work, resolution=resolution, pdf_path=outcome.path)
            )

    if not dry_run:
        report.manifest_path = campaign_dir / "corpus.jsonl"
        write_campaign_manifest(
            report.manifest_path,
            manifest_items,
            source=f"campaign:{campaign_dir.name}",
        )
    return report


def load_discovered_candidates(state: CampaignState) -> list[CandidateWork]:
    """Recover unique discovery records from append-only campaign state."""
    candidates: dict[str, CandidateWork] = {}
    for record in state.records:
        if record.status != "discovered":
            continue
        candidate = _candidate_from_payload(record.payload, expected_doi=record.doi)
        candidates[record.doi] = candidate
    return list(candidates.values())


def _candidate_from_payload(payload: dict[str, Any], *, expected_doi: str) -> CandidateWork:
    doi = normalize_doi(payload.get("doi", ""))
    authors = payload.get("authors", [])
    year = payload.get("year")
    if doi != expected_doi:
        raise ValueError(f"campaign state candidate DOI mismatch for {expected_doi}")
    if not isinstance(authors, list) or not all(isinstance(author, str) for author in authors):
        raise ValueError(f"campaign state candidate authors are invalid for {expected_doi}")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
        raise ValueError(f"campaign state candidate year is invalid for {expected_doi}")
    fields: dict[str, str | None] = {}
    for name in (
        "title",
        "abstract",
        "journal",
        "oa_status_hint",
        "license_hint",
        "source",
    ):
        value = payload.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"campaign state candidate {name} is invalid for {expected_doi}")
        fields[name] = value
    return CandidateWork(
        doi=doi,
        title=fields["title"],
        abstract=fields["abstract"],
        year=year,
        authors=authors,
        journal=fields["journal"],
        oa_status_hint=fields["oa_status_hint"],
        license_hint=fields["license_hint"],
        source=fields["source"] or "unknown",
    )


def _cached_resolutions(state: CampaignState) -> dict[str, OaResolution]:
    resolutions: dict[str, OaResolution] = {}
    for record in state.records:
        if record.status != "resolved":
            continue
        raw = record.payload.get("resolution")
        if not isinstance(raw, dict):
            raise ValueError(f"campaign state resolution is invalid for {record.doi}")
        try:
            resolution = OaResolution(**raw)
        except TypeError as exc:
            raise ValueError(f"campaign state resolution is invalid for {record.doi}") from exc
        if resolution.doi != record.doi or resolution.license_class not in LICENSE_CLASSES:
            raise ValueError(f"campaign state resolution is invalid for {record.doi}")
        resolutions[record.doi] = resolution
    return resolutions


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTPStatusError: upstream returned {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return f"{type(exc).__name__}: upstream HTTP request failed"
    return f"{type(exc).__name__}: {exc}"[:500]
