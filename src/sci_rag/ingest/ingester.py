"""Ingestion: files in, embedded chunks out.

For each corpus entry: parse, chunk, deduplicate, embed, store, all inside
one transaction per document so a failure never leaves half a document
behind. Re-running ingestion over unchanged parsed chunks is a no-op;
the coarse SHA-256 is followed by an exact chunk comparison. Canonical
source path and member identify a chain independently of its content hash.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db import Chunk, Document, session_scope
from sci_rag.db.models import KgCommunity, KgEntity
from sci_rag.document_dates import document_date
from sci_rag.embed.provider import EmbeddingProvider
from sci_rag.ingest.chunker import ChunkDraft, chunk_document
from sci_rag.ingest.errors import ParserError
from sci_rag.ingest.fingerprint import (
    PlaceholderFileError,
    SourceFingerprint,
    fingerprint,
    ingest_signature,
)
from sci_rag.ingest.manifest import CorpusEntry
from sci_rag.ingest.parsers import ParsedDocument, parse_file, parse_file_many
from sci_rag.ingest.suffixes import parser_for_suffix
from sci_rag.versions import canonical_source_path, identity_key_for, lock_document_writes

log = structlog.get_logger(__name__)


@dataclass
class IngestOutcome:
    path: str
    status: str  # "ingested" | "skipped_duplicate" | "failed"
    detail: str = ""
    document_id: str | None = None
    chunk_count: int = 0
    graph_changed: bool = False
    parser: str = ""
    document_count: int = 1
    documents_removed: int = 0


@dataclass(frozen=True)
class PendingIngest:
    """A reconcile decision, checked again under the transaction writer lock."""

    entry: CorpusEntry
    predecessor_id: str | None
    version_seq: int
    source_fingerprint: SourceFingerprint
    is_current: bool = True


@dataclass(frozen=True)
class PendingHostIngest:
    entry: CorpusEntry
    source_fingerprint: SourceFingerprint
    # Complete current-host snapshot, not merely the first message.
    members: dict[str, tuple[str, int]]


@dataclass
class IngestReport:
    outcomes: list[IngestOutcome] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "ingested")

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "skipped_duplicate")

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")


def content_hash_for(drafts: list[ChunkDraft]) -> str:
    joined = "\n\n".join(d.body for d in drafts)
    normalized = " ".join(joined.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_citation(entry: CorpusEntry, title: str) -> str:
    """A human-readable citation from whatever metadata the manifest offered."""
    pieces: list[str] = []
    if entry.authors:
        pieces.append(", ".join(entry.authors))
    if entry.year:
        pieces.append(f"({entry.year})")
    pieces.append(title if title.endswith(".") else f"{title}.")
    if entry.doi:
        pieces.append(f"https://doi.org/{entry.doi.removeprefix('https://doi.org/')}")
    elif entry.url:
        pieces.append(entry.url)
    return " ".join(pieces)


async def ingest_entries(
    entries: Sequence[CorpusEntry | PendingIngest | PendingHostIngest],
    *,
    embedder: EmbeddingProvider,
    target_tokens: int = 800,
    overlap_tokens: int = 150,
    prefer_docling: bool = True,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> IngestReport:
    report = IngestReport()
    for entry in entries:
        actual_entry = (
            entry.entry if isinstance(entry, (PendingIngest, PendingHostIngest)) else entry
        )
        ingest = _ingest_host if actual_entry.path.suffix.lower() == ".mbox" else _ingest_one
        outcome = await ingest(
            entry,
            embedder=embedder,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            prefer_docling=prefer_docling,
            session_factory=session_factory,
        )
        outcome.parser = outcome.parser or parser_for_suffix(actual_entry.path.suffix)
        report.outcomes.append(outcome)
        log.info(
            "ingest_outcome",
            status=outcome.status,
            chunks=outcome.chunk_count,
        )
    return report


@asynccontextmanager
async def _writer_session(
    factory: async_sessionmaker[AsyncSession] | None, existing: AsyncSession | None
) -> AsyncIterator[AsyncSession]:
    if existing is not None:
        yield existing
    else:
        async with session_scope(factory=factory) as session:
            yield session


async def _ingest_host(
    entry: CorpusEntry | PendingIngest | PendingHostIngest,
    *,
    embedder: EmbeddingProvider,
    target_tokens: int,
    overlap_tokens: int,
    prefer_docling: bool,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> IngestOutcome:
    pending = entry if isinstance(entry, PendingHostIngest) else None
    if isinstance(entry, PendingIngest):
        return IngestOutcome(
            path=str(entry.entry.path), status="failed", detail="host_plan_required", parser="mbox"
        )
    source = pending.entry if pending else entry
    assert isinstance(source, CorpusEntry)
    try:
        observed = fingerprint(source.path)
        if pending and observed != pending.source_fingerprint:
            raise ValueError("source_changed_since_scan")
        documents = parse_file_many(source.path, prefer_docling=prefer_docling)
        if fingerprint(source.path) != observed:
            raise ValueError("source_changed_during_parse")
        members = [d.metadata["source_member"] for d in documents]
        if len(members) != len(set(members)):
            raise ValueError("ambiguous_host_members")
        from sci_rag.corpus import delete_documents_in_session

        async with session_scope(factory=session_factory) as session:
            await lock_document_writes(session)
            old = list(
                (
                    await session.scalars(
                        select(Document).where(
                            Document.extra["path"].astext == canonical_source_path(source.path)
                        )
                    )
                ).all()
            )
            current = {d.identity_key: (d.id, d.version_seq) for d in old if d.is_current}
            if pending and current != pending.members:
                raise ValueError("stale_reconcile_plan")
            if any(not d.extra.get("source_member") for d in old):
                raise ValueError("legacy_host_requires_explicit_rebuild")
            outcomes = []
            for parsed in documents:
                identity = identity_key_for(source.path, parsed.metadata["source_member"])
                head = current.get(identity)
                child = PendingIngest(
                    source, head[0] if head else None, head[1] + 1 if head else 1, observed
                )
                result = await _ingest_one(
                    child,
                    embedder=embedder,
                    target_tokens=target_tokens,
                    overlap_tokens=overlap_tokens,
                    prefer_docling=prefer_docling,
                    session_factory=session_factory,
                    _parsed=parsed,
                    _session=session,
                )
                if result.status == "failed":
                    raise ValueError(result.detail)
                outcomes.append(result)
            absent = {d.id for d in old if d.extra.get("source_member") not in set(members)}
            removed = await delete_documents_in_session(session, sorted(absent)) if absent else None
            if fingerprint(source.path) != observed:
                raise ValueError("source_changed_before_commit")
            aggregate = hashlib.sha256(
                "\n".join(
                    sorted(
                        parsed.metadata["source_member"]
                        + ":"
                        + content_hash_for(
                            chunk_document(
                                parsed, target_tokens=target_tokens, overlap_tokens=overlap_tokens
                            )
                        )
                        for parsed in documents
                    )
                ).encode()
            ).hexdigest()
            for result in outcomes:
                doc = await session.get(Document, result.document_id)
                if doc is not None:
                    doc.extra = {
                        **doc.extra,
                        "host_members_digest": aggregate,
                        "host_member_count": len(documents),
                    }
            changed = bool(absent) or any(
                o.status == "ingested" or o.graph_changed for o in outcomes
            )
            return IngestOutcome(
                path=str(source.path),
                status="ingested" if changed else "skipped_duplicate",
                parser="mbox",
                document_id=outcomes[0].document_id if len(outcomes) == 1 else None,
                document_count=len(documents),
                chunk_count=sum(o.chunk_count for o in outcomes),
                documents_removed=removed.documents_deleted if removed else 0,
                graph_changed=changed,
                detail=f"members={len(documents)} changed={sum(o.status == 'ingested' for o in outcomes)} removed={len(absent)}",
            )
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, ParserError)
            else str(exc)
            if isinstance(exc, ValueError)
            and str(exc)
            in {
                "source_changed_since_scan",
                "source_changed_during_parse",
                "source_changed_before_commit",
                "stale_reconcile_plan",
                "legacy_host_requires_explicit_rebuild",
                "ambiguous_host_members",
            }
            else "host_ingestion_failed"
        )
        return IngestOutcome(
            path=str(source.path), status="failed", detail=code, parser="mbox", document_count=0
        )


async def _ingest_one(
    entry: CorpusEntry | PendingIngest | PendingHostIngest,
    *,
    embedder: EmbeddingProvider,
    target_tokens: int,
    overlap_tokens: int,
    prefer_docling: bool,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    _parsed: ParsedDocument | None = None,
    _session: AsyncSession | None = None,
) -> IngestOutcome:
    pending = entry if isinstance(entry, PendingIngest) else None
    entry = pending.entry if pending is not None else entry
    assert isinstance(entry, CorpusEntry)
    path_str = str(entry.path)
    try:
        observed = fingerprint(entry.path)
        if pending is not None and observed != pending.source_fingerprint:
            return IngestOutcome(path=path_str, status="failed", detail="source_changed_since_scan")
        parsed = (
            _parsed
            if _parsed is not None
            else parse_file(entry.path, prefer_docling=prefer_docling)
        )
        if fingerprint(entry.path) != observed:
            return IngestOutcome(
                path=path_str, status="failed", detail="source_changed_during_parse"
            )
    except PlaceholderFileError:
        return IngestOutcome(path=path_str, status="failed", detail="source_placeholder")
    except FileNotFoundError:
        return IngestOutcome(path=path_str, status="failed", detail="file not found")
    except ParserError as exc:
        return IngestOutcome(path=path_str, status="failed", detail=exc.code, parser=exc.parser)
    except Exception as exc:
        return IngestOutcome(
            path=path_str, status="failed", detail=f"parse_error:{type(exc).__name__}"
        )

    title = parsed.title if parsed.metadata.get("source_member") else entry.title or parsed.title
    drafts = chunk_document(parsed, target_tokens=target_tokens, overlap_tokens=overlap_tokens)
    if not drafts:
        return IngestOutcome(path=path_str, status="failed", detail="no extractable text")

    digest = content_hash_for(drafts)
    try:
        member = parsed.metadata.get("source_member", "")
        identity = identity_key_for(entry.path, member)
        async with _writer_session(session_factory, _session) as session:
            await lock_document_writes(session)
            existing = await session.scalar(
                select(Document)
                .where(Document.identity_key == identity, Document.is_current.is_(True))
                .with_for_update()
            )
            if pending is not None and (
                not pending.is_current
                or (existing.id if existing is not None else None) != pending.predecessor_id
                or pending.version_seq != (existing.version_seq + 1 if existing else 1)
            ):
                raise ValueError("stale_reconcile_plan")
            source_extra = {
                "source_fingerprint": observed.as_dict(),
                "ingest_signature": ingest_signature(
                    entry,
                    target_tokens=target_tokens,
                    overlap_tokens=overlap_tokens,
                    prefer_docling=prefer_docling,
                ),
            }
            parsed_date, date_source = document_date(parsed.metadata, observed.mtime_ns)
            unchanged = False
            if existing is not None and existing.content_hash == digest:
                stored = list(
                    (
                        await session.scalars(
                            select(Chunk)
                            .where(Chunk.document_id == existing.id)
                            .order_by(Chunk.chunk_index)
                        )
                    ).all()
                )
                unchanged = [(c.content, c.section_path, c.is_table) for c in stored] == [
                    (d.content, d.section_path, d.is_table) for d in drafts
                ]
            if unchanged and existing is not None:
                rights_changed = existing.license_class != entry.license_class
                if rights_changed:
                    await invalidate_document_graph(session, existing)
                existing.title = title
                existing.source = entry.source
                existing.source_ref = entry.url or path_str
                existing.authors = entry.authors
                existing.publication_year = entry.year
                existing.doi = entry.doi
                existing.journal = entry.journal
                existing.page_count = parsed.page_count
                existing.doc_date = parsed_date
                existing.doc_date_source = date_source
                existing.formatted_citation = build_citation(entry, title)
                existing.license_class = entry.license_class
                existing.license_source = entry.license_source or (
                    "manifest" if entry.license_class != "unknown" else None
                )
                existing.extra = {
                    **existing.extra,
                    **parsed.metadata,
                    **source_extra,
                    "authors_source": "manifest" if entry.authors else "unspecified",
                }
                if fingerprint(entry.path) != observed:
                    raise ValueError("source_changed_before_commit")
                return IngestOutcome(
                    path=path_str,
                    status="skipped_duplicate",
                    detail="unchanged content for this source identity",
                    document_id=existing.id if existing is not None else None,
                    graph_changed=rights_changed,
                    parser=parsed.metadata.get("parser", "text"),
                )

            vectors = await embedder.embed([d.content for d in drafts], task="document")
            if fingerprint(entry.path) != observed:
                raise ValueError("source_changed_during_embedding")

            if existing is not None:
                existing.is_current = False
                await session.flush()
                old_chunks = list(
                    (
                        await session.scalars(
                            select(Chunk.id).where(Chunk.document_id == existing.id)
                        )
                    ).all()
                )
                entities = list(
                    (
                        await session.scalars(
                            select(KgEntity).where(
                                or_(
                                    KgEntity.document_ids.contains([existing.id]),
                                    KgEntity.chunk_ids.overlap(old_chunks),
                                )
                            )
                        )
                    ).all()
                )
                for entity in entities:
                    entity.document_ids = [i for i in entity.document_ids if i != existing.id]
                    entity.chunk_ids = [i for i in entity.chunk_ids if i not in old_chunks]
                    entity.description = None
                    entity.aliases = []
                await session.execute(delete(KgCommunity))

            document = Document(
                title=title,
                source=entry.source,
                source_ref=entry.url or path_str,
                authors=entry.authors,
                publication_year=entry.year,
                doi=entry.doi,
                journal=entry.journal,
                formatted_citation=build_citation(entry, title),
                license_class=entry.license_class,
                license_source=entry.license_source
                or ("manifest" if entry.license_class != "unknown" else None),
                content_hash=digest,
                identity_key=identity,
                version_seq=pending.version_seq
                if pending
                else (existing.version_seq + 1 if existing is not None else 1),
                version_of=pending.predecessor_id
                if pending
                else (existing.id if existing is not None else None),
                is_current=True,
                project_id=existing.project_id
                if existing is not None and existing.project_source == "manual"
                else None,
                project_source="manual"
                if existing is not None and existing.project_source == "manual"
                else None,
                tags=list(existing.tags) if existing is not None else [],
                page_count=parsed.page_count,
                doc_date=parsed_date,
                doc_date_source=date_source,
                chunk_count=len(drafts),
                extra={
                    **parsed.metadata,
                    **source_extra,
                    "path": canonical_source_path(entry.path),
                    "source_member": member,
                    "parser": parsed.metadata.get("parser", "text"),
                    "ingested_at_utc": datetime.now(UTC).isoformat(),
                    "authors_source": "manifest" if entry.authors else "unspecified",
                    **(
                        {
                            key: existing.extra[key]
                            for key in ("project_confidence", "project_evidence")
                            if key in existing.extra
                        }
                        if existing is not None and existing.project_source == "manual"
                        else {}
                    ),
                },
            )
            session.add(document)
            await session.flush()

            for index, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
                session.add(
                    Chunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=draft.content,
                        token_count=draft.token_count,
                        section_path=draft.section_path,
                        is_table=draft.is_table,
                        embedding=vector,
                        embedding_version=embedder.version,
                    )
                )
            if fingerprint(entry.path) != observed:
                raise ValueError("source_changed_before_commit")
            from sci_rag.relate.vectors import refresh_document_embedding

            await refresh_document_embedding(session, document.id)
            document_id = document.id
    except Exception as exc:
        return IngestOutcome(
            path=path_str,
            status="failed",
            detail=(
                str(exc)
                if isinstance(exc, ValueError)
                and str(exc)
                in {
                    "source_changed_before_commit",
                    "source_changed_during_embedding",
                    "stale_reconcile_plan",
                }
                else f"{type(exc).__name__}: ingestion transaction failed"
            ),
        )

    return IngestOutcome(
        path=path_str,
        status="ingested",
        document_id=document_id,
        chunk_count=len(drafts),
        graph_changed=True,
        parser=parsed.metadata.get("parser", "text"),
    )


async def invalidate_document_graph(session: AsyncSession, document: Document) -> None:
    """Invalidate derived evidence before a source's rights change."""
    from sci_rag.db.models import KgRelationship

    chunk_ids = list(
        (await session.scalars(select(Chunk.id).where(Chunk.document_id == document.id))).all()
    )
    entities = (
        await session.scalars(
            select(KgEntity).where(
                or_(
                    KgEntity.document_ids.contains([document.id]),
                    KgEntity.chunk_ids.overlap(chunk_ids),
                )
            )
        )
    ).all()
    for entity in entities:
        entity.document_ids = [d for d in entity.document_ids if d != document.id]
        entity.chunk_ids = [c for c in entity.chunk_ids if c not in chunk_ids]
        entity.description, entity.aliases = None, []
    await session.execute(
        delete(KgRelationship).where(
            or_(KgRelationship.document_id == document.id, KgRelationship.chunk_id.in_(chunk_ids))
        )
    )
    for chunk in (
        await session.scalars(select(Chunk).where(Chunk.document_id == document.id))
    ).all():
        chunk.graph_extracted_at = None
    await session.execute(delete(KgCommunity))
