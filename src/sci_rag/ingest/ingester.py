"""Ingestion: files in, embedded chunks out.

For each corpus entry: parse, chunk, deduplicate, embed, store, all inside
one transaction per document so a failure never leaves half a document
behind. Re-running ingestion over the same files is a no-op; content
identity is a SHA-256 over the chunked text, enforced by a unique
constraint in the database as the concurrency backstop.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sci_rag.db import Chunk, Document, session_scope
from sci_rag.embed.provider import EmbeddingProvider
from sci_rag.ingest.chunker import ChunkDraft, chunk_document
from sci_rag.ingest.manifest import CorpusEntry
from sci_rag.ingest.parsers import parse_file

log = structlog.get_logger(__name__)


@dataclass
class IngestOutcome:
    path: str
    status: str  # "ingested" | "skipped_duplicate" | "failed"
    detail: str = ""
    document_id: str | None = None
    chunk_count: int = 0


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
    entries: list[CorpusEntry],
    *,
    embedder: EmbeddingProvider,
    target_tokens: int = 800,
    overlap_tokens: int = 150,
    prefer_docling: bool = True,
) -> IngestReport:
    report = IngestReport()
    for entry in entries:
        outcome = await _ingest_one(
            entry,
            embedder=embedder,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            prefer_docling=prefer_docling,
        )
        report.outcomes.append(outcome)
        log.info(
            "ingest_outcome",
            path=outcome.path,
            status=outcome.status,
            chunks=outcome.chunk_count,
            detail=outcome.detail or None,
        )
    return report


async def _ingest_one(
    entry: CorpusEntry,
    *,
    embedder: EmbeddingProvider,
    target_tokens: int,
    overlap_tokens: int,
    prefer_docling: bool,
) -> IngestOutcome:
    path_str = str(entry.path)
    try:
        parsed = parse_file(entry.path, prefer_docling=prefer_docling)
    except FileNotFoundError:
        return IngestOutcome(path=path_str, status="failed", detail="file not found")
    except Exception as exc:
        return IngestOutcome(path=path_str, status="failed", detail=f"parse error: {exc}")

    title = entry.title or parsed.title
    drafts = chunk_document(parsed, target_tokens=target_tokens, overlap_tokens=overlap_tokens)
    if not drafts:
        return IngestOutcome(path=path_str, status="failed", detail="no extractable text")

    digest = content_hash_for(drafts)
    try:
        async with session_scope() as session:
            existing = await session.scalar(
                select(Document.id).where(Document.content_hash == digest)
            )
            if existing:
                return IngestOutcome(
                    path=path_str,
                    status="skipped_duplicate",
                    detail=f"same content as document {existing}",
                    document_id=existing,
                )

            vectors = await embedder.embed([d.content for d in drafts], task="document")

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
                page_count=parsed.page_count,
                chunk_count=len(drafts),
                extra={
                    "parser": parsed.metadata.get("parser", "text"),
                    "ingested_at_utc": datetime.now(UTC).isoformat(),
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
            document_id = document.id
    except IntegrityError:
        # Another process ingested the same content between our check and our
        # commit; the unique constraint on content_hash is the backstop.
        return IngestOutcome(
            path=path_str, status="skipped_duplicate", detail="concurrent duplicate"
        )
    except Exception as exc:
        return IngestOutcome(path=path_str, status="failed", detail=f"{type(exc).__name__}: {exc}")

    return IngestOutcome(
        path=path_str,
        status="ingested",
        document_id=document_id,
        chunk_count=len(drafts),
    )
