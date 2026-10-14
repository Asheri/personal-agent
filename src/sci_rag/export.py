"""Export the corpus to files you can hand to something else.

``docs/operations.md`` used to sketch this as a DuckDB one-liner. The reason
it deserves a command is the same reason retrieval has a scope: **an export is
a redistribution**. Reading rows out of Postgres by hand loses the rights
information that every other path in the kit enforces, and the copy that
leaves the database is the copy nobody re-checks.

So a scoped export is fail-closed in the same way retrieval is, and in one
place further. Documents and chunks filter through :func:`scope_conditions`,
exactly as a retrieval layer would. Entities and relationships cannot, because
they aggregate: a ``KgEntity`` carries one description written from evidence
across every document it was extracted from, so exporting it under a scope
that excludes one of those documents would leak that document's content
through the summary. The rule here is that an entity survives a scope only
when EVERY document it points at survived, and a relationship survives only
when its own document did and both endpoints did. An entity with no document
attribution at all cannot be checked, so under a scope it does not survive.

Communities are deliberately not exported. A ``KgCommunity`` summary
aggregates across documents with no per-document attribution to check, which
is the same reason the community retrieval layer disables itself under any
scope. There is nothing to filter it by, so there is no honest way to include
it here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document, KgEntity, KgRelationship
from sci_rag.retrieve.types import RetrievalScope, scope_conditions

ExportFormat = Literal["jsonl", "parquet"]

FORMATS: tuple[str, ...] = ("jsonl", "parquet")

#: The tables an export writes, in dependency order.
TABLES: tuple[str, ...] = ("documents", "chunks", "entities", "relationships")

#: Columns never exported, whatever else is asked for. ``search_tsv`` is a
#: generated tsvector: a Postgres index artifact, not corpus data, and not
#: portable to anything downstream.
ALWAYS_SKIP: dict[str, frozenset[str]] = {
    "chunks": frozenset({"search_tsv"}),
}

#: Skipped unless ``include_embeddings``. Vectors dominate the output size and
#: are rarely what a downstream consumer wants.
EMBEDDING_COLUMNS: dict[str, frozenset[str]] = {
    "chunks": frozenset({"embedding"}),
}

_MODELS = {
    "documents": Document,
    "chunks": Chunk,
    "entities": KgEntity,
    "relationships": KgRelationship,
}


class ParquetUnavailableError(RuntimeError):
    """Raised when a Parquet export is asked for without pyarrow installed."""


@dataclass
class ExportResult:
    directory: Path
    fmt: str
    counts: dict[str, int]
    files: list[Path]
    scoped: bool


def exported_columns(table: str, *, include_embeddings: bool = False) -> list[str]:
    """The column names an export writes for ``table``.

    Derived from the model rather than hand-listed, so a new column is
    exported rather than silently dropped, and pinned by a test so adding one
    is a decision somebody makes rather than a surprise in a data file.
    """
    model = _MODELS[table]
    skip = set(ALWAYS_SKIP.get(table, frozenset()))
    if not include_embeddings:
        skip |= set(EMBEDDING_COLUMNS.get(table, frozenset()))
    return [column.key for column in model.__table__.columns if column.key not in skip]


async def export_corpus(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    directory: Path,
    fmt: ExportFormat = "jsonl",
    scope: RetrievalScope | None = None,
    include_embeddings: bool = False,
) -> ExportResult:
    """Write one file per table under ``directory``.

    ``scope`` of ``None`` exports everything. Any scope at all is applied
    fail-closed, including to the graph; see the module docstring for why the
    graph needs a different rule than the rows.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; known: {', '.join(FORMATS)}")
    if fmt == "parquet":
        _require_pyarrow()

    directory.mkdir(parents=True, exist_ok=True)

    async with session_factory() as session:
        tables = await _collect(session, scope=scope, include_embeddings=include_embeddings)

    files: list[Path] = []
    counts: dict[str, int] = {}
    for table in TABLES:
        rows = tables[table]
        columns = exported_columns(table, include_embeddings=include_embeddings)
        path = directory / f"{table}.{'jsonl' if fmt == 'jsonl' else 'parquet'}"
        if fmt == "jsonl":
            _write_jsonl(path, rows)
        else:
            _write_parquet(path, rows, columns)
        files.append(path)
        counts[table] = len(rows)

    return ExportResult(
        directory=directory,
        fmt=fmt,
        counts=counts,
        files=files,
        scoped=scope is not None,
    )


async def _collect(
    session: AsyncSession,
    *,
    scope: RetrievalScope | None,
    include_embeddings: bool,
) -> dict[str, list[dict[str, Any]]]:
    conditions = scope_conditions(scope) if scope is not None else []

    doc_query = select(Document).order_by(Document.id)
    if conditions:
        doc_query = doc_query.where(*conditions)
    documents = list((await session.scalars(doc_query)).all())
    document_ids = {document.id for document in documents}

    chunk_query = select(Chunk).order_by(Chunk.document_id, Chunk.chunk_index)
    if scope is not None:
        chunk_query = chunk_query.join(Document, Chunk.document_id == Document.id)
        if conditions:
            chunk_query = chunk_query.where(*conditions)
    chunks = list((await session.scalars(chunk_query)).all())

    entities = list((await session.scalars(select(KgEntity).order_by(KgEntity.id))).all())
    relationships = list(
        (await session.scalars(select(KgRelationship).order_by(KgRelationship.id))).all()
    )

    if scope is not None:
        entities = [e for e in entities if _entity_in_scope(e, document_ids)]
        surviving = {entity.id for entity in entities}
        relationships = [
            r
            for r in relationships
            if r.document_id in document_ids
            and r.source_entity_id in surviving
            and r.target_entity_id in surviving
        ]

    return {
        "documents": [_row(d, "documents", include_embeddings) for d in documents],
        "chunks": [_row(c, "chunks", include_embeddings) for c in chunks],
        "entities": [_row(e, "entities", include_embeddings) for e in entities],
        "relationships": [_row(r, "relationships", include_embeddings) for r in relationships],
    }


def _entity_in_scope(entity: KgEntity, document_ids: set[str]) -> bool:
    """Every document behind the entity has to have survived, not just one.

    ``description`` is written from evidence across all of them, so one
    out-of-scope document is enough to make the summary unsafe to hand out.
    An entity with no attribution cannot be checked, so it does not survive.
    """
    return bool(entity.document_ids) and set(entity.document_ids) <= document_ids


def _row(instance: Any, table: str, include_embeddings: bool) -> dict[str, Any]:
    columns = exported_columns(table, include_embeddings=include_embeddings)
    return {name: _plain(getattr(instance, name)) for name in columns}


def _plain(value: Any) -> Any:
    """Make a database value JSON-safe without losing precision."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _require_pyarrow() -> Any:
    try:
        import pyarrow
    except ImportError as exc:  # pragma: no cover - exercised by a monkeypatched test
        raise ParquetUnavailableError(
            "Parquet export needs pyarrow, which is not installed. Either install it "
            "(`uv sync --extra export`) or export JSONL, which needs no extra."
        ) from exc
    return pyarrow


def _write_parquet(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Write one Parquet file, with nested JSONB flattened to a JSON string.

    ``documents.extra`` holds whatever Crossref returned, so its keys differ
    row to row. Inferring a struct from that produces a schema that changes
    with the corpus; a JSON string is one stable column a reader can parse
    when it wants to. Every other column maps directly.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    flattened = [
        {
            name: json.dumps(row[name], ensure_ascii=False)
            if isinstance(row[name], dict)
            else row[name]
            for name in columns
        }
        for row in rows
    ]
    if flattened:
        table = pa.Table.from_pylist(flattened)
    else:
        # An empty corpus still needs a file with the right columns, or a
        # downstream reader sees "no such column" rather than "no rows".
        table = pa.table({name: pa.array([], type=pa.string()) for name in columns})
    pq.write_table(table, path)
