"""Discover scientific works from a topic or a DOI seed file.

The public functions return one normalized record shape regardless of the
upstream catalog. Network and persistence seams are injected so discovery is
fully testable offline and a campaign can resume without a database.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, unquote

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_DOI_PREFIX_RE = re.compile(
    r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)",
    re.IGNORECASE,
)


class JsonClient(Protocol):
    async def get_json(
        self, url: str, *, params: Mapping[str, str | int] | None = None
    ) -> dict[str, Any]: ...


class CampaignStateSink(Protocol):
    @property
    def processed_dois(self) -> set[str]: ...

    def is_processed(self, doi: str) -> bool: ...

    def append(
        self,
        *,
        doi: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class CandidateWork:
    doi: str
    title: str | None = None
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    journal: str | None = None
    oa_status_hint: str | None = None
    license_hint: str | None = None
    source: str = "unknown"
    abstract: str | None = None


@dataclass
class DiscoveryReport:
    works: list[CandidateWork] = field(default_factory=list)
    malformed_records: int = 0
    duplicate_records: int = 0
    skipped_processed: int = 0


def normalize_doi(value: str) -> str | None:
    """Return a lowercase bare DOI, or ``None`` for an invalid value."""
    if not isinstance(value, str):
        return None
    normalized = unquote(value.strip())
    normalized = _DOI_PREFIX_RE.sub("", normalized).strip().lower()
    if not normalized or any(character.isspace() for character in normalized):
        return None
    return normalized if _DOI_RE.fullmatch(normalized) else None


async def discover_by_topic(
    client: JsonClient,
    topic: str,
    *,
    max_results: int = 100,
    per_page: int = 100,
    state: CampaignStateSink | None = None,
    api_key: str | None = None,
) -> DiscoveryReport:
    """Page OpenAlex by cursor and return normalized, unique DOI records."""
    topic = " ".join(topic.split())
    if not topic:
        raise ValueError("topic must not be empty")
    if max_results <= 0:
        raise ValueError("max_results must be positive")
    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100")

    report = DiscoveryReport()
    processed_count = len(state.processed_dois) if state is not None else 0
    report.skipped_processed = processed_count
    new_result_limit = max(0, max_results - processed_count)
    seen: set[str] = set()
    cursor: str | None = "*"
    used_cursors: set[str] = set()

    while cursor is not None and len(report.works) < new_result_limit:
        if cursor in used_cursors:
            raise ValueError("OpenAlex repeated a cursor instead of advancing")
        used_cursors.add(cursor)
        params: dict[str, str | int] = {
            "search": topic,
            "cursor": cursor,
            "per_page": min(per_page, new_result_limit - len(report.works)),
            "select": (
                "doi,title,abstract_inverted_index,publication_year,authorships,primary_location,"
                "open_access,best_oa_location"
            ),
        }
        if api_key:
            params["api_key"] = api_key
        payload = await client.get_json(OPENALEX_WORKS_URL, params=params)
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("OpenAlex response results must be a list")

        for raw in raw_results:
            candidate = _candidate_from_openalex(raw)
            if candidate is None:
                report.malformed_records += 1
                continue
            if candidate.doi in seen:
                report.duplicate_records += 1
                continue
            seen.add(candidate.doi)
            if state is not None and state.is_processed(candidate.doi):
                continue
            _record_candidate(report, candidate, state)
            if len(report.works) == new_result_limit:
                break

        meta = payload.get("meta")
        if not isinstance(meta, dict):
            raise ValueError("OpenAlex response meta must be an object")
        next_cursor = meta.get("next_cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError("OpenAlex next_cursor must be a string or null")
        cursor = next_cursor
        if not raw_results:
            break

    return report


async def discover_by_dois(
    client: JsonClient,
    path: Path,
    *,
    state: CampaignStateSink | None = None,
) -> DiscoveryReport:
    """Read DOI seeds, enrich them through Crossref, and deduplicate them."""
    report = DiscoveryReport()
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line or raw_line.startswith("#"):
            continue
        doi = normalize_doi(raw_line)
        if doi is None:
            report.malformed_records += 1
            continue
        if doi in seen:
            report.duplicate_records += 1
            continue
        seen.add(doi)
        if state is not None and state.is_processed(doi):
            report.skipped_processed += 1
            continue

        payload = await client.get_json(f"{CROSSREF_WORKS_URL}/{quote(doi, safe='')}")
        candidate = _candidate_from_crossref(payload)
        if candidate is None:
            report.malformed_records += 1
            continue
        _record_candidate(report, candidate, state)
    return report


def _record_candidate(
    report: DiscoveryReport,
    candidate: CandidateWork,
    state: CampaignStateSink | None,
) -> None:
    report.works.append(candidate)
    if state is not None:
        state.append(doi=candidate.doi, status="discovered", payload=asdict(candidate))


def _candidate_from_openalex(raw: Any) -> CandidateWork | None:
    if not isinstance(raw, dict):
        return None
    doi = normalize_doi(raw.get("doi", ""))
    if doi is None:
        return None
    authors: list[str] = []
    raw_authorships = raw.get("authorships")
    if isinstance(raw_authorships, list):
        for authorship in raw_authorships:
            if not isinstance(authorship, dict) or not isinstance(authorship.get("author"), dict):
                continue
            name = authorship["author"].get("display_name")
            if isinstance(name, str) and name.strip():
                authors.append(" ".join(name.split()))

    location = raw.get("primary_location")
    source = location.get("source") if isinstance(location, dict) else None
    journal = source.get("display_name") if isinstance(source, dict) else None
    open_access = raw.get("open_access")
    oa_status = open_access.get("oa_status") if isinstance(open_access, dict) else None
    best_location = raw.get("best_oa_location")
    license_hint = best_location.get("license") if isinstance(best_location, dict) else None
    year = raw.get("publication_year")
    title = raw.get("title")
    return CandidateWork(
        doi=doi,
        title=title.strip() if isinstance(title, str) and title.strip() else None,
        abstract=_abstract_from_openalex(raw.get("abstract_inverted_index")),
        year=year if isinstance(year, int) and not isinstance(year, bool) else None,
        authors=authors,
        journal=journal.strip() if isinstance(journal, str) and journal.strip() else None,
        oa_status_hint=oa_status if isinstance(oa_status, str) else None,
        license_hint=license_hint if isinstance(license_hint, str) else None,
        source="openalex",
    )


def _candidate_from_crossref(payload: dict[str, Any]) -> CandidateWork | None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    doi = normalize_doi(message.get("DOI", ""))
    if doi is None:
        return None
    titles = message.get("title")
    title = (
        titles[0] if isinstance(titles, list) and titles and isinstance(titles[0], str) else None
    )
    journals = message.get("container-title")
    journal = (
        journals[0]
        if isinstance(journals, list) and journals and isinstance(journals[0], str)
        else None
    )
    authors: list[str] = []
    raw_authors = message.get("author")
    if isinstance(raw_authors, list):
        for raw_author in raw_authors:
            if not isinstance(raw_author, dict):
                continue
            name = " ".join(
                part.strip()
                for part in (raw_author.get("given"), raw_author.get("family"))
                if isinstance(part, str) and part.strip()
            )
            if name:
                authors.append(name)
    year = _crossref_year(message)
    raw_licenses = message.get("license")
    license_hint = None
    if isinstance(raw_licenses, list):
        for raw_license in raw_licenses:
            if isinstance(raw_license, dict) and isinstance(raw_license.get("URL"), str):
                license_hint = raw_license["URL"]
                break
    return CandidateWork(
        doi=doi,
        title=title.strip() if title and title.strip() else None,
        abstract=_abstract_from_crossref(message.get("abstract")),
        year=year,
        authors=authors,
        journal=journal.strip() if journal and journal.strip() else None,
        license_hint=license_hint,
        source="crossref",
    )


def _abstract_from_openalex(raw: Any) -> str | None:
    """Reconstruct OpenAlex's inverted-index abstract without guessing gaps."""
    if not isinstance(raw, dict):
        return None
    positioned: dict[int, str] = {}
    for token, raw_positions in raw.items():
        if not isinstance(token, str) or not isinstance(raw_positions, list):
            return None
        for position in raw_positions:
            if (
                isinstance(position, bool)
                or not isinstance(position, int)
                or position < 0
                or position in positioned
            ):
                return None
            positioned[position] = token
    if not positioned or sorted(positioned) != list(range(len(positioned))):
        return None
    return " ".join(positioned[position] for position in range(len(positioned)))


def _abstract_from_crossref(raw: Any) -> str | None:
    """Normalize Crossref's optional JATS fragment to plain screening text."""
    if not isinstance(raw, str):
        return None
    without_tags = re.sub(r"<[^>]+>", " ", raw)
    normalized = " ".join(html.unescape(without_tags).split())
    return normalized or None


def _crossref_year(message: dict[str, Any]) -> int | None:
    for field_name in ("published", "published-print", "published-online", "issued"):
        value = message.get(field_name)
        parts = value.get("date-parts") if isinstance(value, dict) else None
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
            and isinstance(parts[0][0], int)
            and not isinstance(parts[0][0], bool)
        ):
            return parts[0][0]
    return None
