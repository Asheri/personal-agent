"""GET /v1/documents: the corpus catalog, with provenance.

Trust starts with being able to see what is in the knowledge base. The
catalog lists every document with its source, license class, and citation
metadata; the detail view previews its chunks.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from sci_rag.db.models import Chunk, Document
from sci_rag.server.auth import AuthContext, require_scopes
from sci_rag.server.schemas import (
    ChunkPreview,
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
)
from sci_rag.server.service import RagService

router = APIRouter(tags=["corpus"])


def _summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        title=document.title,
        source=document.source,
        license_class=document.license_class,
        authors=document.authors or [],
        publication_year=document.publication_year,
        doi=document.doi,
        chunk_count=document.chunk_count,
        ingested_at=document.ingested_at.isoformat(),
    )


@router.get("/v1/documents", response_model=DocumentListResponse)
async def list_documents(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, description="Case-insensitive title substring."),
    source: str | None = Query(None),
    license_class: str | None = Query(None),
    auth: AuthContext = require_scopes("corpus:read"),
) -> DocumentListResponse:
    service: RagService = request.app.state.service
    documents, total = await service.list_documents(
        page=page, page_size=page_size, search=search, source=source, license_class=license_class
    )
    return DocumentListResponse(
        documents=[_summary(d) for d in documents],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/v1/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: str,
    request: Request,
    auth: AuthContext = require_scopes("corpus:read"),
) -> DocumentDetail:
    service: RagService = request.app.state.service
    document, chunks = await service.get_document(document_id)
    return DocumentDetail(
        **_summary(document).model_dump(),
        source_ref=document.source_ref,
        formatted_citation=document.formatted_citation,
        page_count=document.page_count,
        chunks=[_preview(chunk) for chunk in chunks],
    )


def _preview(chunk: Chunk, chars: int = 240) -> ChunkPreview:
    text = chunk.content.replace("\n", " ")
    return ChunkPreview(
        id=chunk.id,
        chunk_index=chunk.chunk_index,
        section_path=chunk.section_path,
        is_table=chunk.is_table,
        preview=text[:chars] + ("..." if len(text) > chars else ""),
    )
