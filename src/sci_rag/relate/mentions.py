"""Literal local links and DOI references, with no model inference or file reads."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.citations import normalize_doi
from sci_rag.db.models import Chunk, Document, DocumentCitation
from sci_rag.versions import lock_document_writes

_LINKS = re.compile(
    r"\[\[([^\]\n|]+)(?:\|[^\]\n]*)?\]\]|\[[^\]\n]*\]\(([^)\s]+)\)|`([^`\n]+\.[\w]+)`"
)
_DOIS = re.compile(r"10\.\d{4,9}/[A-Za-z0-9._;()/:+-]+", re.IGNORECASE)


def mention_keys(content: str) -> list[str]:
    keys = [
        next(v for v in match.groups() if v is not None).strip()
        for match in _LINKS.finditer(content)
    ]
    keys += [m.group().rstrip(".,;)") for m in _DOIS.finditer(content)]
    return list(dict.fromkeys(k for k in keys if k and ("://" not in k or normalize_doi(k))))


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def resolve_key(key: str, source: Document, documents: list[Document]) -> tuple[str | None, bool]:
    decoded = unquote(key).split("#", 1)[0].strip()
    if doi := normalize_doi(decoded):
        matches = [d.id for d in documents if normalize_doi(d.doi) == doi]
    else:
        source_path = (source.extra or {}).get("path")
        relative = None
        if isinstance(source_path, str) and source_path and Path(source_path).is_absolute():
            relative = os.path.normcase(os.path.abspath(Path(source_path).parent / decoded))
        matches = [d.id for d in documents if relative and (d.extra or {}).get("path") == relative]
        if not matches:
            matches = [
                d.id
                for d in documents
                if _normalized(decoded)
                in {_normalized(d.title), _normalized(Path((d.extra or {}).get("path", "")).name)}
            ]
    return (matches[0] if len(matches) == 1 else None, len(matches) > 1)


async def build_mentions(
    factory: async_sessionmaker[AsyncSession], *, apply: bool = False
) -> dict[str, int | bool]:
    async with factory() as session:
        await lock_document_writes(session)
        documents = list(
            (
                await session.scalars(
                    select(Document).where(Document.is_current.is_(True)).order_by(Document.id)
                )
            ).all()
        )
        by_id = {d.id: d for d in documents}
        chunks = list(
            (
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.document_id.in_(by_id))
                    .order_by(Chunk.document_id, Chunk.chunk_index)
                )
            ).all()
        )
        existing = list(
            (
                await session.scalars(
                    select(DocumentCitation).where(DocumentCitation.citing_document_id.in_(by_id))
                )
            ).all()
        )
        crossref_pairs = {
            (r.citing_document_id, r.cited_document_id)
            for r in existing
            if r.source == "crossref" and r.cited_document_id
        }
        desired: dict[str, dict[str, tuple[str | None, str, str | None, str]]] = defaultdict(dict)
        matched = ambiguous = self_skipped = 0
        pairs: set[tuple[str, str]] = set()
        for chunk in chunks:
            for key in mention_keys(chunk.content):
                target, is_ambiguous = resolve_key(key, by_id[chunk.document_id], documents)
                if target == chunk.document_id:
                    self_skipped += 1
                    continue
                if (chunk.document_id, target) in crossref_pairs or (
                    target is not None and (chunk.document_id, target) in pairs
                ):
                    continue
                normalized = _normalized(key)
                if normalized in desired[chunk.document_id]:
                    continue
                if target:
                    pairs.add((chunk.document_id, target))
                    matched += 1
                ambiguous += is_ambiguous
                desired[chunk.document_id][normalized] = (target, chunk.id, normalize_doi(key), key)
        old: dict[str, dict[str, tuple[str | None, str | None, str | None, str | None]]] = (
            defaultdict(dict)
        )
        for row in existing:
            if row.source == "mention":
                old[row.citing_document_id][_normalized(row.cited_key or "")] = (
                    row.cited_document_id,
                    row.evidence_chunk_id,
                    row.cited_doi,
                    row.cited_key,
                )
        changed = {d.id for d in documents if old[d.id] != desired[d.id]}
        removed = sum(r.source == "mention" and r.citing_document_id in changed for r in existing)
        written = sum(len(desired[i]) for i in changed)
        if apply and changed:
            await session.execute(
                delete(DocumentCitation).where(
                    DocumentCitation.source == "mention",
                    DocumentCitation.citing_document_id.in_(changed),
                )
            )
            await session.flush()
            for source_id in sorted(changed):
                for target, chunk_id, doi, literal in desired[source_id].values():
                    session.add(
                        DocumentCitation(
                            citing_document_id=source_id,
                            cited_document_id=target,
                            cited_key=literal,
                            cited_doi=doi,
                            evidence_chunk_id=chunk_id,
                            confidence=1.0,
                            source="mention",
                        )
                    )
            await session.commit()
        return {
            "documents_scanned": len(documents),
            "mentions": sum(len(v) for v in desired.values()),
            "matched": matched,
            "ambiguous": ambiguous,
            "self_skipped": self_skipped,
            "rows_written": written,
            "rows_removed": removed,
            "applied": apply,
        }
