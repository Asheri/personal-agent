"""What `--max-results` bounds once a campaign has state to resume from.

Discovery honored the option and the build did not. The guide's own sequence
discovers up to 100 works and then uses `--max-results 20` as a bounded
rights-resolution trial, so a reader who followed it made 100 Unpaywall
requests and, outside dry run, would have attempted 100 downloads. The
option's help called it the maximum total candidates, which is what makes the
old behavior a defect rather than a naming disagreement.

The bound has to be deterministic across retries. Campaign state is
append-only and `load_discovered_candidates` walks it in file order, so the
first N are the same N every time, and a resumed trial keeps working on the
candidates it already resolved instead of sampling a new set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sci_rag.campaigns.build import build_campaign, load_discovered_candidates
from sci_rag.campaigns.state import CampaignState

DISCOVERED = 100


class CountingClient:
    """Answers every Unpaywall lookup and records which DOIs were asked for."""

    mailto = "researcher@example.org"

    def __init__(self) -> None:
        self.requested: list[str] = []

    async def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # The DOI is everything after the base URL, and it contains a slash.
        doi = url.split("/v2/", 1)[1]
        self.requested.append(doi)
        return {
            "doi": doi,
            "is_oa": False,
            "oa_status": "closed",
            "best_oa_location": None,
        }


def _state_with_discoveries(tmp_path: Path, count: int = DISCOVERED) -> CampaignState:
    state = CampaignState(tmp_path / "state.jsonl")
    for index in range(count):
        doi = f"10.1234/work-{index:03d}"
        state.append(
            doi=doi,
            status="discovered",
            payload={
                "doi": doi,
                "title": f"Work {index}",
                "year": None,
                "authors": [],
                "journal": None,
                "oa_status_hint": None,
                "license_hint": None,
                "source": "openalex",
            },
        )
    return state


async def _build(tmp_path: Path, *, dry_run: bool, max_results: int | None) -> tuple[Any, Any]:
    state = _state_with_discoveries(tmp_path)
    client = CountingClient()
    report = await build_campaign(
        load_discovered_candidates(state),
        campaign_dir=tmp_path,
        state=state,
        client=client,  # type: ignore[arg-type]
        dry_run=dry_run,
        max_results=max_results,
        unpaywall_base_url="http://unpaywall.invalid/v2",
    )
    return report, client


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "download"])
async def test_a_lower_build_maximum_bounds_a_larger_discovery(  # type: ignore[no-untyped-def]
    tmp_path: Path, dry_run: bool
) -> None:
    """100 discovered, 20 asked for, 20 processed. Both modes, same bound."""
    report, client = await _build(tmp_path, dry_run=dry_run, max_results=20)

    assert len(client.requested) == 20
    assert report.candidates == 20
    assert report.resolved == 20


async def test_the_report_separates_what_is_retained_from_what_was_attempted(
    tmp_path: Path,
) -> None:
    """A trial that says "candidates 100" reads as having processed 100."""
    report, _ = await _build(tmp_path, dry_run=True, max_results=20)

    assert report.retained == DISCOVERED
    assert report.candidates == 20


async def test_the_same_candidates_are_in_scope_on_every_retry(tmp_path: Path) -> None:
    """Resume must not sample a different 20 out of the same 100."""
    _, first = await _build(tmp_path / "a", dry_run=True, max_results=20)
    _, second = await _build(tmp_path / "b", dry_run=True, max_results=20)

    assert first.requested == second.requested


async def test_no_maximum_processes_every_retained_candidate(tmp_path: Path) -> None:
    """The explicit override for a reader who wants the whole retained set."""
    report, client = await _build(tmp_path, dry_run=True, max_results=None)

    assert len(client.requested) == DISCOVERED
    assert report.candidates == DISCOVERED
    assert report.retained == DISCOVERED
