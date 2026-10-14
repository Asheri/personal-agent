"""Community detection and summaries.

Once the graph exists, clusters of tightly connected entities usually map
onto real themes in the corpus (a feedstock and its region, processes and
their products). We find those clusters, have an LLM write a short summary
of each, and embed the summaries; the community retrieval layer then
answers "big picture" questions no single chunk covers.

The clustering is deterministic label propagation: every entity starts as
its own community, then repeatedly adopts the community most of its
neighbors belong to (ties break toward the smaller label), until stable.
It is a simpler cousin of Louvain modularity optimization; for graphs of
hundreds to a few thousand entities it lands in the same place and is easy
to reason about. Rebuilding replaces all communities, so the operation is
idempotent by reconstruction.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import KgCommunity, KgEntity, KgRelationship
from sci_rag.domain import DomainProfile
from sci_rag.embed.provider import EmbeddingProvider
from sci_rag.llm import LLMClient

log = structlog.get_logger(__name__)


def detect_communities(
    nodes: list[str], edges: list[tuple[str, str]], *, max_sweeps: int = 10
) -> dict[str, list[str]]:
    """Deterministic label propagation. Returns label -> sorted member ids."""
    if not nodes:
        return {}
    ordered = sorted(nodes)
    labels: dict[str, str] = {node: node for node in ordered}
    weights: dict[str, Counter[str]] = defaultdict(Counter)
    for a, b in edges:
        if a == b or a not in labels or b not in labels:
            continue
        weights[a][b] += 1
        weights[b][a] += 1

    for _ in range(max_sweeps):
        changed = False
        for node in ordered:
            neighbor_labels: Counter[str] = Counter()
            for neighbor, weight in weights[node].items():
                neighbor_labels[labels[neighbor]] += weight
            if not neighbor_labels:
                continue
            # Highest weight wins; ties break toward the smallest label so
            # repeated runs always agree.
            best_label = min(
                (
                    label
                    for label, w in neighbor_labels.items()
                    if w == max(neighbor_labels.values())
                )
            )
            if best_label != labels[node]:
                labels[node] = best_label
                changed = True
        if not changed:
            break

    groups: dict[str, list[str]] = defaultdict(list)
    for node, label in labels.items():
        groups[label].append(node)
    return {label: sorted(members) for label, members in groups.items()}


@dataclass
class CommunityStats:
    communities_created: int = 0
    entities_clustered: int = 0
    llm_summary_failures: int = 0


async def build_communities(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    embedder: EmbeddingProvider,
    domain: DomainProfile,
    min_size: int = 3,
) -> CommunityStats:
    stats = CommunityStats()
    async with session_factory() as session:
        entities = (await session.execute(select(KgEntity))).scalars().all()
        relationships = (await session.execute(select(KgRelationship))).scalars().all()

    if not entities:
        log.info("communities_no_entities")
        return stats

    by_id = {e.id: e for e in entities}
    groups = detect_communities(
        [e.id for e in entities],
        [(r.source_entity_id, r.target_entity_id) for r in relationships],
    )
    keep = [members for members in groups.values() if len(members) >= min_size]
    keep.sort(key=lambda members: (-len(members), members[0]))

    async with session_factory() as session:
        await session.execute(delete(KgCommunity))
        for members in keep:
            community = await _build_one(
                members, by_id, relationships, llm, embedder, domain, stats
            )
            session.add(community)
            stats.communities_created += 1
            stats.entities_clustered += len(members)
        await session.commit()
    return stats


async def _build_one(
    members: list[str],
    by_id: dict[str, KgEntity],
    relationships: Sequence[KgRelationship],
    llm: LLMClient,
    embedder: EmbeddingProvider,
    domain: DomainProfile,
    stats: CommunityStats,
) -> KgCommunity:
    member_set = set(members)
    internal = [
        r
        for r in relationships
        if r.source_entity_id in member_set and r.target_entity_id in member_set
    ]
    degree: Counter[str] = Counter()
    for r in internal:
        degree[r.source_entity_id] += 1
        degree[r.target_entity_id] += 1
    ranked = sorted(members, key=lambda mid: (-degree[mid], by_id[mid].name.lower()))
    title = ", ".join(by_id[mid].name for mid in ranked[:3])

    entities_block = "\n".join(
        f"- {by_id[mid].name} ({by_id[mid].entity_type})"
        + (f": {by_id[mid].description}" if by_id[mid].description else "")
        for mid in ranked
    )
    relationships_block = (
        "\n".join(
            f"- {by_id[r.source_entity_id].name} {r.relation_type} {by_id[r.target_entity_id].name}"
            + (f' (evidence: "{r.evidence}")' if r.evidence else "")
            for r in internal
        )
        or "- (none recorded)"
    )

    summary: str | None = None
    try:
        summary = (
            await llm.generate(
                domain.render_prompt(
                    "community_summary",
                    DOMAIN_NAME=domain.name,
                    ENTITIES=entities_block,
                    RELATIONSHIPS=relationships_block,
                ),
                temperature=0.2,
                max_tokens=400,
            )
        ).strip() or None
    except Exception as exc:
        stats.llm_summary_failures += 1
        log.warning("community_summary_failed", error=type(exc).__name__)
    if not summary:
        names = ", ".join(by_id[mid].name for mid in ranked)
        summary = f"A cluster of related concepts: {names}."

    [vector] = await embedder.embed([summary], task="document")
    return KgCommunity(
        title=title,
        level=0,
        member_entity_ids=members,
        summary=summary,
        summary_embedding=vector,
        summary_embedding_version=embedder.version,
    )
