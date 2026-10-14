"""Crossref enrichment against the real Postgres corpus interface."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from sci_rag.db import Document, get_session_factory
from sci_rag.enrich import enrich_documents
from sci_rag.ingest import CorpusEntry, ingest_entries

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "campaigns"


class StaticCrossrefClient:
    async def get_json(self, _url: str, **_kwargs: Any) -> dict[str, Any]:
        return json.loads((FIXTURES / "crossref_retracted.json").read_text())


class UnexpectedNetworkClient:
    async def get_json(self, _url: str, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("dry-run must not make network calls")


class OneMalformedCrossrefClient:
    async def get_json(self, url: str, **_kwargs: Any) -> dict[str, Any]:
        if "malformed" in url:
            return json.loads((FIXTURES / "crossref_malformed.json").read_text())
        return await StaticCrossrefClient().get_json(url)


async def test_enrich_documents_persists_crossref_metadata(
    clean_tables, local_embedder, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    paper = tmp_path / "paper.md"
    paper.write_text("A sufficiently long scientific document about reproducible results.")
    await ingest_entries(
        [
            CorpusEntry(
                path=paper,
                title="Retracted paper",
                doi="10.1000/retracted",
                license_class="public",
            )
        ],
        embedder=local_embedder,
    )

    report = await enrich_documents(get_session_factory(), StaticCrossrefClient())

    assert report.enriched == 1
    assert report.failed == 0
    async with get_session_factory()() as session:
        document = (await session.execute(select(Document))).scalar_one()
    assert document.journal == "Journal of Reproducible Results"
    assert document.extra["crossref"]["is_retracted"] is True
    assert document.extra["crossref"]["retraction_notice_doi"] == "10.1000/retraction-notice"
    assert document.extra["crossref"]["citation_count"] == 17
    assert document.extra["crossref"]["enriched_at"]

    second = await enrich_documents(get_session_factory(), UnexpectedNetworkClient())
    assert second.skipped == 1
    assert second.failed == 0


async def test_enrich_dry_run_plans_without_network_or_writes(
    clean_tables, local_embedder, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    paper = tmp_path / "paper.md"
    paper.write_text("A sufficiently long scientific document about a current result.")
    await ingest_entries(
        [CorpusEntry(path=paper, title="Current paper", doi="10.1000/current")],
        embedder=local_embedder,
    )

    report = await enrich_documents(get_session_factory(), UnexpectedNetworkClient(), dry_run=True)

    assert report.planned == 1
    async with get_session_factory()() as session:
        document = (await session.execute(select(Document))).scalar_one()
    assert "crossref" not in document.extra
    assert document.journal is None


async def test_corpus_enrich_cli_dry_run_reports_the_plan(
    clean_tables, local_embedder, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    paper = tmp_path / "paper.md"
    paper.write_text("A sufficiently long scientific document for a command-line plan.")
    await ingest_entries(
        [CorpusEntry(path=paper, title="CLI paper", doi="10.1000/cli")],
        embedder=local_embedder,
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sci_rag.cli.main",
            "corpus",
            "enrich",
            "--mailto",
            "researcher@example.org",
            "--dry-run",
            "--limit",
            "1",
        ],
        cwd=Path(__file__).parents[2],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "10.1000/cli" in result.stdout
    assert "planned" in result.stdout


async def test_enrich_records_one_failure_and_continues_other_documents(
    clean_tables, local_embedder, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    good = tmp_path / "good.md"
    good.write_text("A sufficiently long scientific document with valid registry metadata.")
    malformed = tmp_path / "malformed.md"
    malformed.write_text("A different scientific document whose registry payload is malformed.")
    await ingest_entries(
        [
            CorpusEntry(path=good, title="Good", doi="10.1000/good"),
            CorpusEntry(path=malformed, title="Malformed", doi="10.1000/malformed"),
        ],
        embedder=local_embedder,
    )

    report = await enrich_documents(get_session_factory(), OneMalformedCrossrefClient())

    assert report.enriched == 1
    assert report.failed == 1
    failure = next(outcome for outcome in report.outcomes if outcome.status == "failed")
    assert failure.doi == "10.1000/malformed"
    assert "update-to" in failure.detail
