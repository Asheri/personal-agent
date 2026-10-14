"""Crossref metadata enrichment for documents already in the corpus."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any, Protocol
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.citations import reference_dois_from_crossref
from sci_rag.db.models import Document


class JsonClient(Protocol):
    def get_json(
        self, url: str, *, params: Mapping[str, str | int] | None = None
    ) -> Awaitable[dict[str, Any]]: ...


@dataclass(frozen=True)
class CrossrefMetadata:
    """The small, validated subset of a Crossref work the corpus stores."""

    is_retracted: bool
    retraction_notice_doi: str | None
    citation_count: int | None
    journal: str | None
    reference_dois: tuple[str, ...]


@dataclass(frozen=True)
class EnrichmentOutcome:
    document_id: str
    doi: str
    status: str
    detail: str = ""


@dataclass
class EnrichmentReport:
    outcomes: list[EnrichmentOutcome] = field(default_factory=list)

    @property
    def enriched(self) -> int:
        return sum(outcome.status == "enriched" for outcome in self.outcomes)

    @property
    def planned(self) -> int:
        return sum(outcome.status == "planned" for outcome in self.outcomes)

    @property
    def skipped(self) -> int:
        return sum(outcome.status == "skipped_recent" for outcome in self.outcomes)

    @property
    def failed(self) -> int:
        return sum(outcome.status == "failed" for outcome in self.outcomes)


def parse_crossref_work(work: dict[str, Any]) -> CrossrefMetadata:
    """Parse retraction and citation metadata from one Crossref work."""
    # Crossref exposes both directions. Current individual-work records use
    # ``updated-by`` for the notice that retracted the queried work; some
    # Retraction Watch and older shapes expose the assertion in ``update-to``.
    # Accept both explicit signals and never infer status from a title.
    updated_by = _update_entries(work, "updated-by")
    update_to = _update_entries(work, "update-to")
    retraction = next(
        (
            notice
            for notice in [*updated_by, *update_to]
            if str(notice.get("type", "")).casefold() == "retraction"
        ),
        None,
    )
    journals = work.get("container-title", [])
    journal = journals[0] if isinstance(journals, list) and journals else None
    citation_count = work.get("is-referenced-by-count")
    return CrossrefMetadata(
        is_retracted=retraction is not None,
        retraction_notice_doi=(
            str(retraction["DOI"]) if retraction and retraction.get("DOI") else None
        ),
        citation_count=citation_count if isinstance(citation_count, int) else None,
        journal=unescape(journal) if isinstance(journal, str) else None,
        reference_dois=tuple(reference_dois_from_crossref(work)),
    )


def _update_entries(work: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    entries = work.get(field_name, [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError(f"Crossref work field '{field_name}' must be a list of objects")
    return entries


async def enrich_documents(
    session_factory: async_sessionmaker[AsyncSession],
    client: JsonClient,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    refresh: bool = False,
    stale_after: timedelta = timedelta(days=30),
) -> EnrichmentReport:
    """Enrich DOI-bearing corpus documents, isolating failures per document."""
    async with session_factory() as session:
        query = (
            select(Document.id, Document.doi, Document.extra)
            .where(Document.doi.is_not(None))
            .order_by(Document.id)
        )
        if limit is not None:
            query = query.limit(limit)
        documents = list(await session.execute(query))

    report = EnrichmentReport()
    for document_id, doi, extra in documents:
        assert doi is not None
        if not refresh and _enrichment_is_recent(extra, stale_after=stale_after):
            report.outcomes.append(EnrichmentOutcome(document_id, doi, "skipped_recent"))
            continue
        if dry_run:
            report.outcomes.append(EnrichmentOutcome(document_id, doi, "planned"))
            continue
        try:
            payload = await client.get_json(f"https://api.crossref.org/works/{quote(doi, safe='')}")
            work = payload.get("message")
            if not isinstance(work, dict):
                raise ValueError("Crossref response field 'message' must be an object")
            metadata = parse_crossref_work(work)
            enriched_at = datetime.now(UTC).isoformat()
            async with session_factory() as session:
                document = await session.get(Document, document_id)
                if document is None:
                    raise ValueError(f"document {document_id} disappeared during enrichment")
                extra = dict(document.extra or {})
                extra["crossref"] = {
                    "is_retracted": metadata.is_retracted,
                    "retraction_notice_doi": metadata.retraction_notice_doi,
                    "citation_count": metadata.citation_count,
                    "journal": metadata.journal,
                    "reference_dois": list(metadata.reference_dois),
                    "enriched_at": enriched_at,
                }
                document.extra = extra
                if metadata.journal:
                    document.journal = metadata.journal
                await session.commit()
            report.outcomes.append(EnrichmentOutcome(document_id, doi, "enriched"))
        except Exception as exc:
            report.outcomes.append(
                EnrichmentOutcome(document_id, doi, "failed", f"{type(exc).__name__}: {exc}")
            )
    return report


def _enrichment_is_recent(extra: dict[str, Any] | None, *, stale_after: timedelta) -> bool:
    crossref = (extra or {}).get("crossref")
    if not isinstance(crossref, dict):
        return False
    enriched_at = crossref.get("enriched_at")
    if not isinstance(enriched_at, str):
        return False
    try:
        timestamp = datetime.fromisoformat(enriched_at)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        return False
    return datetime.now(UTC) - timestamp.astimezone(UTC) < stale_after
