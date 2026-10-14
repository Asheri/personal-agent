"""Where retrieval time actually goes, per profile and per stage.

Every request already carries the measurements: each stage records its own
duration in a :class:`~sci_rag.retrieve.types.StageTrace`. This replays a
question set against each profile and aggregates those traces, so nothing new
is instrumented and the numbers are the same ones a single traced request
prints.

Two things about the numbers are easy to misread, so both are reported rather
than left to the reader.

**Stage durations do not sum to the request.** The orchestrator runs the
candidate generators concurrently, so a request is roughly as slow as its
slowest stage, not as slow as their total. Wall-clock per request is measured
separately and reported beside the stages; a stage table without it invites
exactly the wrong arithmetic.

**The query-embedding cache is disabled while profiling.** Interactive requests
normally cache query embeddings in process memory, so replaying one question N
times would measure the cache on runs 2..N and produce a p50 that no real user
ever sees. Every run here is cold, which makes profiles comparable to each
other at the cost of being slightly pessimistic about a warm interactive path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sci_rag.evals.stats import percentile

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sci_rag.evals.seeds import SeedQuestion
    from sci_rag.retrieve.retriever import Retriever

#: The profiles a user can actually ask for. ``auto`` resolves to one of the
#: other two per question, which is the thing worth measuring about it.
PROFILES: tuple[str, ...] = ("interactive", "deep", "auto")

#: Statuses that mean "this stage did not run", as opposed to "it ran and
#: something went wrong". A stage the profile switches off contributes no
#: timing sample and is not a degradation: `interactive` disables graph,
#: community, and HyDE by definition, and an unconfigured reranker is a
#: choice. Counting those as failures buries the ones that are.
NOT_RUN_STATUSES: frozenset[str] = frozenset({"disabled", "skipped"})

#: Statuses that mean the stage ran and produced a usable result. `empty` is
#: one of them: finding nothing is an answer, not a fault.
HEALTHY_STATUSES: frozenset[str] = frozenset({"success", "empty"})


@dataclass
class StageTiming:
    """One stage's latency distribution across every run of one profile."""

    stage: str
    samples: list[float] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)

    @property
    def runs(self) -> int:
        return sum(self.statuses.values())

    @property
    def p50(self) -> float:
        return percentile(sorted(self.samples), 0.50) if self.samples else 0.0

    @property
    def p95(self) -> float:
        return percentile(sorted(self.samples), 0.95) if self.samples else 0.0

    @property
    def degraded(self) -> int:
        """Runs where the stage ran and failed. A fast stage that errored is not fast.

        A stage the profile switched off is not counted: `interactive` disables
        graph, community, and HyDE on purpose, and reporting that as a failure
        on every run would bury the timeouts that matter.
        """
        return sum(
            count
            for status, count in self.statuses.items()
            if status not in HEALTHY_STATUSES and status not in NOT_RUN_STATUSES
        )

    @property
    def ran(self) -> int:
        """Runs where the stage was actually asked to do something."""
        return sum(
            count for status, count in self.statuses.items() if status not in NOT_RUN_STATUSES
        )


@dataclass
class ProfileTiming:
    """Everything measured for one profile."""

    profile: str
    wall_clock: list[float] = field(default_factory=list)
    stages: dict[str, StageTiming] = field(default_factory=dict)
    resolved: dict[str, int] = field(default_factory=dict)

    @property
    def runs(self) -> int:
        return len(self.wall_clock)

    @property
    def p50(self) -> float:
        return percentile(sorted(self.wall_clock), 0.50) if self.wall_clock else 0.0

    @property
    def p95(self) -> float:
        return percentile(sorted(self.wall_clock), 0.95) if self.wall_clock else 0.0

    def ordered_stages(self) -> list[StageTiming]:
        """Slowest first at p95, which is the order somebody optimizing reads in."""
        return sorted(self.stages.values(), key=lambda stage: stage.p95, reverse=True)

    @property
    def slowest(self) -> StageTiming | None:
        ordered = [stage for stage in self.ordered_stages() if stage.samples]
        return ordered[0] if ordered else None


@dataclass
class ProfileReport:
    questions: int = 0
    runs_per_question: int = 0
    profiles: list[ProfileTiming] = field(default_factory=list)

    def by_name(self, profile: str) -> ProfileTiming | None:
        return next((timing for timing in self.profiles if timing.profile == profile), None)


async def profile_retrieval(
    retriever: Retriever,
    questions: list[SeedQuestion],
    *,
    runs: int = 3,
    limit: int = 8,
    profiles: tuple[str, ...] = PROFILES,
) -> ProfileReport:
    """Replay every question ``runs`` times against each profile."""
    if runs < 1:
        raise ValueError("runs must be at least 1")

    report = ProfileReport(questions=len(questions), runs_per_question=runs)
    for profile in profiles:
        timing = ProfileTiming(profile=profile)
        for question in questions:
            for _ in range(runs):
                start = time.monotonic()
                result = await retriever.retrieve(
                    question.question,
                    profile=profile,
                    limit=limit,
                    # Cold every time: see the module docstring.
                    use_query_cache=False,
                )
                timing.wall_clock.append((time.monotonic() - start) * 1000)
                timing.resolved[result.profile] = timing.resolved.get(result.profile, 0) + 1
                for trace in result.traces:
                    stage = timing.stages.setdefault(trace.stage, StageTiming(stage=trace.stage))
                    stage.statuses[trace.status] = stage.statuses.get(trace.status, 0) + 1
                    # A stage that never ran took no time and is not a sample;
                    # counting its zero would drag every percentile down.
                    if trace.status not in NOT_RUN_STATUSES:
                        stage.samples.append(float(trace.duration_ms))
        report.profiles.append(timing)
    return report


def verdict(report: ProfileReport) -> list[str]:
    """The one-line-per-finding summary: where the time goes, and what moved it."""
    lines: list[str] = []
    for timing in report.profiles:
        if not timing.runs:
            continue
        slowest = timing.slowest
        where = (
            f"slowest stage {slowest.stage} at {slowest.p95:.0f} ms p95"
            if slowest
            else "no stage reported a duration"
        )
        lines.append(f"{timing.profile}: {timing.p95:.0f} ms p95 per request, {where}.")

    interactive = report.by_name("interactive")
    deep = report.by_name("deep")
    if interactive and deep and interactive.runs and deep.runs:
        delta = deep.p95 - interactive.p95
        if delta > 0:
            lines.append(
                f"deep costs {delta:.0f} ms p95 over interactive, which is what its extra "
                "stages (graph, community, HyDE) buy."
            )
        else:
            # Real on a small corpus, and worth saying rather than printing a
            # negative "cost": the extra stages return nothing and return it fast.
            lines.append(
                f"deep is {abs(delta):.0f} ms p95 FASTER than interactive here, which means "
                "its extra stages are returning nothing quickly rather than adding value. "
                "Check their status column before reading anything into the difference."
            )

    auto = report.by_name("auto")
    if auto and auto.runs and auto.resolved:
        picked = ", ".join(f"{name} {count}" for name, count in sorted(auto.resolved.items()))
        lines.append(f"auto routed to: {picked}. Router overhead is its own row above.")

    for timing in report.profiles:
        rerank = timing.stages.get("rerank")
        if rerank and rerank.samples:
            lines.append(
                f"{timing.profile}: the reranker adds {rerank.p95:.0f} ms p95. Compare that "
                "against its ablation row in docs/benchmarks.md before keeping it on."
            )
        degraded = [stage for stage in timing.stages.values() if stage.degraded]
        if degraded:
            detail = ", ".join(
                f"{stage.stage} ({stage.degraded}/{stage.ran})" for stage in degraded
            )
            lines.append(
                f"Warning: {timing.profile} had stages that did not succeed on every run: "
                f"{detail}. A stage that timed out is fast for the wrong reason."
            )
    return lines


def report_payload(report: ProfileReport) -> dict[str, Any]:
    return {
        "questions": report.questions,
        "runs_per_question": report.runs_per_question,
        "query_cache": "disabled while profiling",
        "profiles": [
            {
                "profile": timing.profile,
                "runs": timing.runs,
                "wall_clock_ms": {"p50": round(timing.p50, 1), "p95": round(timing.p95, 1)},
                "resolved_to": timing.resolved,
                "stages": [
                    {
                        "stage": stage.stage,
                        "p50_ms": round(stage.p50, 1),
                        "p95_ms": round(stage.p95, 1),
                        "runs": stage.runs,
                        "ran": stage.ran,
                        "degraded": stage.degraded,
                        "statuses": stage.statuses,
                    }
                    for stage in timing.ordered_stages()
                ],
            }
            for timing in report.profiles
        ],
    }


__all__ = [
    "HEALTHY_STATUSES",
    "NOT_RUN_STATUSES",
    "PROFILES",
    "ProfileReport",
    "ProfileTiming",
    "StageTiming",
    "profile_retrieval",
    "report_payload",
    "verdict",
]
