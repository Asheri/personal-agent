"""Aggregating stage traces into a latency profile.

The arithmetic is easy; what it counts is not. Two distinctions carry the
whole value of the output. A stage the profile switched off did not fail, so
counting it as a degradation on every run buries the stage that actually timed
out. And a stage that never ran contributed no time, so folding its zero into
the samples would drag every percentile toward zero and make the slowest stage
look fast.
"""

from __future__ import annotations

import pytest

from sci_rag.retrieve.profiler import (
    ProfileReport,
    ProfileTiming,
    StageTiming,
    profile_retrieval,
    report_payload,
    verdict,
)
from sci_rag.retrieve.types import RetrievalResult, StageTrace


class _StubRetriever:
    """Replays a scripted trace set, so the aggregation is what is under test."""

    def __init__(
        self, per_profile: dict[str, list[StageTrace]], resolves: dict[str, str] | None = None
    ) -> None:
        self.per_profile = per_profile
        self.resolves = resolves or {}
        self.calls: list[dict] = []

    async def retrieve(self, query, *, profile="deep", limit=8, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"query": query, "profile": profile, **kwargs})
        return RetrievalResult(
            items=[],
            traces=list(self.per_profile.get(profile, [])),
            profile=self.resolves.get(profile, profile),
        )


class _Question:
    def __init__(self, question: str) -> None:
        self.question = question


def _traces(**stages: tuple[str, int]) -> list[StageTrace]:
    return [
        StageTrace(stage=name, status=status, duration_ms=duration)
        for name, (status, duration) in stages.items()
    ]


# --- percentiles -------------------------------------------------------------


def test_percentiles_come_from_the_samples() -> None:
    stage = StageTiming(stage="vector", samples=[float(v) for v in range(1, 101)])
    stage.statuses = {"success": 100}

    assert stage.p50 == pytest.approx(50.5)
    assert stage.p95 == pytest.approx(95.05, abs=0.1)


def test_a_stage_with_no_samples_reports_zero_rather_than_raising() -> None:
    stage = StageTiming(stage="rerank", statuses={"disabled": 5})

    assert stage.p50 == 0.0
    assert stage.p95 == 0.0
    assert stage.samples == []


# --- what counts as a failure ------------------------------------------------


def test_a_disabled_stage_is_not_a_degradation() -> None:
    """`interactive` switches graph off by definition; that is not a fault."""
    stage = StageTiming(stage="graph", statuses={"disabled": 10})

    assert stage.degraded == 0
    assert stage.ran == 0


def test_an_empty_stage_is_not_a_degradation() -> None:
    """Finding nothing is an answer."""
    stage = StageTiming(stage="keyword", statuses={"empty": 7, "success": 3})

    assert stage.degraded == 0
    assert stage.ran == 10


def test_a_timeout_or_error_is_a_degradation() -> None:
    stage = StageTiming(stage="hyde", statuses={"success": 6, "timeout": 3, "error": 1})

    assert stage.degraded == 4
    assert stage.ran == 10


def test_the_degraded_denominator_excludes_runs_the_stage_sat_out() -> None:
    """`auto` disables a stage for some questions; those are not failures to divide by."""
    stage = StageTiming(stage="graph", statuses={"disabled": 2, "error": 18})

    assert (stage.degraded, stage.ran) == (18, 18)


# --- aggregation -------------------------------------------------------------


async def test_every_question_is_replayed_against_every_profile() -> None:
    retriever = _StubRetriever({})
    questions = [_Question("a"), _Question("b")]

    report = await profile_retrieval(retriever, questions, runs=3)  # type: ignore[arg-type]

    assert report.questions == 2
    assert report.runs_per_question == 3
    assert len(retriever.calls) == 2 * 3 * 3  # questions x runs x profiles
    assert {timing.profile for timing in report.profiles} == {"interactive", "deep", "auto"}
    assert all(timing.runs == 6 for timing in report.profiles)


async def test_profiling_runs_cold_so_the_replays_are_comparable() -> None:
    """Otherwise runs 2..N measure the query-embedding cache, not retrieval."""
    retriever = _StubRetriever({})

    await profile_retrieval(retriever, [_Question("a")], runs=2)  # type: ignore[arg-type]

    assert retriever.calls, "the stub should have been called"
    assert all(call["use_query_cache"] is False for call in retriever.calls)


async def test_a_stage_that_never_ran_contributes_no_sample() -> None:
    """Folding its zero in would drag every percentile toward zero."""
    retriever = _StubRetriever({"deep": _traces(vector=("success", 40), rerank=("disabled", 0))})

    report = await profile_retrieval(
        retriever,  # type: ignore[arg-type]
        [_Question("a")],
        runs=4,
        profiles=("deep",),
    )
    deep = report.by_name("deep")
    assert deep is not None

    assert deep.stages["vector"].samples == [40.0] * 4
    assert deep.stages["rerank"].samples == []
    assert deep.stages["rerank"].statuses == {"disabled": 4}


async def test_the_slowest_stage_is_the_slowest_one_that_actually_ran() -> None:
    retriever = _StubRetriever(
        {
            "deep": _traces(
                vector=("success", 10),
                graph=("success", 90),
                rerank=("disabled", 0),
            )
        }
    )

    report = await profile_retrieval(
        retriever,  # type: ignore[arg-type]
        [_Question("a")],
        runs=2,
        profiles=("deep",),
    )
    deep = report.by_name("deep")
    assert deep is not None

    assert deep.slowest is not None
    assert deep.slowest.stage == "graph"
    assert [stage.stage for stage in deep.ordered_stages()][:2] == ["graph", "vector"]


async def test_auto_records_what_it_resolved_to() -> None:
    """The interesting fact about `auto` is which profile it picked, per question."""
    retriever = _StubRetriever({"auto": _traces(router=("success", 1))}, resolves={"auto": "deep"})

    report = await profile_retrieval(
        retriever,  # type: ignore[arg-type]
        [_Question("a")],
        runs=3,
        profiles=("auto",),
    )
    auto = report.by_name("auto")
    assert auto is not None

    assert auto.resolved == {"deep": 3}


async def test_zero_runs_is_rejected_rather_than_producing_an_empty_report() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await profile_retrieval(_StubRetriever({}), [_Question("a")], runs=0)  # type: ignore[arg-type]


# --- the verdict -------------------------------------------------------------


def _timing(profile: str, wall: list[float], stages: dict[str, StageTiming]) -> ProfileTiming:
    timing = ProfileTiming(profile=profile)
    timing.wall_clock = wall
    timing.stages = stages
    return timing


def test_the_verdict_names_the_slowest_stage_per_profile() -> None:
    report = ProfileReport(questions=1, runs_per_question=1)
    report.profiles = [
        _timing(
            "deep",
            [100.0],
            {"graph": StageTiming("graph", samples=[80.0], statuses={"success": 1})},
        )
    ]

    lines = verdict(report)

    assert any("slowest stage graph" in line for line in lines)


def test_the_verdict_reports_a_faster_deep_profile_as_a_warning_sign() -> None:
    """A negative "cost" printed as a cost would read as deep being free."""
    report = ProfileReport(questions=1, runs_per_question=1)
    report.profiles = [
        _timing("interactive", [100.0], {}),
        _timing("deep", [60.0], {}),
    ]

    lines = verdict(report)

    assert any("FASTER than interactive" in line for line in lines)
    assert not any("deep costs" in line for line in lines)


def test_the_verdict_warns_only_about_stages_that_ran_and_failed() -> None:
    report = ProfileReport(questions=1, runs_per_question=1)
    report.profiles = [
        _timing(
            "interactive",
            [10.0],
            {
                "graph": StageTiming("graph", statuses={"disabled": 4}),
                "hyde": StageTiming("hyde", samples=[1.0], statuses={"timeout": 4}),
            },
        )
    ]

    warnings = [line for line in verdict(report) if line.startswith("Warning")]

    assert len(warnings) == 1
    assert "hyde (4/4)" in warnings[0]
    assert "graph" not in warnings[0]


def test_an_empty_report_produces_no_verdict_rather_than_dividing_by_zero() -> None:
    assert verdict(ProfileReport()) == []


# --- the payload -------------------------------------------------------------


async def test_the_payload_records_that_the_cache_was_off() -> None:
    """A latency number without that caveat is not reproducible."""
    report = await profile_retrieval(
        _StubRetriever({"deep": _traces(vector=("success", 5))}),  # type: ignore[arg-type]
        [_Question("a")],
        runs=1,
        profiles=("deep",),
    )

    payload = report_payload(report)

    assert payload["query_cache"] == "disabled while profiling"
    assert payload["profiles"][0]["stages"][0]["stage"] == "vector"
    assert payload["profiles"][0]["stages"][0]["ran"] == 1
    assert payload["profiles"][0]["stages"][0]["degraded"] == 0
