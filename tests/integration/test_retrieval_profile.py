"""The profiler against the real retriever, offline.

The unit tests script the traces; this one proves the traces exist to be
scripted. Running the real orchestrator with the deterministic local embedder
is what shows that the profiler needs no new instrumentation: every number it
reports is one a single traced request already carries.

Timings here are honest but not comparable to anything: a two-document corpus
on a developer machine is not a latency benchmark. What is asserted is the
shape: that each profile ran, that the stages a profile enables reported
durations, and that the ones it disables did not become samples.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_rag.evals.seeds import SeedQuestion
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.retrieve import Retriever
from sci_rag.retrieve.profiler import PROFILES, profile_retrieval, report_payload, verdict

pytestmark = pytest.mark.integration


@pytest.fixture()
def corpus(tmp_path: Path) -> list[CorpusEntry]:
    entries = []
    for name, text in (
        ("rice", "Rice straw availability is near 310,000 tons per year in the valley."),
        ("almond", "Almond prunings are chipped in winter and stored on site."),
    ):
        path = tmp_path / f"{name}.md"
        path.write_text(text)
        entries.append(CorpusEntry(path=path, title=name, license_class="public", source="tests"))
    return entries


QUESTIONS = [
    SeedQuestion(id="straw", question="How much rice straw is available?"),
    SeedQuestion(id="prunings", question="When are almond prunings chipped?"),
]


async def test_the_profiler_measures_every_profile_over_the_real_retriever(
    clean_tables, corpus, local_embedder
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus, embedder=local_embedder)

    report = await profile_retrieval(Retriever(), QUESTIONS, runs=2)

    assert report.questions == 2
    assert report.runs_per_question == 2
    assert [timing.profile for timing in report.profiles] == list(PROFILES)
    for timing in report.profiles:
        assert timing.runs == 4, f"{timing.profile} should have 2 questions x 2 runs"
        assert timing.p95 >= timing.p50 >= 0.0


async def test_the_stages_a_profile_runs_report_real_durations(
    clean_tables, corpus, local_embedder
):  # type: ignore[no-untyped-def]
    """No new instrumentation: these are the traces a single request already carries."""
    await ingest_entries(corpus, embedder=local_embedder)

    report = await profile_retrieval(Retriever(), QUESTIONS, runs=2, profiles=("interactive",))
    interactive = report.by_name("interactive")
    assert interactive is not None

    # Vector and keyword are on in every profile.
    assert "vector" in interactive.stages
    assert "keyword" in interactive.stages
    assert interactive.stages["vector"].ran == 4
    assert interactive.stages["vector"].samples, "the vector stage should report durations"


async def test_a_stage_the_profile_disables_is_counted_but_not_sampled(
    clean_tables, corpus, local_embedder
):  # type: ignore[no-untyped-def]
    """`interactive` switches graph, community, and HyDE off; that is not a failure."""
    await ingest_entries(corpus, embedder=local_embedder)

    report = await profile_retrieval(Retriever(), QUESTIONS, runs=1, profiles=("interactive",))
    interactive = report.by_name("interactive")
    assert interactive is not None

    for name in ("graph", "community", "hyde"):
        stage = interactive.stages.get(name)
        if stage is None:  # pragma: no cover - the orchestrator always traces these
            continue
        assert stage.statuses.get("disabled", 0) == 2, f"{name} should be off in interactive"
        assert stage.degraded == 0, f"a disabled {name} is not a degradation"
        assert stage.samples == [], f"a disabled {name} should not be a timing sample"


async def test_auto_records_which_profile_it_chose(clean_tables, corpus, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus, embedder=local_embedder)

    report = await profile_retrieval(Retriever(), QUESTIONS, runs=1, profiles=("auto",))
    auto = report.by_name("auto")
    assert auto is not None

    assert sum(auto.resolved.values()) == 2
    assert set(auto.resolved) <= {"interactive", "deep"}
    assert "router" in auto.stages, "routing is itself a measurable cost"


async def test_the_verdict_and_payload_render_from_a_real_run(clean_tables, corpus, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus, embedder=local_embedder)

    report = await profile_retrieval(Retriever(), QUESTIONS, runs=2)

    lines = verdict(report)
    assert lines
    assert any(line.startswith("interactive:") for line in lines)
    assert any("p95 per request" in line for line in lines)

    payload = report_payload(report)
    assert payload["questions"] == 2
    assert payload["query_cache"] == "disabled while profiling"
    assert [entry["profile"] for entry in payload["profiles"]] == list(PROFILES)
    for entry in payload["profiles"]:
        assert entry["runs"] == 4
        assert entry["wall_clock_ms"]["p95"] >= entry["wall_clock_ms"]["p50"]
        assert entry["stages"], f"{entry['profile']} should report stages"
