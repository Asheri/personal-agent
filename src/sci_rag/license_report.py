"""The corpus's rights posture, counted.

License classes already gate retrieval: every layer applies the caller's
allowlist inside its own SQL, and ``unknown`` is never included unless asked
for by name. What was missing is the view from outside that machinery: how
much of the corpus is actually reachable under a restriction, and which
documents are quietly sitting in ``unknown`` because nobody recorded their
rights.

Two decisions shape the numbers here.

Every class in the vocabulary is reported, including the ones at zero. A table
that omits ``restricted`` because the corpus has none reads as "not checked"
rather than "none", and those are different claims about a rights audit.

Documents and chunks are both counted, because they answer different
questions. Rights are declared per document but retrieval returns chunks, so a
corpus that is 20% restricted by document can be 60% restricted by the material
an answer would actually draw on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document
from sci_rag.licensing import EXTERNAL_SAFE_CLASSES, LICENSE_CLASSES, UNKNOWN_CLASS


@dataclass
class ClassCount:
    """One row of the posture table."""

    license_class: str
    documents: int
    chunks: int
    document_share: float
    chunk_share: float

    @property
    def external_safe(self) -> bool:
        """Safe on a surface you do not fully control, per the taxonomy."""
        return self.license_class in EXTERNAL_SAFE_CLASSES


@dataclass
class UndeclaredDocument:
    """A document nobody has recorded rights for."""

    id: str
    title: str
    source: str


@dataclass
class LicenseReport:
    total_documents: int = 0
    total_chunks: int = 0
    by_class: list[ClassCount] = field(default_factory=list)
    undeclared: list[UndeclaredDocument] = field(default_factory=list)
    undeclared_by_source: dict[str, int] = field(default_factory=dict)

    @property
    def undeclared_count(self) -> int:
        return len(self.undeclared)

    @property
    def external_safe_documents(self) -> int:
        return sum(row.documents for row in self.by_class if row.external_safe)

    @property
    def external_safe_share(self) -> float:
        return _share(self.external_safe_documents, self.total_documents)

    @property
    def clean(self) -> bool:
        """True when every document has a rights decision on it."""
        return self.undeclared_count == 0


def _share(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


async def build_license_report(
    session_factory: async_sessionmaker[AsyncSession],
) -> LicenseReport:
    """Count the corpus by license class, and name what is still undeclared."""
    async with session_factory() as session:
        document_rows = (
            await session.execute(
                select(Document.license_class, func.count(Document.id)).group_by(
                    Document.license_class
                )
            )
        ).all()
        chunk_rows = (
            await session.execute(
                select(Document.license_class, func.count(Chunk.id))
                .join(Document, Chunk.document_id == Document.id)
                .group_by(Document.license_class)
            )
        ).all()
        undeclared_rows = (
            await session.execute(
                select(Document.id, Document.title, Document.source)
                .where(Document.license_class == UNKNOWN_CLASS)
                .order_by(Document.source, Document.title)
            )
        ).all()

    documents: dict[str, int] = {row[0]: row[1] for row in document_rows}
    chunks: dict[str, int] = {row[0]: row[1] for row in chunk_rows}
    total_documents = sum(documents.values())
    total_chunks = sum(chunks.values())

    report = LicenseReport(total_documents=total_documents, total_chunks=total_chunks)
    # Every class, in taxonomy order, including the empty ones. A missing row
    # reads as "not checked"; a zero reads as "none", and only one is true.
    for license_class in LICENSE_CLASSES:
        document_count = documents.get(license_class, 0)
        chunk_count = chunks.get(license_class, 0)
        report.by_class.append(
            ClassCount(
                license_class=license_class,
                documents=document_count,
                chunks=chunk_count,
                document_share=_share(document_count, total_documents),
                chunk_share=_share(chunk_count, total_chunks),
            )
        )

    # A class outside the taxonomy should be impossible: the manifest loader
    # normalizes on the way in. If one is in the database anyway, saying so is
    # better than a table whose percentages quietly fail to add up.
    for license_class, document_count in sorted(documents.items()):
        if license_class not in LICENSE_CLASSES:
            report.by_class.append(
                ClassCount(
                    license_class=license_class,
                    documents=document_count,
                    chunks=chunks.get(license_class, 0),
                    document_share=_share(document_count, total_documents),
                    chunk_share=_share(chunks.get(license_class, 0), total_chunks),
                )
            )

    report.undeclared = [
        UndeclaredDocument(id=row.id, title=row.title, source=row.source) for row in undeclared_rows
    ]
    for document in report.undeclared:
        report.undeclared_by_source[document.source] = (
            report.undeclared_by_source.get(document.source, 0) + 1
        )
    return report


def report_payload(report: LicenseReport) -> dict[str, Any]:
    """The ``--json`` shape: everything the table shows, and nothing elided."""
    return {
        "total_documents": report.total_documents,
        "total_chunks": report.total_chunks,
        "external_safe": {
            "classes": list(EXTERNAL_SAFE_CLASSES),
            "documents": report.external_safe_documents,
            "document_share": report.external_safe_share,
        },
        "by_class": [
            {
                "license_class": row.license_class,
                "documents": row.documents,
                "chunks": row.chunks,
                "document_share": row.document_share,
                "chunk_share": row.chunk_share,
                "external_safe": row.external_safe,
            }
            for row in report.by_class
        ],
        "undeclared": {
            "count": report.undeclared_count,
            "by_source": report.undeclared_by_source,
            "documents": [
                {"id": document.id, "title": document.title, "source": document.source}
                for document in report.undeclared
            ],
        },
    }


__all__ = [
    "ClassCount",
    "LicenseReport",
    "UndeclaredDocument",
    "build_license_report",
    "report_payload",
]
