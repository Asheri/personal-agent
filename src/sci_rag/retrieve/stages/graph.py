"""Layer 3: knowledge-graph traversal.

The question names entities; the graph knows their neighbors; the
neighbors point back to evidence chunks. Concretely:

1. A fast LLM call extracts entity names from the question.
2. Matching graph entities are walked up to two hops in either direction.
3. The chunks those entities were extracted from re-enter the candidate
   pool, ranked by hop distance.

This is what makes multi-hop questions work ("what converts the residue
that almonds produce?"): the connecting entity brings its evidence with it
even when the question's own words never appear in that text.
"""

from __future__ import annotations

import structlog
from sqlalchemy import String, bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.sqltypes import Text as TextType

from sci_rag.db.models import Document
from sci_rag.domain import DomainProfile
from sci_rag.llm import LLMClient
from sci_rag.retrieve.types import Key, RetrievalScope, scope_conditions

log = structlog.get_logger(__name__)

MAX_HOPS = 2

_WALK_SQL = text(
    """
    WITH RECURSIVE canonical_walk(entity_id) AS (
        SELECT id
        FROM kg_entities
        WHERE (
                lower(name) = ANY(:names)
                OR (
                    :allow_aliases
                    AND EXISTS (
                        SELECT 1 FROM unnest(aliases) AS alias
                        WHERE lower(alias) = ANY(:names)
                    )
               )
           )
          AND (
                :unrestricted
                OR EXISTS (
                    SELECT 1
                    FROM unnest(chunk_ids) AS entity_chunk_id
                    JOIN chunks seed_chunk ON seed_chunk.id = entity_chunk_id
                    WHERE seed_chunk.document_id = ANY(:eligible_document_ids)
                      AND btrim(regexp_replace(
                            lower(kg_entities.name), '[^[:alnum:]]+', ' ', 'g'
                          )) <> ''
                      AND position(
                            ' ' || btrim(regexp_replace(
                                lower(kg_entities.name), '[^[:alnum:]]+', ' ', 'g'
                            )) || ' '
                            IN
                            ' ' || btrim(regexp_replace(
                                lower(seed_chunk.content), '[^[:alnum:]]+', ' ', 'g'
                            )) || ' '
                          ) > 0
                )
          )
        UNION
        SELECT e.canonical_entity_id
        FROM kg_entities e
        JOIN canonical_walk c ON c.entity_id = e.id
        WHERE e.canonical_entity_id IS NOT NULL
    ), matched(entity_id) AS (
        SELECT c.entity_id
        FROM canonical_walk c
        JOIN kg_entities e ON e.id = c.entity_id
        WHERE e.canonical_entity_id IS NULL
    ), walk(entity_id, hop, path_confidence) AS (
        SELECT entity_id, 0, 1.0::double precision FROM matched
        UNION
        SELECT CASE WHEN r.source_entity_id = w.entity_id
                    THEN r.target_entity_id ELSE r.source_entity_id END,
               w.hop + 1,
               LEAST(w.path_confidence, r.confidence)
        FROM kg_relationships r
        JOIN walk w ON w.entity_id IN (r.source_entity_id, r.target_entity_id)
        WHERE w.hop < :max_hops
          AND r.confidence >= :min_confidence
          AND (
                :unrestricted
                OR r.document_id = ANY(:eligible_document_ids)
                OR (
                    r.document_id IS NULL
                    AND r.chunk_id IN (
                        SELECT edge_chunk.id
                        FROM chunks edge_chunk
                        WHERE edge_chunk.document_id = ANY(:eligible_document_ids)
                    )
                )
          )
    ), entity_candidates AS (
        SELECT candidate_chunk.id,
               candidate_chunk.document_id,
               MIN(w.hop) AS hop,
               MAX(w.path_confidence) AS path_confidence
        FROM walk w
        JOIN kg_entities e ON e.id = w.entity_id AND e.canonical_entity_id IS NULL
        CROSS JOIN LATERAL unnest(e.chunk_ids) AS entity_chunk_id
        JOIN chunks candidate_chunk ON candidate_chunk.id = entity_chunk_id
        WHERE :unrestricted OR candidate_chunk.document_id = ANY(:eligible_document_ids)
        GROUP BY candidate_chunk.id, candidate_chunk.document_id
    ), candidate_documents AS (
        SELECT document_id, MIN(hop) AS hop, MAX(path_confidence) AS path_confidence
        FROM entity_candidates
        GROUP BY document_id
    ), citation_documents AS (
        SELECT dc.cited_document_id AS document_id,
               source.hop + 1 AS hop,
               source.path_confidence
        FROM candidate_documents source
        JOIN document_citations dc ON dc.citing_document_id = source.document_id
        WHERE :include_citations
          AND dc.cited_document_id IS NOT NULL
          AND (:unrestricted OR dc.cited_document_id = ANY(:eligible_document_ids))
        UNION ALL
        SELECT dc.citing_document_id AS document_id,
               source.hop + 1 AS hop,
               source.path_confidence
        FROM candidate_documents source
        JOIN document_citations dc ON dc.cited_document_id = source.document_id
        WHERE :include_citations
          AND (:unrestricted OR dc.citing_document_id = ANY(:eligible_document_ids))
    ), citation_candidates AS (
        SELECT citation_chunk.id,
               MIN(citation_document.hop) AS hop,
               MAX(citation_document.path_confidence) AS path_confidence
        FROM citation_documents citation_document
        JOIN chunks citation_chunk ON citation_chunk.document_id = citation_document.document_id
        WHERE :unrestricted OR citation_chunk.document_id = ANY(:eligible_document_ids)
        GROUP BY citation_chunk.id
    ), combined_candidates AS (
        SELECT id, hop, path_confidence FROM entity_candidates
        UNION ALL
        SELECT id, hop, path_confidence FROM citation_candidates
    ), candidates AS (
        SELECT id, MIN(hop) AS hop, MAX(path_confidence) AS path_confidence
        FROM combined_candidates
        GROUP BY id
    )
    SELECT candidates.id, candidates.hop
    FROM candidates
    JOIN chunks ranked_chunk ON ranked_chunk.id = candidates.id
    JOIN documents ranked_document ON ranked_document.id = ranked_chunk.document_id
    ORDER BY CASE WHEN :confidence_weighted
                  THEN candidates.path_confidence END DESC NULLS LAST,
             candidates.hop,
             ranked_document.content_hash,
             ranked_chunk.chunk_index
    LIMIT :limit
    """
).bindparams(
    bindparam("names", type_=ARRAY(TextType())),
    bindparam("eligible_document_ids", type_=ARRAY(String())),
)


async def extract_query_entities(llm: LLMClient, domain: DomainProfile, query: str) -> list[str]:
    prompt = domain.render_prompt(
        "query_entities",
        DOMAIN_NAME=domain.name,
        QUERY=query,
        ENTITY_TYPES=domain.entity_types_block(),
    )
    try:
        payload = await llm.generate_json(prompt, max_tokens=512)
    except Exception as exc:
        log.warning("query_entity_extraction_failed", error=type(exc).__name__)
        return []
    entities = payload.get("entities", []) if isinstance(payload, dict) else []
    return [str(name).strip() for name in entities if str(name).strip()][:15]


async def graph_stage(
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    domain: DomainProfile,
    query: str,
    scope: RetrievalScope,
    limit: int,
    *,
    min_confidence: float = 0.0,
    confidence_weighted: bool = False,
    include_citations: bool = False,
) -> list[Key]:
    names = await extract_query_entities(llm, domain, query)
    if not names:
        return []
    lowered = sorted({name.lower() for name in names})

    async with session_factory() as session:
        unrestricted = scope.is_unrestricted()
        eligible_document_ids: list[str] = []
        if not unrestricted:
            eligible_document_ids = list(
                (
                    await session.execute(select(Document.id).where(*scope_conditions(scope)))
                ).scalars()
            )
            if not eligible_document_ids:
                return []
        rows = (
            await session.execute(
                _WALK_SQL,
                {
                    "names": lowered,
                    "max_hops": MAX_HOPS,
                    "min_confidence": min_confidence,
                    "confidence_weighted": confidence_weighted,
                    "include_citations": include_citations,
                    # Restricted callers seed only exact names proven in
                    # eligible chunk content; aliases lack per-surface provenance.
                    "allow_aliases": unrestricted,
                    "unrestricted": unrestricted,
                    "eligible_document_ids": eligible_document_ids,
                    "limit": limit,
                },
            )
        ).all()
    return [("chunk", chunk_id) for chunk_id, _hop in rows]
