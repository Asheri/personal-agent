"""Retrieval evaluation: does the right evidence come back, and which
layers earn their keep?

Relevance is judged at the evidence level, mechanically and transparently:
a retrieved item counts as relevant to a question if it comes from one of
the question's reference documents, or its text contains one of the
question's distinctive evidence phrases (whitespace- and case-normalized).
That is a deliberate, honest granularity for retrieval; grading the
quality of generated ANSWERS is the blind judge's job, never substring
matching.

The ablation configs re-run the same questions with layers switched off,
which is the only honest way to know what the graph, HyDE, or community
layers actually contribute on YOUR corpus before touching any fusion
weight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from sci_rag.evals.seeds import SeedQuestion
from sci_rag.retrieve import RetrievalScope, RetrievedItem, Retriever


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def ndcg_at_k(relevant_ranks: list[int], *, k: int) -> float:
    """nDCG@k with binary gains, judged over the retrieved list.

    ``relevant_ranks`` are the 1-based positions of relevant items in the
    retrieved ranking. The ideal ordering puts those same items at the
    top, so the metric compares the achieved ordering against the best
    ordering OF WHAT WAS RETRIEVED. That makes it a relative comparator
    across ablation configs, not an absolute recall claim: the mechanical
    relevance judgments cannot know about relevant documents that were
    never retrieved at all.
    """
    if not relevant_ranks:
        return 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks if 1 <= rank <= k)
    # The ideal ranking packs every relevant retrieved item (up to k) at
    # the top, including ones the achieved ranking left below the cutoff.
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant_ranks), k)))
    return dcg / ideal if ideal else 0.0


def is_relevant(item: RetrievedItem, question: SeedQuestion) -> bool:
    if item.title and any(
        _normalize(item.title) == _normalize(title) for title in question.reference_titles
    ):
        return True
    content = _normalize(item.content)
    return any(
        len(phrase.strip()) >= 3 and _normalize(phrase) in content
        for phrase in question.evidence_phrases
    )


@dataclass
class AblationConfig:
    name: str
    description: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    scope: RetrievalScope | None = None


RESOLVED_ENTITIES_CONFIG = AblationConfig(
    "resolved_entities",
    "Deep retrieval on an audited post-resolution corpus snapshot",
    {"profile": "deep"},
)


DEFAULT_ABLATIONS: list[AblationConfig] = [
    AblationConfig("full_deep", "All five layers (deep profile)", {"profile": "deep"}),
    AblationConfig(
        "interactive",
        "Vector + keyword only, as interactive callers see it",
        {"profile": "interactive"},
    ),
    AblationConfig(
        "vector_only",
        "Dense vectors alone",
        {
            "profile": "deep",
            "include_keyword": False,
            "include_graph": False,
            "include_community": False,
            "include_hyde": False,
        },
    ),
    AblationConfig(
        "keyword_only",
        "Full-text search alone",
        {
            "profile": "deep",
            "include_vector": False,
            "include_graph": False,
            "include_community": False,
            "include_hyde": False,
        },
    ),
    AblationConfig(
        "no_graph", "Deep without graph traversal", {"profile": "deep", "include_graph": False}
    ),
    AblationConfig(
        "confidence_weighted",
        "Deep with graph candidates ordered by minimum path confidence",
        {"profile": "deep", "graph_confidence_weighted": True},
    ),
    AblationConfig(
        "with_citations",
        "Deep with one-hop corpus citation expansion inside the graph stage",
        {"profile": "deep", "graph_include_citations": True},
    ),
    AblationConfig("no_hyde", "Deep without HyDE", {"profile": "deep", "include_hyde": False}),
    AblationConfig(
        "no_community",
        "Deep without community summaries",
        {"profile": "deep", "include_community": False},
    ),
    AblationConfig(
        "with_rerank",
        "Deep plus the post-fusion reranker",
        {"profile": "deep", "include_rerank": True},
    ),
    AblationConfig(
        "no_rerank",
        "Deep with the reranker explicitly off (paired control for with_rerank)",
        {"profile": "deep", "include_rerank": False},
    ),
    AblationConfig(
        "auto_routed",
        "Adaptive routing picks the profile and layers per query",
        {"profile": "auto"},
    ),
    AblationConfig(
        "no_retracted",
        "Deep retrieval excluding documents known to be retracted",
        {"profile": "deep"},
        scope=RetrievalScope(exclude_retracted=True),
    ),
]


@dataclass
class QuestionRetrievalRecord:
    question_id: str
    first_relevant_rank: int | None
    hit_at_5: bool
    hit_at_10: bool
    retrieved: int
    degraded_stages: list[str]
    # 1-based positions of every relevant item in the ranking (drives nDCG).
    relevant_ranks: list[int] = field(default_factory=list)


@dataclass
class RetrievalEvalResult:
    config: AblationConfig
    records: list[QuestionRetrievalRecord]

    @property
    def metrics(self) -> dict[str, float]:
        n = len(self.records)
        if n == 0:
            return {"n": 0.0, "hit_at_5": 0.0, "hit_at_10": 0.0, "mrr": 0.0, "ndcg_at_10": 0.0}
        return {
            "n": float(n),
            "hit_at_5": sum(r.hit_at_5 for r in self.records) / n,
            "hit_at_10": sum(r.hit_at_10 for r in self.records) / n,
            "mrr": sum(1.0 / r.first_relevant_rank for r in self.records if r.first_relevant_rank)
            / n,
            "ndcg_at_10": sum(ndcg_at_k(r.relevant_ranks, k=10) for r in self.records) / n,
        }

    def per_question_values(self) -> dict[str, list[float]]:
        """Per-question metric values, the resampling unit for bootstrap CIs."""
        return {
            "hit_at_5": [1.0 if r.hit_at_5 else 0.0 for r in self.records],
            "hit_at_10": [1.0 if r.hit_at_10 else 0.0 for r in self.records],
            "mrr": [
                1.0 / r.first_relevant_rank if r.first_relevant_rank else 0.0 for r in self.records
            ],
            "ndcg_at_10": [ndcg_at_k(r.relevant_ranks, k=10) for r in self.records],
        }

    @property
    def metrics_with_ci(self) -> dict[str, Any]:
        """Each metric as {mean, lo, hi} (bootstrap 95% CI) plus n."""
        from sci_rag.evals.stats import bootstrap_ci

        n = len(self.records)
        out: dict[str, Any] = {"n": n}
        if n == 0:
            return out
        for name, values in self.per_question_values().items():
            out[name] = bootstrap_ci(values).as_dict()
        return out


async def run_retrieval_eval(
    retriever: Retriever,
    questions: list[SeedQuestion],
    *,
    configs: list[AblationConfig] | None = None,
    limit: int = 10,
    scope: RetrievalScope | None = None,
) -> list[RetrievalEvalResult]:
    configs = configs or [DEFAULT_ABLATIONS[0]]
    answerable = [q for q in questions if q.answerable]
    results: list[RetrievalEvalResult] = []
    for config in configs:
        records: list[QuestionRetrievalRecord] = []
        for question in answerable:
            effective_scope = config.scope if config.scope is not None else scope
            result = await retriever.retrieve(
                question.question, limit=limit, scope=effective_scope, **config.kwargs
            )
            relevant_ranks = [
                rank
                for rank, item in enumerate(result.items, start=1)
                if is_relevant(item, question)
            ]
            first_rank = relevant_ranks[0] if relevant_ranks else None
            records.append(
                QuestionRetrievalRecord(
                    question_id=question.id,
                    first_relevant_rank=first_rank,
                    hit_at_5=first_rank is not None and first_rank <= 5,
                    hit_at_10=first_rank is not None and first_rank <= 10,
                    retrieved=len(result.items),
                    degraded_stages=result.degraded_stages,
                    relevant_ranks=relevant_ranks,
                )
            )
        results.append(RetrievalEvalResult(config=config, records=records))
    return results
