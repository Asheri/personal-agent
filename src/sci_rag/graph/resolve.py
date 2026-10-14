"""Fail-safe entity resolution with durable merge receipts.

The resolver is intentionally conservative. Exact surface-form overlap and
very high same-type string similarity are deterministic. Borderline pairs
are sent in one JSON batch to the LLM. Everything else remains separate.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

import structlog
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import EntityResolutionAudit, KgCommunity, KgEntity, KgRelationship
from sci_rag.llm import LLMClient

log = structlog.get_logger(__name__)


def normalize_entity_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


@dataclass(frozen=True)
class EntityRecord:
    id: str
    name: str
    entity_type: str
    aliases: tuple[str, ...]
    document_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class PairDecision:
    left_id: str
    right_id: str
    method: str
    confidence: float
    merge: bool
    left_name: str = ""
    right_name: str = ""
    entity_type: str = ""


@dataclass
class ResolutionReport:
    entities_considered: int = 0
    pairs_considered: int = 0
    automatic_pairs: int = 0
    ambiguous_pairs: int = 0
    llm_failures: int = 0
    planned_merges: int = 0
    merged: int = 0


def _surfaces(entity: EntityRecord) -> set[str]:
    return {
        normalized
        for value in (entity.name, *entity.aliases)
        if (normalized := normalize_entity_name(value))
    }


def classify_entity_pairs(
    entities: list[EntityRecord],
    *,
    fuzzy_threshold: float = 0.92,
    ambiguous_threshold: float = 0.80,
) -> tuple[list[PairDecision], list[PairDecision]]:
    """Split viable same-type pairs into automatic and ambiguous bands."""
    if not 0.0 <= ambiguous_threshold <= fuzzy_threshold <= 1.0:
        raise ValueError("thresholds must satisfy 0 <= ambiguous <= fuzzy <= 1")
    automatic: list[PairDecision] = []
    ambiguous: list[PairDecision] = []
    ordered = sorted(entities, key=lambda item: item.id)
    for index, left in enumerate(ordered):
        left_surfaces = _surfaces(left)
        for right in ordered[index + 1 :]:
            if left.entity_type.casefold() != right.entity_type.casefold():
                continue
            right_surfaces = _surfaces(right)
            if left_surfaces & right_surfaces:
                automatic.append(
                    PairDecision(
                        left.id,
                        right.id,
                        "alias",
                        1.0,
                        True,
                        left.name,
                        right.name,
                        left.entity_type,
                    )
                )
                continue
            score = max(
                (
                    SequenceMatcher(None, left_name, right_name).ratio()
                    for left_name in left_surfaces
                    for right_name in right_surfaces
                ),
                default=0.0,
            )
            decision = PairDecision(
                left.id,
                right.id,
                "fuzzy",
                score,
                True,
                left.name,
                right.name,
                left.entity_type,
            )
            if score >= fuzzy_threshold:
                automatic.append(decision)
            elif score >= ambiguous_threshold:
                ambiguous.append(
                    PairDecision(
                        left.id,
                        right.id,
                        "llm",
                        score,
                        False,
                        left.name,
                        right.name,
                        left.entity_type,
                    )
                )
    return automatic, ambiguous


async def resolve_ambiguous_pairs(
    pairs: list[PairDecision], llm: LLMClient
) -> tuple[list[PairDecision], int]:
    """Ask once about all borderline pairs; invalid or missing rows fail closed."""
    if not pairs:
        return [], 0
    payload = {
        "task": (
            "Decide whether each pair denotes the exact same real-world entity. "
            "Use false when uncertain. Return every pair exactly once."
        ),
        "pairs": [
            {
                "left_id": pair.left_id,
                "left_name": pair.left_name,
                "right_id": pair.right_id,
                "right_name": pair.right_name,
                "entity_type": pair.entity_type,
            }
            for pair in pairs
        ],
        "schema": {
            "decisions": [
                {
                    "left_id": "string",
                    "right_id": "string",
                    "merge": "boolean",
                    "confidence": "number from 0 to 1",
                }
            ]
        },
    }
    expected = {(pair.left_id, pair.right_id) for pair in pairs}
    try:
        response = await llm.generate_json(json.dumps(payload), max_tokens=4096)
    except Exception as exc:
        log.warning("entity_resolution_llm_failed", error=type(exc).__name__)
        return [], len(pairs)
    rows = response.get("decisions") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        return [], len(pairs)
    decisions: list[PairDecision] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        pair = (str(row.get("left_id", "")), str(row.get("right_id", "")))
        merge = row.get("merge")
        confidence = row.get("confidence")
        if (
            pair not in expected
            or pair in seen
            or not isinstance(merge, bool)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            continue
        seen.add(pair)
        decisions.append(PairDecision(pair[0], pair[1], "llm", float(confidence), merge))
    return decisions, len(expected - seen)


def _record(entity: KgEntity) -> EntityRecord:
    return EntityRecord(
        entity.id,
        entity.name,
        entity.entity_type,
        tuple(entity.aliases or []),
        tuple(entity.document_ids or []),
        tuple(entity.chunk_ids or []),
    )


def _ordered_union(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in (value for group in groups for value in group):
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


async def _apply_merges(
    session: AsyncSession,
    entities: dict[str, KgEntity],
    decisions: list[PairDecision],
) -> int:
    parent = {entity_id: entity_id for entity_id in entities}

    def find(entity_id: str) -> str:
        while parent[entity_id] != entity_id:
            parent[entity_id] = parent[parent[entity_id]]
            entity_id = parent[entity_id]
        return entity_id

    for decision in decisions:
        if not decision.merge:
            continue
        left_root = find(decision.left_id)
        right_root = find(decision.right_id)
        if left_root != right_root:
            parent[right_root] = left_root

    groups: dict[str, list[KgEntity]] = {}
    for entity_id, entity in entities.items():
        groups.setdefault(find(entity_id), []).append(entity)

    merged = 0
    affected_winner_ids: set[str] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        winner = sorted(
            group,
            key=lambda item: (
                -(len(item.document_ids or []) + len(item.chunk_ids or [])),
                item.id,
            ),
        )[0]
        affected_winner_ids.add(winner.id)
        losers = sorted((item for item in group if item.id != winner.id), key=lambda item: item.id)
        for loser in losers:
            relevant = [
                decision
                for decision in decisions
                if decision.merge and loser.id in (decision.left_id, decision.right_id)
            ]
            receipt = max(relevant, key=lambda item: item.confidence)
            winner.document_ids = _ordered_union(
                list(winner.document_ids or []), list(loser.document_ids or [])
            )
            winner.chunk_ids = _ordered_union(
                list(winner.chunk_ids or []), list(loser.chunk_ids or [])
            )
            aliases = _ordered_union(
                list(winner.aliases or []),
                [loser.name],
                list(loser.aliases or []),
            )
            winner_normalized = normalize_entity_name(winner.name)
            winner.aliases = [
                alias for alias in aliases if normalize_entity_name(alias) != winner_normalized
            ][:20]
            if not winner.description and loser.description:
                winner.description = loser.description
            loser.canonical_entity_id = winner.id
            session.add(
                EntityResolutionAudit(
                    merged_entity_id=loser.id,
                    merged_entity_name=loser.name,
                    surviving_entity_id=winner.id,
                    surviving_entity_name=winner.name,
                    method=receipt.method,
                    confidence=receipt.confidence,
                )
            )
            relationships = (
                (
                    await session.execute(
                        select(KgRelationship).where(
                            (KgRelationship.source_entity_id == loser.id)
                            | (KgRelationship.target_entity_id == loser.id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            for relationship in relationships:
                if relationship.source_entity_id == loser.id:
                    relationship.source_entity_id = winner.id
                if relationship.target_entity_id == loser.id:
                    relationship.target_entity_id = winner.id
            merged += 1

    await session.flush()
    relationships = (
        (
            await session.execute(
                select(KgRelationship)
                .where(
                    or_(
                        KgRelationship.source_entity_id.in_(affected_winner_ids),
                        KgRelationship.target_entity_id.in_(affected_winner_ids),
                    )
                )
                .order_by(KgRelationship.id)
            )
        )
        .scalars()
        .all()
    )
    seen: dict[tuple[str, str, str, str | None, str | None], KgRelationship] = {}
    for relationship in relationships:
        if relationship.source_entity_id == relationship.target_entity_id:
            await session.delete(relationship)
            continue
        key = (
            relationship.source_entity_id,
            relationship.target_entity_id,
            relationship.relation_type,
            relationship.document_id,
            relationship.chunk_id,
        )
        incumbent = seen.get(key)
        if incumbent is None:
            seen[key] = relationship
        elif relationship.confidence > incumbent.confidence:
            await session.delete(incumbent)
            seen[key] = relationship
        else:
            await session.delete(relationship)
    if merged:
        # These summaries materialize member names and graph structure, both
        # of which changed. They can be rebuilt explicitly after resolution.
        await session.execute(delete(KgCommunity))
    return merged


async def resolve_entities(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    llm: LLMClient | None = None,
    dry_run: bool = True,
    no_llm: bool = False,
    fuzzy_threshold: float = 0.92,
    ambiguous_threshold: float = 0.80,
) -> ResolutionReport:
    """Plan or apply entity merges in one transaction."""
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(KgEntity)
                    .where(KgEntity.canonical_entity_id.is_(None))
                    .order_by(KgEntity.id)
                )
            )
            .scalars()
            .all()
        )
        records = [_record(row) for row in rows]
        automatic, ambiguous = classify_entity_pairs(
            records,
            fuzzy_threshold=fuzzy_threshold,
            ambiguous_threshold=ambiguous_threshold,
        )
        report = ResolutionReport(
            entities_considered=len(rows),
            pairs_considered=len(automatic) + len(ambiguous),
            automatic_pairs=len(automatic),
            ambiguous_pairs=len(ambiguous),
        )
        llm_decisions: list[PairDecision] = []
        if ambiguous and not no_llm:
            if llm is None:
                raise ValueError("llm is required unless no_llm=True")
            llm_decisions, report.llm_failures = await resolve_ambiguous_pairs(ambiguous, llm)
        decisions = [*automatic, *llm_decisions]
        report.planned_merges = sum(1 for decision in decisions if decision.merge)
        if dry_run or not report.planned_merges:
            return report
        report.merged = await _apply_merges(session, {row.id: row for row in rows}, decisions)
        await session.commit()
    log.info(
        "entity_resolution_complete",
        merged=report.merged,
        automatic=report.automatic_pairs,
        ambiguous=report.ambiguous_pairs,
        llm_failures=report.llm_failures,
    )
    return report
