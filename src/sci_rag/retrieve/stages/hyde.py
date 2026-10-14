"""Layer 5: HyDE (hypothetical document embeddings).

Questions and answers are worded differently, which hurts plain vector
search: "how much rice straw does Colusa County produce?" does not look
like "Colusa County generated 310,000 tons of rice straw in 2022". HyDE
bridges the gap by asking a fast model to write the passage a real
document WOULD contain, embedding that passage, and searching near it.

The domain profile can steer the style per query class (an availability
question reads like a resource assessment; a properties question reads
like a characterization table). The generated passage is a search probe
only; it is never shown to anyone and never cited.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.domain import DomainProfile
from sci_rag.embed.provider import EmbeddingProvider
from sci_rag.llm import LLMClient
from sci_rag.retrieve.stages.vector import vector_stage
from sci_rag.retrieve.types import Key, RetrievalScope

log = structlog.get_logger(__name__)


async def generate_hyde_passage(llm: LLMClient, domain: DomainProfile, query: str) -> str | None:
    query_class = domain.classify_query(query)
    prompt = domain.render_prompt(
        "hyde",
        DOMAIN_NAME=domain.name,
        QUERY=query,
        CLASS_INSTRUCTION=query_class.hyde_instruction if query_class else "",
    )
    try:
        passage = await llm.generate(prompt, temperature=0.2, max_tokens=512)
    except Exception as exc:
        log.warning("hyde_generation_failed", error=type(exc).__name__)
        return None
    passage = passage.strip()
    return passage or None


async def hyde_stage(
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    embedder: EmbeddingProvider,
    domain: DomainProfile,
    query: str,
    scope: RetrievalScope,
    limit: int,
) -> list[Key]:
    passage = await generate_hyde_passage(llm, domain, query)
    if passage is None:
        return []
    [vector] = await embedder.embed([passage], task="document")
    return await vector_stage(session_factory, vector, scope, limit)
