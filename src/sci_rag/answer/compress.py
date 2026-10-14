"""Question-aware compression of retrieved chunks before answer generation.

The model output is an optimization hint, never new evidence. Valid summaries
retain the original chunk identity and citation metadata. Missing, malformed,
failed, or over-budget summaries fall back to the complete retrieved text so a
provider problem cannot silently erase evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from sci_rag.domain import DomainProfile
from sci_rag.ingest.tokens import count_tokens
from sci_rag.llm import LLMClient
from sci_rag.retrieve import RetrievedItem

log = structlog.get_logger(__name__)


class _Snippet(BaseModel):
    index: int = Field(ge=1, strict=True)
    relevance_score: float = Field(ge=0.0, le=1.0, strict=True)
    summary: str = Field(min_length=1, strict=True)


@dataclass
class CompressionResult:
    items: list[RetrievedItem]
    failure_count: int = 0
    dropped_count: int = 0


class SnippetCompressor:
    """Compress chunk text in one batched JSON call.

    Community summaries already are compressed, cross-document evidence and
    therefore pass through untouched. The compressor only has authority over
    ordinary chunks returned by retrieval.
    """

    def __init__(self, domain: DomainProfile, llm: LLMClient) -> None:
        self.domain = domain
        self.llm = llm

    async def compress(
        self,
        query: str,
        items: list[RetrievedItem],
        *,
        relevance_floor: float,
        max_tokens_per_chunk: int,
    ) -> CompressionResult:
        chunks = [
            (index, item) for index, item in enumerate(items, start=1) if item.kind == "chunk"
        ]
        if not chunks:
            return CompressionResult(items=list(items))

        try:
            prompt = self.domain.render_prompt(
                "snippet_compression",
                QUERY=query,
                MAX_TOKENS_PER_CHUNK=str(max_tokens_per_chunk),
                CHUNKS_JSON=json.dumps(
                    [{"index": index, "text": item.content} for index, item in chunks],
                    ensure_ascii=False,
                ),
            )
            payload = await self.llm.generate_json(
                prompt,
                max_tokens=min(8192, max(512, len(chunks) * max_tokens_per_chunk + 256)),
            )
        except Exception as exc:
            log.warning(
                "snippet_compression_failed",
                error=type(exc).__name__,
                chunk_count=len(chunks),
            )
            return CompressionResult(items=list(items), failure_count=len(chunks))

        snippets = _validated_snippets(payload)
        if snippets is None:
            return CompressionResult(items=list(items), failure_count=len(chunks))

        by_index: dict[int, _Snippet] = {}
        duplicate_indexes: set[int] = set()
        for snippet in snippets:
            if snippet.index in by_index:
                duplicate_indexes.add(snippet.index)
            by_index[snippet.index] = snippet

        output: list[RetrievedItem] = []
        failures = 0
        dropped = 0
        chunk_indexes = {index for index, _item in chunks}
        for index, item in enumerate(items, start=1):
            if item.kind != "chunk":
                output.append(item)
                continue
            selected = by_index.get(index)
            if (
                selected is None
                or index in duplicate_indexes
                or not selected.summary.strip()
                or count_tokens(selected.summary.strip()) > max_tokens_per_chunk
            ):
                failures += 1
                output.append(item)
            elif selected.relevance_score < relevance_floor:
                dropped += 1
            else:
                output.append(replace(item, content=selected.summary.strip()))

        unexpected = set(by_index) - chunk_indexes
        if unexpected:
            log.warning("snippet_compression_ignored_indexes", count=len(unexpected))
        return CompressionResult(items=output, failure_count=failures, dropped_count=dropped)


def _validated_snippets(payload: Any) -> list[_Snippet] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("snippets"), list):
        return None
    try:
        return [_Snippet.model_validate(value) for value in payload["snippets"]]
    except ValidationError:
        return None
