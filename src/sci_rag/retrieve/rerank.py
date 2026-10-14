"""Post-fusion reranking: a second, sharper look at the fused pool.

Reciprocal-rank fusion is a strong first ranking, but it only sees each
layer's rank positions, never the text. A reranker reads the actual
candidate content against the query and reorders the pool. It is OFF by
default: enable it in ``domain.yaml`` only after the ablation tables
(``with_rerank`` vs ``no_rerank``) show it earns its latency on your
corpus.

Two adapters ship here, one seam for more:

* :class:`LLMReranker` (default): one JSON-mode call to the existing
  ``LLMClient`` scores every candidate; no new dependency, works with
  whatever model the kit is already configured for.
* :class:`LocalCrossEncoder` (optional ``rerank`` extra): a local
  sentence-transformers cross-encoder; no per-query API cost, needs the
  extra installed.
* GCP users can plug the Vertex AI Ranking API in by implementing the
  two-method :class:`Reranker` protocol; see ``docs/methodology.md``.

Failure discipline mirrors the retrieval stages: the orchestrator wraps
``rerank()`` in its own timeout, and any error (malformed model output,
network trouble, a missing extra) falls back to the fused order with an
honest trace status. Reranking can improve an answer; it must never be
able to lose one.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import structlog

from sci_rag.domain import DomainProfile
from sci_rag.llm import LLMClient
from sci_rag.retrieve.types import RetrievedItem

log = structlog.get_logger(__name__)

# Candidate text is truncated before prompting: the reranker judges
# relevance, and the first few hundred words carry the signal without
# blowing up latency or cost on long table chunks.
_SNIPPET_CHARS = 1200

# Used when a domain directory predates the rerank feature and has no
# prompts/rerank.md. Kept in sync with the shipped template.
_FALLBACK_PROMPT = """You are ranking search results for a scientific knowledge base.

Question:
$QUERY

Candidates (numbered):
$CANDIDATES

Score every candidate 0-10 for how directly it helps answer the question
(10 = contains the answer, 0 = unrelated). Judge only the text shown.

Return JSON only: {"scores": [{"index": <candidate number>, "score": <0-10>}, ...]}
"""


class RerankError(RuntimeError):
    """The reranker could not produce a usable ranking."""


class Reranker(Protocol):
    """Reorder retrieved items by relevance to the query."""

    name: str

    async def rerank(
        self, query: str, items: list[RetrievedItem], *, top_k: int
    ) -> list[RetrievedItem]:
        """Return ``items`` reordered, truncated to ``top_k``.

        Raise :class:`RerankError` (or anything) on failure; the
        orchestrator falls back to the fused order.
        """
        ...


def _apply_scores(
    items: list[RetrievedItem], scores: dict[int, float], top_k: int
) -> list[RetrievedItem]:
    """Scored items first (score desc, fused order for ties), then the
    unscored tail in fused order. Deterministic by construction."""
    scored = [(scores[i], i) for i in range(len(items)) if i in scores]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    ordered = [items[i] for _, i in scored]
    ordered += [items[i] for i in range(len(items)) if i not in scores]
    return ordered[:top_k]


class LLMReranker:
    """Score the pool with one JSON-mode LLM call."""

    name = "llm"

    def __init__(self, llm: LLMClient, domain: DomainProfile) -> None:
        self._llm = llm
        self._domain = domain

    def _prompt(self, query: str, items: list[RetrievedItem]) -> str:
        candidates = "\n\n".join(
            f"[{i}] {item.title}\n{item.content[:_SNIPPET_CHARS]}" for i, item in enumerate(items)
        )
        try:
            return self._domain.render_prompt("rerank", QUERY=query, CANDIDATES=candidates)
        except FileNotFoundError:
            # Older domain dirs predate prompts/rerank.md; the built-in
            # template keeps them working unchanged.
            from string import Template

            return Template(_FALLBACK_PROMPT).substitute(QUERY=query, CANDIDATES=candidates)

    async def rerank(
        self, query: str, items: list[RetrievedItem], *, top_k: int
    ) -> list[RetrievedItem]:
        if not items:
            return []
        try:
            payload = await self._llm.generate_json(self._prompt(query, items), max_tokens=2048)
        except Exception as exc:
            raise RerankError(f"rerank LLM call failed: {type(exc).__name__}: {exc}") from exc
        rows = payload.get("scores") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RerankError(f"rerank response missing 'scores' list: {payload!r}")
        scores: dict[int, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            index, score = row.get("index"), row.get("score")
            if (
                isinstance(index, int | float)
                and isinstance(score, int | float)
                and 0 <= int(index) < len(items)
            ):
                scores[int(index)] = float(score)
        return _apply_scores(items, scores, top_k)


class LocalCrossEncoder:
    """Score with a local sentence-transformers cross-encoder.

    Needs the ``rerank`` extra (``pip install 'sci-rag-kit[rerank]'``).
    The model loads lazily on first use and stays cached on the instance.
    """

    name = "local"

    DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _load(self):  # type: ignore[no-untyped-def]
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RerankError(
                    "LocalCrossEncoder needs the 'rerank' extra: pip install 'sci-rag-kit[rerank]'"
                ) from exc
            self._model = CrossEncoder(self._model_name)
        return self._model

    async def rerank(
        self, query: str, items: list[RetrievedItem], *, top_k: int
    ) -> list[RetrievedItem]:
        if not items:
            return []
        model = await asyncio.to_thread(self._load)
        pairs = [(query, item.content[:_SNIPPET_CHARS]) for item in items]
        predictions = await asyncio.to_thread(model.predict, pairs)
        scores = {i: float(p) for i, p in enumerate(predictions)}
        return _apply_scores(items, scores, top_k)


def build_reranker(
    adapter: str, *, llm: LLMClient, domain: DomainProfile, model: str | None = None
) -> Reranker:
    if adapter == "llm":
        return LLMReranker(llm, domain)
    if adapter == "local":
        return LocalCrossEncoder(model)
    raise RerankError(f"unknown reranker adapter {adapter!r} (expected 'llm' or 'local')")
