from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, ClassVar

from typer.testing import CliRunner

from sci_rag.campaigns import http as campaign_http
from sci_rag.campaigns.discovery import CandidateWork
from sci_rag.campaigns.state import CampaignState
from sci_rag.cli.main import app
from sci_rag.llm import MockLLM

FIXTURES = Path(__file__).parents[1] / "fixtures" / "campaigns"
runner = CliRunner()


class StubPoliteClient:
    init_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).init_kwargs = kwargs

    async def __aenter__(self) -> StubPoliteClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get_json(
        self, _url: str, *, params: dict[str, str | int] | None = None
    ) -> dict[str, Any]:
        return json.loads((FIXTURES / "crossref_work.json").read_text(encoding="utf-8"))


def test_campaign_discover_doi_file_prints_deduplicated_list_and_writes_state(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(campaign_http, "PoliteHttpClient", StubPoliteClient)
    doi_file = tmp_path / "seeds.txt"
    doi_file.write_text(
        "10.7717/PEERJ.4375\nhttps://doi.org/10.7717/peerj.4375\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "campaign",
            "discover",
            "--doi-file",
            str(doi_file),
            "--name",
            "OA Seed",
            "--mailto",
            "researcher@example.org",
            "--campaign-root",
            str(tmp_path / "campaigns"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output.count("10.7717/peerj.4375") == 1
    assert "1 discovered" in result.output
    assert "1 duplicate" in result.output
    assert (tmp_path / "campaigns" / "oa-seed" / "state.jsonl").exists()
    assert StubPoliteClient.init_kwargs["mailto"] == "researcher@example.org"


def test_campaign_discover_requires_exactly_one_input(tmp_path: Path) -> None:
    doi_file = tmp_path / "seeds.txt"
    doi_file.write_text("10.7717/peerj.4375\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "campaign",
            "discover",
            "--topic",
            "open access",
            "--doi-file",
            str(doi_file),
            "--mailto",
            "researcher@example.org",
        ],
    )

    assert result.exit_code != 0
    assert "exactly one" in result.output.lower()


def test_campaign_screen_and_review_cli_preserve_a_human_decision(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    campaign_root = tmp_path / "campaigns"
    state = CampaignState(campaign_root / "review-demo" / "state.jsonl")
    work = CandidateWork(
        doi="10.1000/review",
        title="Uncertain fixture",
        abstract="The abstract does not state the population clearly.",
        source="fixture",
    )
    state.append(doi=work.doi, status="discovered", payload=asdict(work))
    criteria = tmp_path / "criteria.txt"
    criteria.write_text("Include studies of adults.\n", encoding="utf-8")
    llm = MockLLM(
        responses=[
            '{"decisions":[{"index":1,"decision":"exclude",'
            '"confidence":0.5,"reason":"Population unclear."}]}'
        ]
    )
    monkeypatch.setattr("sci_rag.llm.get_llm", lambda _settings: llm)

    screened = runner.invoke(
        app,
        [
            "campaign",
            "screen",
            "--name",
            "review-demo",
            "--criteria-file",
            str(criteria),
            "--campaign-root",
            str(campaign_root),
        ],
    )

    assert screened.exit_code == 0, screened.output
    assert "awaiting review" in screened.output.lower()
    assert (campaign_root / "review-demo" / "screening-report.json").exists()

    reviewed = runner.invoke(
        app,
        [
            "campaign",
            "review",
            "--name",
            "review-demo",
            "--campaign-root",
            str(campaign_root),
        ],
        input="include\nHuman review confirms the population.\n",
    )

    assert reviewed.exit_code == 0, reviewed.output
    assert "1 included" in reviewed.output
    assert "0 awaiting review" in reviewed.output
    loaded = CampaignState(campaign_root / "review-demo" / "state.jsonl")
    assert loaded.records[-1].status == "screen_included"
    assert loaded.records[-1].payload["source"] == "human"


def test_campaign_guide_checkpoint_names_the_shipped_report_and_the_real_invariant() -> None:
    """The guide's last checkpoint has to be reachable and has to state the real sum.

    It sent readers to `sci-rag campaign report`, which was never a registered
    command, and reconciled against "the candidate count". What the code
    actually checks is `PrismaCounts.reconciles`: included plus excluded plus
    awaiting review equals screened. Naming the measures by their field names
    means renaming one breaks this guard rather than the reader's arithmetic.
    """
    import re

    from sci_rag.campaigns.prisma import PrismaCounts

    page = (Path(__file__).parents[2] / "docs" / "campaigns.md").read_text(encoding="utf-8")
    checkpoint = re.sub(
        r"\s+",
        " ",
        page.rpartition('<div class="srag-checkpoint"')[2].partition("</div>")[0],
    )

    for measure in ("included", "excluded", "awaiting_review", "screened"):
        assert measure in PrismaCounts.__dataclass_fields__, measure

    assert "campaign report" not in checkpoint
    assert "`sci-rag campaign review --name rice-straw`" in checkpoint
    assert "`data/campaigns/rice-straw/screening-report.json`" in checkpoint
    assert "`included` plus `excluded` plus `awaiting review` equals `screened`" in checkpoint
