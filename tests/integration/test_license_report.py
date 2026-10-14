"""The corpus's rights posture, over a mixed-license fixture.

Two things here are claims about a rights audit rather than about formatting.
Every class in the taxonomy appears even at zero, because a table that omits
`restricted` reads as "not checked" rather than "none". And documents and
chunks are counted separately, because rights are declared per document while
retrieval returns chunks, so the two percentages genuinely differ.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_rag.db import get_session_factory
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.license_report import build_license_report, report_payload
from sci_rag.licensing import LICENSE_CLASSES

pytestmark = pytest.mark.integration


def _entry(tmp_path: Path, name: str, text: str, license_class: str | None, source: str):  # type: ignore[no-untyped-def]
    path = tmp_path / f"{name}.md"
    path.write_text(text)
    fields = {"path": path, "title": name, "source": source}
    if license_class is not None:
        fields["license_class"] = license_class
    return CorpusEntry(**fields)


@pytest.fixture()
def mixed_corpus(tmp_path: Path) -> list[CorpusEntry]:
    """Four documents across three declared classes, plus one nobody declared.

    The public document is deliberately the long one, so its chunk share and
    its document share come apart and the test can tell them apart.
    """
    return [
        _entry(
            tmp_path,
            "county_report",
            "Rice straw availability. " * 400,
            "public",
            "agency_reports",
        ),
        _entry(tmp_path, "open_paper", "An openly licensed study.", "cc-by", "journal_papers"),
        _entry(
            tmp_path, "paywalled", "A publisher version of record.", "restricted", "journal_papers"
        ),
        _entry(tmp_path, "scraped_page", "Nobody recorded the rights here.", None, "web"),
    ]


async def test_every_class_in_the_taxonomy_is_reported_even_at_zero(
    clean_tables, mixed_corpus, local_embedder
):  # type: ignore[no-untyped-def]
    """A missing row reads as "not checked"; a zero reads as "none"."""
    await ingest_entries(mixed_corpus, embedder=local_embedder)

    report = await build_license_report(get_session_factory())

    assert [row.license_class for row in report.by_class] == list(LICENSE_CLASSES)
    counts = {row.license_class: row.documents for row in report.by_class}
    assert counts == {
        "public": 1,
        "open_commercial": 1,  # `cc-by` normalizes here on the way in
        "open_noncommercial": 0,
        "restricted": 1,
        "unknown": 1,
    }


async def test_document_share_and_chunk_share_are_different_facts(
    clean_tables, mixed_corpus, local_embedder
):  # type: ignore[no-untyped-def]
    """Rights are declared per document; retrieval returns chunks."""
    await ingest_entries(mixed_corpus, embedder=local_embedder)

    report = await build_license_report(get_session_factory())
    public = next(row for row in report.by_class if row.license_class == "public")

    assert public.documents == 1
    assert public.document_share == 25.0
    assert public.chunks > 1, "the long document should chunk into several"
    assert public.chunk_share > public.document_share, (
        "one long public document dominates the material an answer would draw on, "
        "which is the fact this column exists to show"
    )


async def test_undeclared_documents_are_named_and_attributed_to_a_source(
    clean_tables, mixed_corpus, local_embedder
):  # type: ignore[no-untyped-def]
    await ingest_entries(mixed_corpus, embedder=local_embedder)

    report = await build_license_report(get_session_factory())

    assert report.undeclared_count == 1
    assert not report.clean
    assert report.undeclared[0].title == "scraped_page"
    assert report.undeclared[0].source == "web"
    assert report.undeclared_by_source == {"web": 1}


async def test_external_safe_is_the_two_classes_the_taxonomy_names(
    clean_tables, mixed_corpus, local_embedder
):  # type: ignore[no-untyped-def]
    """The operational question: what could go on a surface you do not control."""
    await ingest_entries(mixed_corpus, embedder=local_embedder)

    report = await build_license_report(get_session_factory())

    assert report.external_safe_documents == 2  # public + open_commercial
    assert report.external_safe_share == 50.0
    safe = {row.license_class for row in report.by_class if row.external_safe}
    assert safe == {"public", "open_commercial"}


async def test_a_corpus_with_every_right_recorded_is_clean(
    clean_tables, mixed_corpus, local_embedder
):  # type: ignore[no-untyped-def]
    await ingest_entries(
        [entry for entry in mixed_corpus if entry.license_class != "unknown"],
        embedder=local_embedder,
    )

    report = await build_license_report(get_session_factory())

    assert report.clean
    assert report.undeclared == []
    assert report.undeclared_by_source == {}


async def test_an_empty_corpus_reports_zeroes_rather_than_dividing_by_them(
    clean_tables,
):  # type: ignore[no-untyped-def]
    report = await build_license_report(get_session_factory())

    assert report.total_documents == 0
    assert report.clean
    assert all(row.document_share == 0.0 and row.chunk_share == 0.0 for row in report.by_class)
    assert [row.license_class for row in report.by_class] == list(LICENSE_CLASSES)


async def test_the_json_payload_elides_nothing(clean_tables, mixed_corpus, local_embedder):  # type: ignore[no-untyped-def]
    """The table truncates a long undeclared list; `--json` is the complete record."""
    await ingest_entries(mixed_corpus, embedder=local_embedder)

    payload = report_payload(await build_license_report(get_session_factory()))

    assert payload["total_documents"] == 4
    assert len(payload["by_class"]) == len(LICENSE_CLASSES)
    assert payload["external_safe"]["documents"] == 2
    assert payload["undeclared"]["count"] == 1
    assert payload["undeclared"]["documents"][0]["title"] == "scraped_page"
    assert payload["undeclared"]["by_source"] == {"web": 1}
    # Every document is accounted for by exactly one class row.
    assert sum(row["documents"] for row in payload["by_class"]) == payload["total_documents"]
