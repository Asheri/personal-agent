"""Grounded answer generation with inline citations.

The contract with users: every claim in an answer is backed by a numbered
source the reader can check, and when the corpus does not contain the
answer, the answer says so instead of improvising. The prompt enforces it,
and the evaluation harness's blind judge checks it after the fact.

Both entry points share the same preparation (retrieve, build the numbered
source block, render the domain's answer prompt):

* :meth:`AnswerEngine.answer` returns the complete result.
* :meth:`AnswerEngine.answer_stream` yields typed events (retrieval
  progress, text deltas, citations, done) that the REST SSE endpoint and
  MCP tools translate directly.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import structlog

from sci_rag.config import Settings, get_settings
from sci_rag.domain import DomainProfile
from sci_rag.ingest.tokens import count_tokens
from sci_rag.llm import LLMClient, get_llm, settings_with_llm_api_key
from sci_rag.retrieve import RetrievalResult, RetrievalScope, Retriever

from .compress import SnippetCompressor

log = structlog.get_logger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass
class SourceCitation:
    index: int
    kind: str  # "chunk" | "community"
    title: str
    citation: str | None
    license_class: str
    document_id: str | None
    chunk_id: str | None
    section_path: str | None
    cited: bool = False


@dataclass
class AnswerEvent:
    type: str  # retrieval_started | retrieval_done | compression_done | generation_started | delta | citations | done | error
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnswerResult:
    text: str
    sources: list[SourceCitation]
    retrieval: RetrievalResult
    model: str
    prompt_retrieval: RetrievalResult | None = None
    prompt_tokens_before: int = 0
    prompt_tokens_after: int = 0
    compression_failure_count: int = 0
    compression_dropped_count: int = 0

    @property
    def cited_sources(self) -> list[SourceCitation]:
        return [s for s in self.sources if s.cited]


class AnswerEngine:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        retriever: Retriever | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = retriever or Retriever(settings=self.settings)
        self.domain: DomainProfile = self.retriever.domain
        self._llm = llm

    def _resolve_llm(self, api_key_override: str | None = None) -> LLMClient:
        if api_key_override:
            # Bring-your-own-key: a per-request client that is never stored.
            provider = self.settings.model_spec_for("answer").provider
            provider_settings = settings_with_llm_api_key(
                self.settings,
                provider,
                api_key_override,
            )
            return get_llm(provider_settings)
        if self._llm is None:
            self._llm = get_llm(self.settings)
        return self._llm

    async def answer(
        self,
        query: str,
        *,
        profile: str = "deep",
        limit: int = 8,
        scope: RetrievalScope | None = None,
        api_key_override: str | None = None,
        max_tokens: int = 2048,
        include_compression: bool | None = None,
    ) -> AnswerResult:
        events = self.answer_stream(
            query,
            profile=profile,
            limit=limit,
            scope=scope,
            api_key_override=api_key_override,
            max_tokens=max_tokens,
            include_compression=include_compression,
        )
        text_parts: list[str] = []
        sources: list[SourceCitation] = []
        retrieval: RetrievalResult | None = None
        prompt_retrieval: RetrievalResult | None = None
        model = str(self.settings.model_spec_for("answer"))
        prompt_tokens_before = 0
        prompt_tokens_after = 0
        compression_failure_count = 0
        compression_dropped_count = 0
        async for event in events:
            if event.type == "delta":
                text_parts.append(event.data["text"])
            elif event.type == "retrieval_done":
                retrieval = event.data["_result"]
            elif event.type == "generation_started":
                model = event.data["model"]
            elif event.type == "compression_done":
                prompt_retrieval = event.data["_result"]
                prompt_tokens_before = event.data["prompt_tokens_before"]
                prompt_tokens_after = event.data["prompt_tokens_after"]
                compression_failure_count = event.data["failure_count"]
                compression_dropped_count = event.data["dropped_count"]
            elif event.type == "citations":
                sources = event.data["_sources"]
            elif event.type == "error":
                raise RuntimeError(event.data.get("message", "answer generation failed"))
        assert retrieval is not None
        if prompt_retrieval is None:
            prompt_retrieval = retrieval
        return AnswerResult(
            text="".join(text_parts),
            sources=sources,
            retrieval=retrieval,
            model=model,
            prompt_retrieval=prompt_retrieval,
            prompt_tokens_before=prompt_tokens_before,
            prompt_tokens_after=prompt_tokens_after,
            compression_failure_count=compression_failure_count,
            compression_dropped_count=compression_dropped_count,
        )

    async def answer_stream(
        self,
        query: str,
        *,
        profile: str = "deep",
        limit: int = 8,
        scope: RetrievalScope | None = None,
        api_key_override: str | None = None,
        max_tokens: int = 2048,
        include_compression: bool | None = None,
    ) -> AsyncIterator[AnswerEvent]:
        yield AnswerEvent(type="retrieval_started", data={"profile": profile})
        if scope is None:
            scope = RetrievalScope(exclude_retracted=True)
        retrieval = await self.retriever.retrieve(query, profile=profile, limit=limit, scope=scope)
        yield AnswerEvent(
            type="retrieval_done",
            data={
                "item_count": len(retrieval.items),
                "degraded_stages": retrieval.degraded_stages,
                "traces": [
                    {
                        "stage": t.stage,
                        "status": t.status,
                        "duration_ms": t.duration_ms,
                        "candidates": t.candidate_count,
                    }
                    for t in retrieval.traces
                ],
                "_result": retrieval,
            },
        )

        if not retrieval.items:
            # An empty corpus and a corpus nobody could reach are opposite
            # findings, and they used to read identically. On a live provider
            # slower than the stage budget every candidate-producing stage
            # times out, and reporting that as "no material" tells a reader
            # their knowledge base is empty when it is fine.
            timed_out = sorted(t.stage for t in retrieval.traces if t.status == "timeout")
            if timed_out:
                text = (
                    f"Retrieval timed out before any evidence was collected "
                    f"({', '.join(timed_out)}), so I cannot give a grounded answer. "
                    "This is not a statement about the corpus. Raise "
                    "SCI_RAG_PROVIDER_CALL_TIMEOUT_S if a provider call is slow, or "
                    "SCI_RAG_DEEP_STAGE_TIMEOUT_S if the database stage is."
                )
                yield AnswerEvent(type="delta", data={"text": text})
                yield AnswerEvent(type="citations", data={"citations": [], "_sources": []})
                yield AnswerEvent(
                    type="done",
                    data={"finish_reason": "retrieval_timeout", "timed_out_stages": timed_out},
                )
                return
            text = (
                "The knowledge base has no material matching this question within "
                "the allowed scope, so I cannot give a grounded answer."
            )
            yield AnswerEvent(type="delta", data={"text": text})
            yield AnswerEvent(type="citations", data={"citations": [], "_sources": []})
            yield AnswerEvent(type="done", data={"finish_reason": "no_sources"})
            return

        try:
            llm = self._resolve_llm(api_key_override)
        except Exception as exc:
            yield AnswerEvent(type="error", data={"code": "llm_unavailable", "message": str(exc)})
            return

        raw_prompt = self._render_answer_prompt(query, retrieval)
        prompt_retrieval = retrieval
        failures = 0
        dropped = 0
        compression_on = (
            include_compression
            if include_compression is not None
            else self.domain.config.compression.enabled
        )
        if compression_on:
            tuning = self.domain.config.compression
            compressed = await SnippetCompressor(self.domain, llm).compress(
                query,
                retrieval.items,
                relevance_floor=tuning.relevance_floor,
                max_tokens_per_chunk=tuning.max_tokens_per_chunk,
            )
            prompt_retrieval = RetrievalResult(
                items=compressed.items,
                traces=retrieval.traces,
                profile=retrieval.profile,
            )
            failures = compressed.failure_count
            dropped = compressed.dropped_count

        prompt = self._render_answer_prompt(query, prompt_retrieval)
        prompt_tokens_before = count_tokens(raw_prompt)
        prompt_tokens_after = count_tokens(prompt)
        yield AnswerEvent(
            type="compression_done",
            data={
                "enabled": compression_on,
                "source_count_before": len(retrieval.items),
                "source_count_after": len(prompt_retrieval.items),
                "failure_count": failures,
                "dropped_count": dropped,
                "prompt_tokens_before": prompt_tokens_before,
                "prompt_tokens_after": prompt_tokens_after,
                "_result": prompt_retrieval,
            },
        )

        if not prompt_retrieval.items:
            text = (
                "The retrieved material did not contain evidence relevant enough "
                "to this question, so I cannot give a grounded answer."
            )
            yield AnswerEvent(type="delta", data={"text": text})
            yield AnswerEvent(type="citations", data={"citations": [], "_sources": []})
            yield AnswerEvent(type="done", data={"finish_reason": "no_relevant_sources"})
            return

        sources = [
            SourceCitation(
                index=i,
                kind=item.kind,
                title=item.title,
                citation=item.citation,
                license_class=item.license_class,
                document_id=item.document_id,
                chunk_id=item.id if item.kind == "chunk" else None,
                section_path=item.section_path,
            )
            for i, item in enumerate(prompt_retrieval.items, start=1)
        ]
        model = llm.describe()
        yield AnswerEvent(type="generation_started", data={"model": model})

        collected: list[str] = []
        try:
            async for delta in llm.stream(prompt, max_tokens=max_tokens):
                collected.append(delta)
                yield AnswerEvent(type="delta", data={"text": delta})
        except Exception as exc:
            # Full detail goes to the server log; the client gets the class
            # name only, since provider exception text can echo request
            # internals.
            log.warning("answer_generation_failed", error=type(exc).__name__, detail=str(exc)[:500])
            yield AnswerEvent(
                type="error",
                data={
                    "code": "generation_failed",
                    "message": f"{type(exc).__name__}: generation failed (see server logs)",
                },
            )
            return

        text = "".join(collected)
        cited_indices = {int(m) for m in _CITATION_RE.findall(text)}
        for source in sources:
            source.cited = source.index in cited_indices
        yield AnswerEvent(
            type="citations",
            data={
                "citations": [
                    {
                        "index": s.index,
                        "kind": s.kind,
                        "title": s.title,
                        "citation": s.citation,
                        "license_class": s.license_class,
                        "document_id": s.document_id,
                        "chunk_id": s.chunk_id,
                        "section_path": s.section_path,
                        "cited": s.cited,
                    }
                    for s in sources
                ],
                "_sources": sources,
            },
        )
        yield AnswerEvent(type="done", data={"finish_reason": "stop"})

    def _render_answer_prompt(self, query: str, retrieval: RetrievalResult) -> str:
        return self.domain.render_prompt(
            "answer",
            DOMAIN_NAME=self.domain.name,
            QUERY=query,
            SOURCES=format_sources(retrieval),
        )


def format_sources(retrieval: RetrievalResult) -> str:
    """The numbered source block shown to the answer model (and to the blind
    grounding judge, which must see exactly what the assistant saw)."""
    blocks: list[str] = []
    for i, item in enumerate(retrieval.items, start=1):
        header = f"[{i}] {item.title}"
        if item.section_path:
            header += f" ({item.section_path})"
        if item.kind == "community":
            header += " [knowledge graph overview]"
        if item.citation:
            header += f"\nCitation: {item.citation}"
        blocks.append(f"{header}\n{item.content}")
    return "\n\n---\n\n".join(blocks)
