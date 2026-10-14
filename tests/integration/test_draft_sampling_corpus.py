"""Drafting prefers the corpus a user actually ingested.

Reading `data/raw/` works before `make setup`, but once documents are in the
database the chunker has already done the segmentation work, and chunks carry
their document title. These tests prove the corpus path returns real chunk
text, spreads across documents, and stays deterministic, because the
copy-paste lane depends on the same folder producing the same prompt twice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_rag.db import get_session_factory
from sci_rag.draft import DraftError
from sci_rag.draft.sampling import sample_corpus
from sci_rag.ingest import CorpusEntry, ingest_entries

pytestmark = pytest.mark.integration


@pytest.fixture()
def entries(tmp_path: Path) -> list[CorpusEntry]:
    rice = tmp_path / "rice.md"
    rice.write_text(
        "# Rice Straw Resources\n\n## Availability\n\n"
        "The basin generated 302,000 dry tons of rice straw in 2023.\n\n"
        "## Collection\n\nStraw is baled after harvest and stored at field edge.\n",
        encoding="utf-8",
    )
    almond = tmp_path / "almond.txt"
    almond.write_text(
        "Almond orchard prunings are chipped in the field during winter maintenance. "
        "Mature blocks average 0.9 dry tons per acre per year.",
        encoding="utf-8",
    )
    return [
        CorpusEntry(path=rice, title="Rice Straw Resources", license_class="public"),
        CorpusEntry(path=almond, title="Almond Pruning Logistics", license_class="public"),
    ]


async def test_sampling_reads_real_chunks_from_every_document(
    clean_tables, local_embedder, entries
) -> None:  # type: ignore[no-untyped-def]
    await ingest_entries(entries, embedder=local_embedder)

    sample = await sample_corpus(get_session_factory(), limit=8, per_document=2)

    assert sample.origin == "corpus"
    assert sample.document_count == 2
    assert {p.document_title for p in sample.passages} == {
        "Rice Straw Resources",
        "Almond Pruning Logistics",
    }
    assert any("302,000 dry tons" in p.text for p in sample.passages)


async def test_sampling_is_deterministic(clean_tables, local_embedder, entries) -> None:  # type: ignore[no-untyped-def]
    await ingest_entries(entries, embedder=local_embedder)

    first = await sample_corpus(get_session_factory(), limit=6, per_document=2)
    second = await sample_corpus(get_session_factory(), limit=6, per_document=2)

    assert [(p.document_title, p.text) for p in first.passages] == [
        (p.document_title, p.text) for p in second.passages
    ]


async def test_an_empty_corpus_is_a_clear_failure(clean_tables) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(DraftError, match="no ingested"):
        await sample_corpus(get_session_factory(), limit=6, per_document=2)
