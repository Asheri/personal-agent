"""PRISMA-aligned counts derived from explicit screening decisions.

The report remains derivable from per-work decisions instead of accepting
operator-supplied totals. This keeps the flow diagram honest after an
interrupted model run or a later human override.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class ScreeningDisposition(Protocol):
    @property
    def doi(self) -> str: ...

    @property
    def decision(self) -> str: ...

    @property
    def reason(self) -> str: ...


@dataclass(frozen=True)
class PrismaCounts:
    identified: int
    duplicates_removed: int
    screened: int
    excluded: int
    excluded_by_reason: dict[str, int]
    included: int
    awaiting_review: int

    def reconciles(self, *, discovered_total: int) -> bool:
        """Return whether every deduplicated work has one disposition."""
        return (
            self.identified - self.duplicates_removed == discovered_total
            and self.screened == discovered_total
            and self.included + self.excluded + self.awaiting_review == self.screened
            and sum(self.excluded_by_reason.values()) == self.excluded
        )


def build_prisma_counts(
    decisions: Sequence[ScreeningDisposition],
    *,
    discovered_total: int,
    duplicates_removed: int = 0,
) -> PrismaCounts:
    """Count one current decision per discovered DOI and verify reconciliation."""
    if discovered_total < 0:
        raise ValueError("discovered_total must not be negative")
    if duplicates_removed < 0:
        raise ValueError("duplicates_removed must not be negative")
    if len(decisions) != discovered_total:
        raise ValueError(
            "screening decisions do not cover the discovered campaign: "
            f"{len(decisions)} decisions for {discovered_total} works"
        )
    dois = [decision.doi for decision in decisions]
    if len(set(dois)) != len(dois):
        raise ValueError("screening decisions contain duplicate DOIs")

    dispositions = Counter(decision.decision for decision in decisions)
    unknown = set(dispositions) - {"include", "exclude", "review"}
    if unknown:
        raise ValueError(f"unknown screening dispositions: {sorted(unknown)}")
    excluded_reasons = Counter(
        decision.reason for decision in decisions if decision.decision == "exclude"
    )
    counts = PrismaCounts(
        identified=discovered_total + duplicates_removed,
        duplicates_removed=duplicates_removed,
        screened=discovered_total,
        excluded=dispositions["exclude"],
        excluded_by_reason=dict(sorted(excluded_reasons.items())),
        included=dispositions["include"],
        awaiting_review=dispositions["review"],
    )
    if not counts.reconciles(discovered_total=discovered_total):
        raise ValueError("PRISMA counts do not reconcile against the discovered campaign")
    return counts
