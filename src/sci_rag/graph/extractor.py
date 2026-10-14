"""Knowledge-graph extraction: chunks in, entities and relationships out.

An LLM reads batches of chunks and reports the entities and relationships
it finds, constrained to the types declared in your ``domain.yaml``. The
results are validated (unknown types and dangling relationship endpoints
are dropped, never guessed), then upserted:

* Entities are canonical by name. Seeing "rice straw" again adds evidence
  pointers to the existing entity instead of creating a duplicate.
* Relationships carry their evidence: the quoted phrase and the chunk it
  came from.

Extraction is incremental. Every processed chunk is stamped, so re-running
``sci-rag graph extract`` only touches new material, and a failed batch is
left unstamped for the next run to retry.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import Row, bindparam, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.sqltypes import Text as TextType

from sci_rag.db.models import Chunk, Document, KgEntity, KgRelationship
from sci_rag.domain import DomainProfile
from sci_rag.llm import LLMClient

log = structlog.get_logger(__name__)

_MAX_PASSAGE_CHARS = 4000
_MAX_NAME_LEN = 200
_MAX_ALIASES = 20

_ALIAS_MATCH = text(
    "EXISTS (SELECT 1 FROM unnest(kg_entities.aliases) AS alias "
    "WHERE lower(alias) = ANY(:entity_names))"
).bindparams(bindparam("entity_names", type_=ARRAY(TextType())))


@dataclass
class ExtractedEntity:
    name: str
    entity_type: str
    description: str
    passages: list[int]
    aliases: list[str] = field(default_factory=list)


@dataclass
class ExtractedRelationship:
    source: str
    target: str
    relation_type: str
    evidence: str
    passage: int
    confidence: float = 1.0


@dataclass
class ExtractionStats:
    chunks_processed: int = 0
    batches_failed: int = 0
    #: Batches whose response was unusable and which were retried smaller.
    batches_split: int = 0
    entities_created: int = 0
    entities_updated: int = 0
    relationships_created: int = 0


def parse_extraction(
    payload: Any, domain: DomainProfile, batch_size: int
) -> tuple[list[ExtractedEntity], list[ExtractedRelationship]]:
    """Validate a model response against the domain ontology.

    Anything malformed is dropped silently rather than repaired: a graph
    built from guesses is worse than a slightly sparser graph.
    """
    if not isinstance(payload, dict):
        return [], []
    entity_types = {t.lower(): t for t in domain.entity_type_names}
    relation_types = {t.lower(): t for t in domain.relation_type_names}

    entities: list[ExtractedEntity] = []
    seen_names: dict[str, ExtractedEntity] = {}
    for raw in payload.get("entities", []) or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        canonical_type = entity_types.get(str(raw.get("type", "")).strip().lower())
        if not name or len(name) > _MAX_NAME_LEN or canonical_type is None:
            continue
        passages = [
            p for p in (raw.get("passages") or []) if isinstance(p, int) and 1 <= p <= batch_size
        ]
        entity = ExtractedEntity(
            name=name,
            entity_type=canonical_type,
            description=str(raw.get("description", "")).strip()[:500],
            passages=passages,
            aliases=_parse_aliases(raw.get("aliases"), canonical_name=name),
        )
        key = name.lower()
        if key in seen_names:
            seen_names[key].passages = sorted(set(seen_names[key].passages) | set(passages))
            seen_names[key].aliases = _parse_aliases(
                [*seen_names[key].aliases, *entity.aliases],
                canonical_name=seen_names[key].name,
            )
        else:
            seen_names[key] = entity
            entities.append(entity)

    relationships: list[ExtractedRelationship] = []
    for raw in payload.get("relationships", []) or []:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source", "")).strip()
        target = str(raw.get("target", "")).strip()
        canonical_type = relation_types.get(str(raw.get("type", "")).strip().lower())
        passage = raw.get("passage")
        if (
            canonical_type is None
            or source.lower() not in seen_names
            or target.lower() not in seen_names
            or source.lower() == target.lower()
        ):
            continue
        relationships.append(
            ExtractedRelationship(
                source=source,
                target=target,
                relation_type=canonical_type,
                evidence=str(raw.get("evidence", "")).strip()[:1000],
                passage=passage if isinstance(passage, int) and 1 <= passage <= batch_size else 1,
                confidence=_parse_confidence(raw.get("confidence")),
            )
        )
    return entities, relationships


def _parse_aliases(value: Any, *, canonical_name: str) -> list[str]:
    if not isinstance(value, list):
        return []
    aliases: list[str] = []
    seen = {canonical_name.casefold()}
    for raw_alias in value:
        if not isinstance(raw_alias, str):
            continue
        alias = " ".join(raw_alias.split())
        key = alias.casefold()
        if not alias or len(alias) > _MAX_NAME_LEN or key in seen:
            continue
        seen.add(key)
        aliases.append(alias)
        if len(aliases) == _MAX_ALIASES:
            break
    return aliases


def _parse_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1.0
    confidence = float(value)
    return confidence if 0.0 <= confidence <= 1.0 else 1.0


async def extract_graph(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    domain: DomainProfile,
    batch_size: int = 10,
    reprocess_all: bool = False,
    rate_limit_s: float = 0.2,
    max_chunks: int | None = None,
) -> ExtractionStats:
    stats = ExtractionStats()
    async with session_factory() as session:
        statement = (
            select(Chunk.id, Chunk.document_id, Chunk.content)
            .join(Document, Document.id == Chunk.document_id)
            .order_by(Document.content_hash, Chunk.chunk_index)
        )
        if not reprocess_all:
            statement = statement.where(Chunk.graph_extracted_at.is_(None))
        if max_chunks:
            statement = statement.limit(max_chunks)
        pending = (await session.execute(statement)).all()

    if not pending:
        log.info("graph_extract_nothing_to_do")
        return stats

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        await _extract_with_recovery(
            batch,
            session_factory,
            llm,
            domain,
            stats,
            rate_limit_s=rate_limit_s,
        )
        if rate_limit_s and start + batch_size < len(pending):
            await asyncio.sleep(rate_limit_s)
    return stats


def _batch_id(batch: Sequence[Row[tuple[str, str, str]]]) -> str:
    """A stable, content-free name for a batch, so logs can be followed.

    Derived from the chunk ids in order, which are identifiers rather than
    text, so a batch keeps the same name while one ingestion run retries or
    splits it and nothing about the documents reaches the log. Fresh ingestion
    assigns fresh chunk ids and therefore a fresh batch name.
    """
    digest = hashlib.sha256("|".join(row[0] for row in batch).encode("utf-8"))
    return digest.hexdigest()[:12]


async def _extract_with_recovery(
    batch: Sequence[Row[tuple[str, str, str]]],
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    domain: DomainProfile,
    stats: ExtractionStats,
    *,
    rate_limit_s: float,
) -> None:
    """Extract one batch, halving it when the model's output is unusable.

    A response the parser cannot read is usually a response that did not fit:
    above some batch size the JSON exceeds the output cap and is cut off, and
    every identical retry is cut off in the same place. Reruns cannot make
    progress on that, which is what left the documented demo route stuck. A
    smaller batch asks for less JSON, so it is the retry that can work.

    Only unusable structured output is retried this way. A database or
    provider failure is not made smaller by a smaller batch, so splitting it
    would spend the same failure twice.

    The split is a deterministic halving and stops at one chunk, so recovery
    is bounded and a rerun repeats the same sequence rather than sampling.
    """
    try:
        await _extract_batch(batch, session_factory, llm, domain, stats)
        stats.chunks_processed += len(batch)
        return
    except ValueError as exc:
        if len(batch) == 1:
            stats.batches_failed += 1
            log.warning(
                "graph_extract_batch_failed",
                batch=_batch_id(batch),
                batch_size=1,
                error=type(exc).__name__,
                detail=str(exc)[:200],
            )
            return
        stats.batches_split += 1
        log.info(
            "graph_extract_batch_split",
            batch=_batch_id(batch),
            batch_size=len(batch),
            error=type(exc).__name__,
        )
    except Exception as exc:
        stats.batches_failed += 1
        log.warning(
            "graph_extract_batch_failed",
            batch=_batch_id(batch),
            batch_size=len(batch),
            error=type(exc).__name__,
            detail=str(exc)[:200],
        )
        return

    half = len(batch) // 2
    for part in (batch[:half], batch[half:]):
        await _extract_with_recovery(
            part, session_factory, llm, domain, stats, rate_limit_s=rate_limit_s
        )
        if rate_limit_s:
            await asyncio.sleep(rate_limit_s)


async def _extract_batch(
    batch: Sequence[Row[tuple[str, str, str]]],
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    domain: DomainProfile,
    stats: ExtractionStats,
) -> None:
    passages = "\n\n".join(
        f"{i}. {content[:_MAX_PASSAGE_CHARS]}" for i, (_, _, content) in enumerate(batch, start=1)
    )
    prompt = domain.render_prompt(
        "entity_extraction",
        DOMAIN_NAME=domain.name,
        ENTITY_TYPES=domain.entity_types_block(),
        RELATION_TYPES=domain.relation_types_block(),
        PASSAGES=passages,
    )
    payload = await llm.generate_json(prompt, max_tokens=8192)
    entities, relationships = parse_extraction(payload, domain, len(batch))

    chunk_id_by_passage = {i: row[0] for i, row in enumerate(batch, start=1)}
    document_id_by_passage = {i: row[1] for i, row in enumerate(batch, start=1)}
    batch_chunk_ids = [row[0] for row in batch]
    batch_document_ids = sorted({row[1] for row in batch})

    async with session_factory() as session:
        entity_ids = await _upsert_entities(
            session,
            entities,
            chunk_id_by_passage,
            document_id_by_passage,
            fallback_chunk_ids=batch_chunk_ids,
            fallback_document_ids=batch_document_ids,
            stats=stats,
        )
        await _insert_relationships(
            session, relationships, entity_ids, chunk_id_by_passage, document_id_by_passage, stats
        )
        await session.execute(
            update(Chunk)
            .where(Chunk.id.in_(batch_chunk_ids))
            .values(graph_extracted_at=datetime.now(UTC))
        )
        await session.commit()


async def _upsert_entities(
    session: AsyncSession,
    entities: list[ExtractedEntity],
    chunk_id_by_passage: dict[int, str],
    document_id_by_passage: dict[int, str],
    *,
    fallback_chunk_ids: list[str],
    fallback_document_ids: list[str],
    stats: ExtractionStats,
) -> dict[str, str]:
    """Create or enrich entities; returns lower(name) -> entity id."""
    if not entities:
        return {}
    names_lower = [e.name.lower() for e in entities]
    existing_rows = list(
        (
            await session.execute(
                select(KgEntity).where(
                    or_(func.lower(KgEntity.name).in_(names_lower), _ALIAS_MATCH)
                ),
                {"entity_names": names_lower},
            )
        )
        .scalars()
        .all()
    )
    # Alias matches can have equal priority. Resolve their candidate ordering with
    # an application-defined total semantic key rather than database collation or
    # fresh persistence UUIDs. Entity names are unique, so the raw name makes the
    # key total after its case-insensitive prefix.
    existing_rows.sort(
        key=lambda row: (
            row.name.casefold(),
            row.name,
            row.entity_type.casefold(),
            row.entity_type,
        )
    )
    existing: dict[tuple[str, str], KgEntity] = {}
    priorities: dict[tuple[str, str], int] = {}
    exact_name_rows: dict[str, KgEntity] = {}
    requested_types: dict[str, set[str]] = {}
    for entity in entities:
        requested_types.setdefault(entity.name.lower(), set()).add(entity.entity_type)
    for matched_row in existing_rows:
        canonical_row = await _follow_canonical_entity(session, matched_row)
        exact_key = matched_row.name.lower()
        if exact_key in requested_types:
            exact_name_rows.setdefault(exact_key, matched_row)
        candidates: list[tuple[str, int]] = []
        if matched_row.entity_type in requested_types.get(exact_key, set()):
            candidates.append((exact_key, 0 if matched_row.canonical_entity_id is None else 1))
        candidates.extend(
            (alias.lower(), 2 if matched_row.canonical_entity_id is None else 3)
            for alias in (matched_row.aliases or [])
            if matched_row.entity_type in requested_types.get(alias.lower(), set())
        )
        for key, priority in candidates:
            typed_key = (key, matched_row.entity_type)
            if priority < priorities.get(typed_key, 4):
                priorities[typed_key] = priority
                existing[typed_key] = canonical_row

    ids: dict[str, str] = {}
    for entity in entities:
        if entity.passages:
            chunk_ids = [chunk_id_by_passage[p] for p in entity.passages]
            document_ids = sorted({document_id_by_passage[p] for p in entity.passages})
        else:
            # The model did not say where; attribute to the whole batch.
            chunk_ids = fallback_chunk_ids
            document_ids = fallback_document_ids

        typed_name = (entity.name.lower(), entity.entity_type)
        row = existing.get(typed_name)
        if row is None:
            if entity.name.lower() in exact_name_rows:
                log.warning(
                    "entity_type_conflict",
                    existing_type=exact_name_rows[entity.name.lower()].entity_type,
                    extracted_type=entity.entity_type,
                )
                continue
            row = KgEntity(
                name=entity.name,
                entity_type=entity.entity_type,
                description=entity.description or None,
                aliases=entity.aliases,
                chunk_ids=list(dict.fromkeys(chunk_ids)),
                document_ids=list(dict.fromkeys(document_ids)),
            )
            session.add(row)
            await session.flush()
            existing[typed_name] = row
            stats.entities_created += 1
        else:
            merged_chunks = list(dict.fromkeys([*(row.chunk_ids or []), *chunk_ids]))
            merged_documents = list(dict.fromkeys([*(row.document_ids or []), *document_ids]))
            changed = merged_chunks != (row.chunk_ids or []) or merged_documents != (
                row.document_ids or []
            )
            row.chunk_ids = merged_chunks
            row.document_ids = merged_documents
            merged_aliases = _parse_aliases(
                [*(row.aliases or []), *entity.aliases], canonical_name=row.name
            )
            if merged_aliases != (row.aliases or []):
                row.aliases = merged_aliases
                changed = True
            if not row.description and entity.description:
                row.description = entity.description
                changed = True
            if changed:
                stats.entities_updated += 1
        ids[entity.name.lower()] = row.id
    return ids


async def _follow_canonical_entity(session: AsyncSession, entity: KgEntity) -> KgEntity:
    """Resolve a persisted entity id to its active survivor, failing on corruption."""
    seen: set[str] = set()
    current = entity
    while current.canonical_entity_id is not None:
        if current.id in seen:
            raise RuntimeError(f"entity canonicalization cycle at {current.id}")
        seen.add(current.id)
        canonical = await session.get(KgEntity, current.canonical_entity_id)
        if canonical is None:
            raise RuntimeError(
                f"entity {current.id} points to missing canonical entity "
                f"{current.canonical_entity_id}"
            )
        current = canonical
    return current


async def _insert_relationships(
    session: AsyncSession,
    relationships: list[ExtractedRelationship],
    entity_ids: dict[str, str],
    chunk_id_by_passage: dict[int, str],
    document_id_by_passage: dict[int, str],
    stats: ExtractionStats,
) -> None:
    relationships = [
        relationship
        for relationship in relationships
        if relationship.source.lower() in entity_ids and relationship.target.lower() in entity_ids
    ]
    if not relationships:
        return
    involved = {entity_ids[r.source.lower()] for r in relationships} | {
        entity_ids[r.target.lower()] for r in relationships
    }
    existing_rows = (
        (
            await session.execute(
                select(KgRelationship).where(KgRelationship.source_entity_id.in_(involved))
            )
        )
        .scalars()
        .all()
    )
    existing_triples: dict[tuple[str, str, str, str | None, str | None], KgRelationship] = {
        (
            row.source_entity_id,
            row.target_entity_id,
            row.relation_type,
            row.document_id,
            row.chunk_id,
        ): row
        for row in existing_rows
    }
    for relationship in relationships:
        source_id = entity_ids[relationship.source.lower()]
        target_id = entity_ids[relationship.target.lower()]
        document_id = document_id_by_passage.get(relationship.passage)
        chunk_id = chunk_id_by_passage.get(relationship.passage)
        triple = (source_id, target_id, relationship.relation_type, document_id, chunk_id)
        existing = existing_triples.get(triple)
        if existing is not None:
            if relationship.confidence > existing.confidence:
                existing.confidence = relationship.confidence
            continue
        row = KgRelationship(
            source_entity_id=source_id,
            target_entity_id=target_id,
            relation_type=relationship.relation_type,
            evidence=relationship.evidence or None,
            confidence=relationship.confidence,
            document_id=document_id,
            chunk_id=chunk_id,
        )
        existing_triples[triple] = row
        session.add(row)
        stats.relationships_created += 1
