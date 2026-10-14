"""Build a corpus-local citation graph from cached Crossref references."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Document, DocumentCitation

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_DOI_PREFIX_RE = re.compile(r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)


def normalize_doi(value: object) -> str | None:
    """Return one comparable DOI, or ``None`` for a non-DOI value."""
    if not isinstance(value, str):
        return None
    candidate = _DOI_PREFIX_RE.sub("", value.strip()).strip()
    candidate = candidate.rstrip(".,;")
    if not _DOI_RE.fullmatch(candidate):
        return None
    return candidate.casefold()


def reference_dois_from_crossref(work: dict[str, Any]) -> list[str]:
    """Extract unique normalized DOI references in deterministic order."""
    references = work.get("reference", [])
    if not isinstance(references, list) or not all(
        isinstance(reference, dict) for reference in references
    ):
        raise ValueError("Crossref work field 'reference' must be a list of objects")
    return sorted(
        {
            doi
            for reference in references
            if (doi := normalize_doi(reference.get("DOI"))) is not None
        }
    )


@dataclass(frozen=True)
class CitationBuildReport:
    documents_scanned: int = 0
    references_found: int = 0
    matched: int = 0
    unmatched: int = 0
    self_citations_skipped: int = 0
    rows_written: int = 0
    rows_removed: int = 0
    dry_run: bool = True


async def build_citation_edges(
    session_factory: async_sessionmaker[AsyncSession], *, dry_run: bool = True
) -> CitationBuildReport:
    """Reconcile cached Crossref references with corpus-local documents.

    A row with a null target is an unresolved DOI pointer, not a graph edge.
    Rebuilding later resolves that row when the cited work enters the corpus.
    """
    async with session_factory() as session:
        documents = list(
            (await session.execute(select(Document).order_by(Document.id))).scalars().all()
        )
        doi_to_ids: dict[str, list[str]] = {}
        for document in documents:
            if doi := normalize_doi(document.doi):
                doi_to_ids.setdefault(doi, []).append(document.id)

        desired: dict[tuple[str, str], str | None] = {}
        scanned = references_found = matched = unmatched = self_skipped = 0
        authoritative_document_ids: list[str] = []
        for document in documents:
            crossref = (document.extra or {}).get("crossref")
            if not isinstance(crossref, dict) or "reference_dois" not in crossref:
                continue
            references = crossref.get("reference_dois")
            if not isinstance(references, list):
                raise ValueError(f"document {document.id} crossref.reference_dois must be a list")
            scanned += 1
            authoritative_document_ids.append(document.id)
            for cited_doi in sorted(
                {doi for value in references if (doi := normalize_doi(value)) is not None}
            ):
                references_found += 1
                if normalize_doi(document.doi) == cited_doi:
                    self_skipped += 1
                    continue
                target_ids = doi_to_ids.get(cited_doi, [])
                target_id = target_ids[0] if len(target_ids) == 1 else None
                desired[(document.id, cited_doi)] = target_id
                if target_id is None:
                    unmatched += 1
                else:
                    matched += 1

        existing = list(
            (
                await session.execute(
                    select(DocumentCitation).where(DocumentCitation.source == "crossref")
                )
            )
            .scalars()
            .all()
        )
        existing_by_key = {(row.citing_document_id, row.cited_doi): row for row in existing}
        stale = [
            row
            for row in existing
            if row.citing_document_id in authoritative_document_ids
            and (row.citing_document_id, row.cited_doi) not in desired
        ]
        writes = sum(
            key not in existing_by_key or existing_by_key[key].cited_document_id != target_id
            for key, target_id in desired.items()
        )
        report = CitationBuildReport(
            documents_scanned=scanned,
            references_found=references_found,
            matched=matched,
            unmatched=unmatched,
            self_citations_skipped=self_skipped,
            rows_written=writes,
            rows_removed=len(stale),
            dry_run=dry_run,
        )
        if dry_run:
            return report

        if stale:
            await session.execute(
                delete(DocumentCitation).where(DocumentCitation.id.in_([row.id for row in stale]))
            )
        for key, target_id in desired.items():
            row = existing_by_key.get(key)
            if row is None:
                session.add(
                    DocumentCitation(
                        citing_document_id=key[0],
                        cited_document_id=target_id,
                        cited_doi=key[1],
                        source="crossref",
                    )
                )
            elif row.cited_document_id != target_id:
                row.cited_document_id = target_id
        await session.commit()
        return report
