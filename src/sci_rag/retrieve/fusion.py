"""Weighted reciprocal rank fusion (RRF).

Each retrieval layer returns an ordered candidate list. RRF turns ranks
into scores so lists with incomparable native scores (cosine distance,
ts_rank, hop counts) still combine sensibly:

    score(c) = sum over layers of  weight_layer / (k + rank_of_c_in_layer)

with rank starting at 1 and k = 60 by default. A candidate several layers
agree on beats a candidate one layer loved. The weights express trust in
each layer; the shipped defaults (vector 1.5, keyword 1.0, graph 0.8,
community 0.6, HyDE 1.2) have held up in production use, and the evaluation
harness's ablation mode is the honest way to revisit them for your corpus.
"""

from __future__ import annotations

from sci_rag.retrieve.types import FusedCandidate, Key


def rrf_fuse(
    layer_results: dict[str, list[Key]],
    *,
    weights: dict[str, float],
    k: int = 60,
    limit: int = 8,
) -> list[FusedCandidate]:
    scores: dict[Key, float] = {}
    layers_hit: dict[Key, list[str]] = {}
    for layer, keys in layer_results.items():
        weight = weights.get(layer, 1.0)
        for rank, key in enumerate(keys, start=1):
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
            layers_hit.setdefault(key, []).append(layer)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        FusedCandidate(key=key, score=score, layers=layers_hit[key])
        for key, score in ordered[:limit]
    ]
