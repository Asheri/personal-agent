"""Statistics for citable eval numbers: bootstrap CIs and paired tests.

Everything is stdlib-only and deterministic under a seed, because an eval
harness whose numbers wobble between runs of the same data cannot be
trusted in a methods section.
"""

from __future__ import annotations

import pytest

from sci_rag.evals.retrieval_eval import (
    AblationConfig,
    QuestionRetrievalRecord,
    RetrievalEvalResult,
)
from sci_rag.evals.stats import bootstrap_ci, paired_bootstrap_test


class TestBootstrapCI:
    def test_deterministic_under_seed(self) -> None:
        values = [0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
        a = bootstrap_ci(values, seed=7)
        b = bootstrap_ci(values, seed=7)
        assert (a.mean, a.lo, a.hi) == (b.mean, b.lo, b.hi)

    def test_different_seeds_still_bracket_mean(self) -> None:
        values = [0.2, 0.4, 0.6, 0.8, 1.0, 0.0, 0.5, 0.7]
        ci = bootstrap_ci(values, seed=1)
        assert ci.lo <= ci.mean <= ci.hi
        assert ci.mean == pytest.approx(sum(values) / len(values))
        assert ci.n == len(values)

    def test_single_value_degenerates_cleanly(self) -> None:
        ci = bootstrap_ci([0.75], seed=3)
        assert ci.mean == ci.lo == ci.hi == 0.75
        assert ci.n == 1

    def test_all_equal_values_zero_width(self) -> None:
        ci = bootstrap_ci([1.0] * 12, seed=5)
        assert ci.lo == ci.hi == ci.mean == 1.0

    def test_empty_values_rejected(self) -> None:
        with pytest.raises(ValueError):
            bootstrap_ci([], seed=1)


class TestPairedBootstrap:
    def test_identical_inputs_show_zero_delta(self) -> None:
        a = [0.5, 0.7, 0.9, 0.4, 0.6]
        cmp = paired_bootstrap_test(a, list(a), seed=2)
        assert cmp.delta == pytest.approx(0.0)
        assert cmp.p_value == pytest.approx(1.0)

    def test_clear_improvement_detected(self) -> None:
        a = [0.1, 0.2, 0.15, 0.1, 0.2, 0.12, 0.18, 0.14, 0.16, 0.11]
        b = [v + 0.5 for v in a]
        cmp = paired_bootstrap_test(a, b, seed=2)
        assert cmp.delta == pytest.approx(0.5)
        assert cmp.p_value < 0.05
        assert cmp.lo > 0

    def test_mismatched_lengths_rejected(self) -> None:
        with pytest.raises(ValueError):
            paired_bootstrap_test([1.0, 2.0], [1.0], seed=1)

    def test_deterministic_under_seed(self) -> None:
        a = [0.1, 0.5, 0.3, 0.7]
        b = [0.2, 0.4, 0.5, 0.6]
        first = paired_bootstrap_test(a, b, seed=9)
        second = paired_bootstrap_test(a, b, seed=9)
        assert (first.delta, first.lo, first.hi, first.p_value) == (
            second.delta,
            second.lo,
            second.hi,
            second.p_value,
        )


def make_result(ranks: list[int | None]) -> RetrievalEvalResult:
    records = [
        QuestionRetrievalRecord(
            question_id=f"q{i}",
            first_relevant_rank=rank,
            hit_at_5=rank is not None and rank <= 5,
            hit_at_10=rank is not None and rank <= 10,
            retrieved=10,
            degraded_stages=[],
            relevant_ranks=[rank] if rank is not None else [],
        )
        for i, rank in enumerate(ranks)
    ]
    return RetrievalEvalResult(config=AblationConfig("test", "test config"), records=records)


class TestMetricsWithCI:
    def test_means_match_plain_metrics(self) -> None:
        result = make_result([1, 3, None, 2, 1, None])
        plain = result.metrics
        with_ci = result.metrics_with_ci
        for key in ("hit_at_5", "hit_at_10", "mrr", "ndcg_at_10"):
            assert with_ci[key]["mean"] == pytest.approx(plain[key])
            assert with_ci[key]["lo"] <= with_ci[key]["mean"] <= with_ci[key]["hi"]
        assert with_ci["n"] == 6

    def test_empty_records_safe(self) -> None:
        result = make_result([])
        assert result.metrics_with_ci["n"] == 0
