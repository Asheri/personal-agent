"""Adaptive routing: spend the graph only where the graph pays.

The published evidence (and our own ablations) says the expensive layers
earn their keep on a MINORITY of queries: graph traversal on multi-hop
questions, community summaries on corpus-overview questions, HyDE where
a query class can shape a hypothetical passage. Routing every query
through everything is honest only in benchmarks; in service it spends
latency where it buys nothing.

``route`` maps a query to a retrieval plan with transparent, ordered
heuristics; every decision carries plain-language reasons, printable via
``sci-rag retrieve --explain-routing``. The optional LLM fallback runs
ONLY when the heuristics are genuinely ambiguous AND a client was
passed in; the default path makes no model calls and is deterministic.

The ``auto`` profile stays opt-in for v0.2. It becomes a default only
if the published ``auto_routed`` vs ``full_deep`` ablation on the
benchmark page supports it; that is the ablation-first house rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

from sci_rag.domain import DomainProfile
from sci_rag.llm import LLMClient

log = structlog.get_logger(__name__)

# Connectives that signal the answer spans more than one fact.
_MULTI_HOP_PATTERNS = (
    r"\bcompare\b",
    r"\bversus\b",
    r"\bvs\.?\b",
    r"\bdifference between\b",
    r"\btrade-?offs?\b",
    r"\brelationship between\b",
    r"\bhow does\b.+\b(affect|influence|impact|change)\b",
    r"\bwhy\b.+\b(instead of|rather than|over)\b",
    r"\bboth\b.+\band\b",
    r"\b(and|or)\b.+\b(compare[ds]?|combined|together)\b",
)

# Openers of a single-fact lookup.
_LOOKUP_PATTERNS = (
    r"^\s*what (is|are|was|were)\b",
    r"^\s*how (much|many)\b",
    r"^\s*when (is|was|does|did)\b",
    r"^\s*where (is|was|does|did)\b",
    r"^\s*which\b",
    r"^\s*who\b",
)

# The corpus-overview signals that community summaries exist for.
_OVERVIEW_PATTERNS = (
    r"\boverview\b",
    r"\bsummar(y|ize|ise)\b",
    r"\bbig picture\b",
    r"\bthemes?\b",
    r"\blandscape\b",
    r"\bstate of\b",
    r"\bmain (topics|areas|findings)\b",
    r"\bacross the (corpus|literature|documents)\b",
)

_LOOKUP_MAX_WORDS = 12


@dataclass(frozen=True)
class RoutingDecision:
    """A retrieval plan with its justification. ``profile`` is always a
    concrete profile ("interactive" or "deep"), never "auto"."""

    profile: str
    include_graph: bool
    include_community: bool
    include_hyde: bool
    matched_class: str | None = None
    ambiguous: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _matches_any(query: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, query, flags=re.IGNORECASE):
            return pattern
    return None


async def route(
    query: str, domain: DomainProfile, *, llm: LLMClient | None = None
) -> RoutingDecision:
    """Classify a query into a retrieval plan.

    Heuristic order: multi-hop cues beat lookup cues (a comparative
    question that happens to start with "what is" still needs the
    graph); overview cues add communities on top of either.
    """
    lowered = " ".join(query.lower().split())
    words = len(lowered.split())
    reasons: list[str] = []
    query_class = domain.classify_query(query)
    matched_class = query_class.name if query_class is not None else None
    if matched_class:
        reasons.append(f"matched query class '{matched_class}' (HyDE has a template for it)")

    multi_hop = _matches_any(lowered, _MULTI_HOP_PATTERNS)
    overview = _matches_any(lowered, _OVERVIEW_PATTERNS)
    lookup = _matches_any(lowered, _LOOKUP_PATTERNS)

    if multi_hop:
        reasons.append(
            "multi-hop / comparative phrasing detected; graph traversal earns its "
            "latency on questions that span facts"
        )
        return RoutingDecision(
            profile="deep",
            include_graph=True,
            include_community=bool(overview),
            include_hyde=True,
            matched_class=matched_class,
            reasons=tuple(
                reasons + (["overview phrasing also detected; communities on"] if overview else [])
            ),
        )

    if overview:
        reasons.append(
            "corpus-overview phrasing detected; community summaries are the layer "
            "built for big-picture questions"
        )
        return RoutingDecision(
            profile="deep",
            include_graph=False,
            include_community=True,
            include_hyde=bool(matched_class),
            matched_class=matched_class,
            reasons=tuple(reasons),
        )

    if lookup and words <= _LOOKUP_MAX_WORDS:
        reasons.append(
            f"single-fact lookup phrasing in a short query ({words} words); "
            "vector + keyword answer these without the deep layers"
        )
        return RoutingDecision(
            profile="interactive",
            include_graph=False,
            include_community=False,
            include_hyde=False,
            matched_class=matched_class,
            reasons=tuple(reasons),
        )

    # Nothing decisive. Ask the LLM only if the caller supplied one;
    # otherwise deep is the honest default (it can only over-retrieve).
    if llm is not None:
        try:
            payload = await llm.generate_json(
                "Classify this search query for a scientific knowledge base as "
                '{"profile": "interactive"} for a simple single-fact lookup or '
                '{"profile": "deep"} for anything needing synthesis across '
                f"documents. Query: {query!r}. Return JSON only.",
                max_tokens=64,
            )
            answer = payload.get("profile") if isinstance(payload, dict) else None
            if answer in ("interactive", "deep"):
                reasons.append(f"heuristics ambiguous; LLM fallback chose '{answer}'")
                deep = answer == "deep"
                return RoutingDecision(
                    profile=answer,
                    include_graph=deep,
                    include_community=deep,
                    include_hyde=deep,
                    matched_class=matched_class,
                    ambiguous=True,
                    reasons=tuple(reasons),
                )
        except Exception as exc:
            log.warning("router_llm_fallback_failed", error=type(exc).__name__)
            reasons.append("LLM fallback failed; defaulting to deep")

    reasons.append("no decisive routing cue; defaulting to deep (all layers)")
    return RoutingDecision(
        profile="deep",
        include_graph=True,
        include_community=True,
        include_hyde=True,
        matched_class=matched_class,
        ambiguous=True,
        reasons=tuple(reasons),
    )
