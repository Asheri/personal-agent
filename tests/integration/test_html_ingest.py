"""HTML pages through the real ingestion pipeline.

The unit tests check the parser in isolation; these check that its output is
actually the shape the rest of the pipeline expects. Two claims only the full
path can settle: that headings become the section-path breadcrumb a chunk
carries, and that a table survives as one `is_table` chunk rather than being
merged into the prose around it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from sci_rag.db import session_scope
from sci_rag.db.models import Chunk, Document
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.ingest.manifest import discover_folder

pytestmark = pytest.mark.integration

PAGE = """<!DOCTYPE html>
<html><head><title>Rice Straw Handling | Demo Lab</title>
<script>var t = 1;</script></head>
<body>
<nav>Home Docs Contact</nav>
<main>
<h1>Rice Straw Handling</h1>
<h2>Composition</h2>
<p>{filler}</p>
<p>Ash content is near 18 percent, which includes high silica.</p>
<table>
  <tr><th>Property</th><th>Value</th></tr>
  <tr><td>Ash content</td><td>18 percent</td></tr>
  <tr><td>Biogas yield</td><td>320 cubic meters per dry ton</td></tr>
</table>
</main>
<footer>Copyright 2026</footer>
</body></html>
"""


@pytest.fixture()
def page(tmp_path: Path) -> Path:
    # Long enough that the chunker has to make more than one chunk, so the
    # table's separation from the prose is a real outcome and not an artifact
    # of everything fitting in one chunk anyway.
    path = tmp_path / "rice-straw.html"
    path.write_text(PAGE.format(filler="Rice straw availability is high. " * 200), encoding="utf-8")
    return path


async def _chunks_for(title: str) -> list[Chunk]:
    async with session_scope() as session:
        document_id = await session.scalar(select(Document.id).where(Document.title == title))
        assert document_id, f"no document titled {title!r}"
        return list(
            (
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.document_id == document_id)
                    .order_by(Chunk.chunk_index)
                )
            ).all()
        )


async def test_an_html_page_ingests_through_a_manifest(clean_tables, page, local_embedder):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=page, title="Rice Straw Handling", license_class="public")

    report = await ingest_entries([entry], embedder=local_embedder)

    assert report.ingested == 1, report.outcomes
    assert report.failed == 0
    chunks = await _chunks_for("Rice Straw Handling")
    assert len(chunks) > 1, "the fixture is long enough to need several chunks"


async def test_folder_discovery_finds_html_without_a_manifest(clean_tables, page, local_embedder):  # type: ignore[no-untyped-def]
    """`.html` is in SUPPORTED_SUFFIXES, so discovery picks it up unaided."""
    entries = discover_folder(page.parent)

    assert [entry.path.name for entry in entries] == ["rice-straw.html"]

    report = await ingest_entries(entries, embedder=local_embedder)
    assert report.ingested == 1, report.outcomes


async def test_headings_become_the_section_path_on_the_chunk(clean_tables, page, local_embedder):  # type: ignore[no-untyped-def]
    """This is what HTML structure is for: a breadcrumb the answer can cite."""
    await ingest_entries(
        [CorpusEntry(path=page, title="Rice Straw Handling")], embedder=local_embedder
    )

    chunks = await _chunks_for("Rice Straw Handling")
    section_paths = {chunk.section_path for chunk in chunks if chunk.section_path}

    assert any("Composition" in path for path in section_paths), section_paths


async def test_the_table_survives_as_its_own_intact_chunk(clean_tables, page, local_embedder):  # type: ignore[no-untyped-def]
    await ingest_entries(
        [CorpusEntry(path=page, title="Rice Straw Handling")], embedder=local_embedder
    )

    chunks = await _chunks_for("Rice Straw Handling")
    tables = [chunk for chunk in chunks if chunk.is_table]

    assert len(tables) == 1, "the page has exactly one table"
    body = tables[0].content
    assert "| Ash content | 18 percent |" in body
    assert "| Biogas yield | 320 cubic meters per dry ton |" in body
    assert "Rice straw availability is high." not in body, "prose must not leak into the table"


async def test_page_chrome_never_reaches_a_chunk(clean_tables, page, local_embedder):  # type: ignore[no-untyped-def]
    """The end-to-end version of the claim: a shared sidebar is not corpus text."""
    await ingest_entries(
        [CorpusEntry(path=page, title="Rice Straw Handling")], embedder=local_embedder
    )

    body = " ".join(chunk.content for chunk in await _chunks_for("Rice Straw Handling"))

    for chrome in ("Home Docs Contact", "Copyright 2026", "var t = 1"):
        assert chrome not in body, f"{chrome!r} should have been stripped before chunking"


async def test_the_parser_that_ran_is_recorded(clean_tables, page, local_embedder):  # type: ignore[no-untyped-def]
    """Same receipt the PDF routes leave, so a corpus can be audited by route."""
    await ingest_entries(
        [CorpusEntry(path=page, title="Rice Straw Handling")], embedder=local_embedder
    )

    async with session_scope() as session:
        extra = await session.scalar(
            select(Document.extra).where(Document.title == "Rice Straw Handling")
        )

    assert extra["parser"] == "html"
