"""Bootstrap statistics for eval reports: the difference between a number
and a citable number.

Everything here is stdlib-only (``random.Random`` with an explicit seed,
so results are reproducible) and resamples at the question level, which
is the honest unit: questions are the independent draws in an eval run,
individual rank positions are not.

Two tools:

* :func:`bootstrap_ci`: a percentile bootstrap 95% CI around a mean.
* :func:`paired_bootstrap_test`: for comparing two configs on the SAME
  questions. Resamples question indices, so each resample preserves the
  pairing; reports the mean delta, its CI, and a two-sided bootstrap
  p-value. Pairing matters: on a 20-question set an unpaired comparison
  needs a huge effect to clear the noise, a paired one does not.

Small-sample honesty is the caller's job and the report writers do it:
below ``SMALL_N`` questions, every table carries a warning instead of
letting a wide interval masquerade as precision.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# Below this many questions, reports must warn that intervals are wide.
SMALL_N = 10

_DEFAULT_RESAMPLES = 2000
_DEFAULT_CONFIDENCE = 0.95


@dataclass(frozen=True)
class ConfidenceInterval:
    mean: float
    lo: float
    hi: float
    n: int

    def as_dict(self) -> dict[str, float]:
        return {"mean": self.mean, "lo": self.lo, "hi": self.hi, "n": float(self.n)}


@dataclass(frozen=True)
class PairedComparison:
    """``delta`` is mean(b) - mean(a): positive means b improved on a."""

    delta: float
    lo: float
    hi: float
    p_value: float
    n: int

    def as_dict(self) -> dict[str, float]:
        return {
            "delta": self.delta,
            "lo": self.lo,
            "hi": self.hi,
            "p_value": self.p_value,
            "n": float(self.n),
        }


def percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile on pre-sorted values.

    Public because the retrieval profiler reports latency percentiles from the
    same implementation; two percentile functions in one codebase is one too
    many.
    """
    if not sorted_values:
        raise ValueError("no values")
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def bootstrap_ci(
    values: list[float],
    *,
    n_resamples: int = _DEFAULT_RESAMPLES,
    confidence: float = _DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> ConfidenceInterval:
    """Percentile-bootstrap confidence interval around the mean."""
    if not values:
        raise ValueError("bootstrap_ci needs at least one value")
    n = len(values)
    mean = sum(values) / n
    if n == 1 or len(set(values)) == 1:
        return ConfidenceInterval(mean=mean, lo=mean, hi=mean, n=n)
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(n_resamples))
    alpha = (1 - confidence) / 2
    return ConfidenceInterval(
        mean=mean,
        lo=percentile(means, alpha),
        hi=percentile(means, 1 - alpha),
        n=n,
    )


def paired_bootstrap_test(
    a: list[float],
    b: list[float],
    *,
    n_resamples: int = _DEFAULT_RESAMPLES,
    confidence: float = _DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> PairedComparison:
    """Paired bootstrap on per-question deltas (b - a).

    The p-value is the two-sided bootstrap tail probability that the mean
    delta crosses zero; 1.0 means "no evidence of any difference".
    """
    if len(a) != len(b):
        raise ValueError(f"paired comparison needs equal lengths, got {len(a)} and {len(b)}")
    if not a:
        raise ValueError("paired comparison needs at least one pair")
    deltas = [y - x for x, y in zip(a, b, strict=True)]
    n = len(deltas)
    delta_mean = sum(deltas) / n
    if n == 1 or len(set(deltas)) == 1:
        p = 1.0 if delta_mean == 0 else 0.0
        return PairedComparison(delta=delta_mean, lo=delta_mean, hi=delta_mean, p_value=p, n=n)
    rng = random.Random(seed)
    resampled = sorted(sum(rng.choice(deltas) for _ in range(n)) / n for _ in range(n_resamples))
    alpha = (1 - confidence) / 2
    at_or_below_zero = sum(1 for value in resampled if value <= 0) / n_resamples
    at_or_above_zero = sum(1 for value in resampled if value >= 0) / n_resamples
    p_value = min(1.0, 2 * min(at_or_below_zero, at_or_above_zero))
    return PairedComparison(
        delta=delta_mean,
        lo=percentile(resampled, alpha),
        hi=percentile(resampled, 1 - alpha),
        p_value=p_value,
        n=n,
    )


def format_ci(ci_dict: dict[str, float]) -> str:
    """Render ``{"mean": .., "lo": .., "hi": ..}`` as ``0.85 [0.67, 1.00]``."""
    return f"{ci_dict['mean']:.2f} [{ci_dict['lo']:.2f}, {ci_dict['hi']:.2f}]"
