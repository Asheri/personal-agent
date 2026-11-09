"""Batch scheduling for graph extraction: order, pacing, and the in-flight cap.

The batches here are integers rather than SQL rows. ``_run_batches`` never reads
a batch, it only hands it to the callback, so any sequence exercises the
scheduling that decides whether one model call is in flight or four.
"""

from __future__ import annotations

import asyncio
import time

from sci_rag.graph.extractor import _run_batches


async def test_serial_path_keeps_the_ingest_order() -> None:
    seen: list[int] = []

    async def run_one(batch) -> None:  # type: ignore[no-untyped-def]
        seen.append(batch[0])

    await _run_batches([[1], [2], [3]], concurrency=1, run_one=run_one)
    assert seen == [1, 2, 3]


async def test_serial_path_keeps_the_pacing_pause() -> None:
    async def run_one(batch) -> None:  # type: ignore[no-untyped-def]
        return None

    started = time.perf_counter()
    await _run_batches([[1], [2], [3]], concurrency=1, run_one=run_one, rate_limit_s=0.02)
    # Two pauses between three batches, never one after the last.
    assert time.perf_counter() - started >= 0.04


async def test_concurrent_path_paces_nothing() -> None:
    async def run_one(batch) -> None:  # type: ignore[no-untyped-def]
        return None

    started = time.perf_counter()
    await _run_batches([[1], [2], [3], [4]], concurrency=4, run_one=run_one, rate_limit_s=0.5)
    # A serial path would spend 1.5 s here; the relaxed bound leaves room for a
    # loaded builder without letting the pause leak into the concurrent path.
    assert time.perf_counter() - started < 0.25


async def test_concurrency_caps_the_batches_in_flight() -> None:
    live = 0
    peak = 0

    async def run_one(batch) -> None:  # type: ignore[no-untyped-def]
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0)  # yield, so a free slot can start its own batch
        live -= 1

    await _run_batches([[index] for index in range(8)], concurrency=3, run_one=run_one)
    assert peak == 3


async def test_concurrent_path_runs_every_batch_exactly_once() -> None:
    seen: list[int] = []

    async def run_one(batch) -> None:  # type: ignore[no-untyped-def]
        seen.append(batch[0])
        await asyncio.sleep(0)

    await _run_batches([[index] for index in range(10)], concurrency=4, run_one=run_one)
    assert sorted(seen) == list(range(10))


async def test_a_swallowed_failure_leaves_the_other_batches_running() -> None:
    attempted: list[int] = []

    async def run_one(batch) -> None:  # type: ignore[no-untyped-def]
        attempted.append(batch[0])
        try:
            if batch[0] == 3:
                raise ValueError("unusable output")
        except ValueError:
            # ``_extract_with_recovery`` handles its own failures; the scheduler
            # must not stop the remaining work when it does.
            return
        await asyncio.sleep(0)

    await _run_batches([[index] for index in range(5)], concurrency=2, run_one=run_one)
    assert sorted(attempted) == [0, 1, 2, 3, 4]
