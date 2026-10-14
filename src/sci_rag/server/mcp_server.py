"""The MCP server: this knowledge base as a set of agent tools.

Agents are first-class citizens of a sci-rag deployment, not an
afterthought: Claude Code, other MCP-capable assistants, and future
multi-RAG routers all connect here. Two transports, one tool set:

* **stdio** for local agent use: ``sci-rag mcp``
* **streamable HTTP** mounted at ``/mcp`` inside the same FastAPI process,
  sharing the exact service instance the REST API uses.

Tool descriptions below are written for the agent reading them: what the
tool is for, when to reach for it, and what comes back. The eight tools
follow an inspect-then-drill pattern (search or ask first; documents,
entities, and relationships for follow-up).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server import MCPServer
from sqlalchemy import case, func, or_, select, text

import sci_rag
from sci_rag.db.models import KgEntity, KgRelationship
from sci_rag.server.service import RagService


def build_mcp_server(
    service: RagService,
) -> tuple[MCPServer, dict[str, Callable[..., Awaitable[Any]]]]:
    """Build the MCP server plus a plain dict of the tool callables.

    The dict is what tests (and any embedding host) call directly; the
    MCPServer wraps the same functions for the protocol.
    """
    mcp = MCPServer(
        "sci-rag",
        version=sci_rag.__version__,
        instructions=(
            f"A retrieval and question-answering server for this knowledge base: "
            f"{service.domain.name}. Start with answer_question for a cited answer, "
            "or search_corpus when you want raw evidence to reason over yourself. "
            "Use corpus_stats or list_sources first if you need to know whether this "
            "knowledge base covers a topic at all."
        ),
    )

    async def search_corpus(
        query: str,
        top_k: int = 5,
        deep: bool = False,
        license_classes: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        journals: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search the knowledge base and get back ranked evidence chunks.

        Use this when you want the underlying source text to reason over
        yourself. Each result carries its document title, section path,
        citation, license class, and which retrieval layers found it.
        Set deep=true for hard or multi-hop questions (slower: adds graph
        traversal, community summaries, and HyDE to the vector+keyword
        default). Restrict license_classes (e.g. ["public",
        "open_commercial"]) when you plan to redistribute what you quote.
        Narrow by publication year with year_min/year_max, or to particular
        journals, when recency or venue matters; those filters apply inside
        every layer, before ranking, and they disable the cross-document
        community summaries because a summary cannot be filtered after the
        fact.
        """
        result = await service.retrieve(
            query,
            profile="deep" if deep else "interactive",
            top_k=max(1, min(top_k, 50)),
            license_classes=license_classes,
            year_min=year_min,
            year_max=year_max,
            journals=journals,
        )
        return {
            "query": query,
            "results": [
                {
                    "kind": item.kind,
                    "chunk_id": item.id if item.kind == "chunk" else None,
                    "document_id": item.document_id,
                    "title": item.title,
                    "section": item.section_path,
                    "text": item.content,
                    "citation": item.citation,
                    "license_class": item.license_class,
                    "score": round(item.score, 4),
                    "found_by_layers": item.layers,
                }
                for item in result.items
            ],
            "degraded_stages": result.degraded_stages,
        }

    async def answer_question(
        query: str,
        top_k: int = 8,
        license_classes: list[str] | None = None,
        include_compression: bool | None = None,
    ) -> dict[str, Any]:
        """Ask the knowledge base a question and get a grounded, cited answer.

        The answer cites numbered sources inline like [1]; the citations
        list maps each number to its document. If the corpus does not
        contain the answer, the response says so rather than guessing.
        This spends LLM tokens; for raw evidence without generation, use
        search_corpus instead. Set include_compression only to override the
        domain default; the response reports measured prompt-token counts and
        any full-text fallbacks.
        """
        text_parts: list[str] = []
        citations: list[dict[str, Any]] = []
        error: dict[str, Any] | None = None
        compression: dict[str, Any] | None = None
        async for event in service.answer_stream(
            query,
            top_k=max(1, min(top_k, 20)),
            license_classes=license_classes,
            include_compression=include_compression,
        ):
            if event.type == "delta":
                text_parts.append(event.data["text"])
            elif event.type == "citations":
                citations = event.data["citations"]
            elif event.type == "error":
                error = {k: v for k, v in event.data.items() if not k.startswith("_")}
            elif event.type == "compression_done":
                compression = {k: v for k, v in event.data.items() if not k.startswith("_")}
        if error:
            return {"error": error, "query": query}
        return {
            "query": query,
            "answer": "".join(text_parts),
            "citations": [c for c in citations if c["cited"]],
            "all_sources": citations,
            "compression": compression,
        }

    async def get_document(document_id: str) -> dict[str, Any]:
        """Fetch one document's full metadata and a preview of its chunks.

        Use after search_corpus or answer_question to inspect a cited
        source: authors, year, DOI, license class, where it came from, and
        the first chunks of its text.
        """
        document, chunks = await service.get_document(document_id)
        return {
            "id": document.id,
            "title": document.title,
            "authors": document.authors or [],
            "year": document.publication_year,
            "doi": document.doi,
            "citation": document.formatted_citation,
            "source": document.source,
            "source_ref": document.source_ref,
            "license_class": document.license_class,
            "chunk_count": document.chunk_count,
            "chunks": [
                {
                    "chunk_id": chunk.id,
                    "index": chunk.chunk_index,
                    "section": chunk.section_path,
                    "is_table": chunk.is_table,
                    "preview": chunk.content[:300],
                }
                for chunk in chunks
            ],
        }

    async def search_entities(
        name_contains: str, entity_type: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """Look up knowledge-graph entities by name substring.

        Use this to check what the graph knows about a concept before
        traversing it ("rice" finds "rice straw"). Optionally filter by
        entity type; corpus_stats does not list types, but the domain's
        ontology does and unknown types simply return nothing.
        """
        limit = max(1, min(limit, 100))
        conditions = [
            KgEntity.canonical_entity_id.is_(None),
            or_(
                KgEntity.name.ilike(f"%{name_contains}%"),
                func.array_to_string(KgEntity.aliases, " ").ilike(f"%{name_contains}%"),
            ),
        ]
        if entity_type:
            conditions.append(KgEntity.entity_type == entity_type)
        async with service.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(KgEntity).where(*conditions).order_by(KgEntity.name).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return {
            "entities": [
                {
                    "name": entity.name,
                    "type": entity.entity_type,
                    "description": entity.description,
                    "evidence_chunk_count": len(entity.chunk_ids or []),
                }
                for entity in rows
            ]
        }

    async def get_citations(document_id: str) -> dict[str, Any]:
        """Inspect a document's references and the corpus documents that cite it.

        Use after get_document when following scientific provenance in either
        direction. Resolved references include corpus document titles and ids;
        unresolved Crossref DOI pointers remain visible with resolved=false.
        """
        return await service.get_citations(document_id)

    async def get_entity_relationships(entity_name: str) -> dict[str, Any]:
        """Show every stated relationship of one entity, with evidence quotes.

        Use for multi-hop reasoning: 'what converts rice straw?' becomes
        one call showing rice straw CONVERTED_BY anaerobic digestion, with
        the sentence that says so. Names are matched case-insensitively.
        """
        async with service.session_factory() as session:
            entity = (
                await session.execute(
                    select(KgEntity)
                    .where(
                        or_(
                            func.lower(KgEntity.name) == entity_name.lower(),
                            text(
                                "EXISTS (SELECT 1 FROM unnest(kg_entities.aliases) alias "
                                "WHERE lower(alias) = lower(:entity_name))"
                            ).bindparams(entity_name=entity_name),
                        )
                    )
                    .order_by(
                        case(
                            (func.lower(KgEntity.name) == entity_name.lower(), 0),
                            else_=1,
                        ),
                        KgEntity.canonical_entity_id.is_not(None),
                        KgEntity.id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if entity is None:
                return {
                    "entity": entity_name,
                    "found": False,
                    "hint": "Try search_entities to find the canonical name.",
                }
            seen_ids: set[str] = set()
            while entity.canonical_entity_id is not None:
                if entity.id in seen_ids:
                    return {
                        "entity": entity_name,
                        "found": False,
                        "hint": "Entity canonicalization cycle detected; run sci-rag doctor.",
                    }
                seen_ids.add(entity.id)
                canonical = await session.get(KgEntity, entity.canonical_entity_id)
                if canonical is None:
                    return {
                        "entity": entity_name,
                        "found": False,
                        "hint": "Canonical entity is missing; run sci-rag doctor.",
                    }
                entity = canonical
            edges = (
                (
                    await session.execute(
                        select(KgRelationship).where(
                            or_(
                                KgRelationship.source_entity_id == entity.id,
                                KgRelationship.target_entity_id == entity.id,
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            ids = {e.source_entity_id for e in edges} | {e.target_entity_id for e in edges}
            names = {
                row.id: row.name
                for row in (
                    await session.execute(select(KgEntity).where(KgEntity.id.in_(ids)))
                ).scalars()
            }
        return {
            "entity": entity.name,
            "found": True,
            "type": entity.entity_type,
            "relationships": [
                {
                    "statement": (
                        f"{names.get(edge.source_entity_id, '?')} {edge.relation_type} "
                        f"{names.get(edge.target_entity_id, '?')}"
                    ),
                    "evidence": edge.evidence,
                    "chunk_id": edge.chunk_id,
                }
                for edge in edges
            ],
        }

    async def list_sources() -> dict[str, Any]:
        """List the corpus's document sources with counts and license classes.

        Use this to learn how the operator organized their corpus (for
        example "county_reports" vs "extension_notes") before filtering a
        search by source or license.
        """
        stats = await service.stats()
        return {
            "sources": stats["sources"],
            "license_classes": stats["license_classes"],
            "note": "Pass these values to search_corpus filters.",
        }

    async def corpus_stats() -> dict[str, Any]:
        """Size and shape of this knowledge base: documents, chunks, graph
        entities, relationships, communities, and embedding versions.

        A fast first call to judge whether this knowledge base is worth
        querying for a given topic, and to detect an empty or stale corpus.
        """
        stats = await service.stats()
        return {"domain": service.domain.name, **stats}

    tools: dict[str, Callable[..., Awaitable[Any]]] = {
        "search_corpus": search_corpus,
        "answer_question": answer_question,
        "get_document": get_document,
        "get_citations": get_citations,
        "search_entities": search_entities,
        "get_entity_relationships": get_entity_relationships,
        "list_sources": list_sources,
        "corpus_stats": corpus_stats,
    }
    for tool in tools.values():
        mcp.tool()(tool)

    @mcp.resource("corpus://manifest")
    async def manifest_resource() -> str:
        """The machine-readable corpus descriptor (same as GET /v1/corpus-manifest)."""
        return json.dumps(await service.corpus_manifest(), indent=2)

    @mcp.resource("corpus://methodology")
    async def methodology_resource() -> str:
        """How retrieval works here, in one page."""
        tuning = service.domain.config.retrieval
        return (
            f"# How {service.domain.name} retrieval works\n\n"
            "Five layers run in parallel and their ranked candidates fuse by weighted "
            f"reciprocal rank (k={tuning.rrf_k}):\n\n"
            f"- vector (weight {tuning.weights.get('vector')}): dense embedding similarity\n"
            f"- keyword (weight {tuning.weights.get('keyword')}): Postgres full-text search\n"
            f"- graph (weight {tuning.weights.get('graph')}): query entities walked up to two "
            "hops through the knowledge graph, returning their evidence chunks\n"
            f"- community (weight {tuning.weights.get('community')}): summaries of graph "
            "clusters, for big-picture questions\n"
            f"- hyde (weight {tuning.weights.get('hyde')}): a hypothetical answer passage is "
            "embedded and searched for\n\n"
            "License scoping is applied inside every layer before ranking, and an empty "
            "allowlist returns nothing (fail closed). Answers cite numbered sources and "
            "refuse rather than guess when the corpus lacks the answer.\n"
        )

    return mcp, tools
