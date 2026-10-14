"""Passage sampling: what the drafters actually show the model.

A drafting prompt is only worth pasting into an assistant if it carries real
text from the user's own documents. These tests pin the two sources, the
determinism both need (the same folder must render the same prompt, or the
copy-paste lane cannot be reproduced), and the spread across documents that
keeps one long report from crowding out the other four.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_rag.draft import DraftError
from sci_rag.draft.sampling import format_passages, sample_files

REPO_ROOT = Path(__file__).parents[2]
FIXTURE = REPO_ROOT / "data" / "demo" / "fixture"


def test_sampling_spreads_across_every_document() -> None:
    sample = sample_files(FIXTURE, limit=10, per_document=2)

    assert sample.origin == "files"
    assert sample.document_count == 5
    titles = {p.document_title for p in sample.passages}
    assert len(titles) == 5, f"one passage per document at least, got {titles}"
    assert len(sample.passages) <= 10


def test_sampling_is_deterministic() -> None:
    first = sample_files(FIXTURE, limit=8, per_document=2)
    second = sample_files(FIXTURE, limit=8, per_document=2)

    assert [(p.document_title, p.text) for p in first.passages] == [
        (p.document_title, p.text) for p in second.passages
    ]


def test_passages_carry_real_document_text() -> None:
    sample = sample_files(FIXTURE, limit=10, per_document=3)
    joined = "\n".join(p.text for p in sample.passages)

    assert "rice straw" in joined.lower()
    assert all(p.text.strip() for p in sample.passages)


def test_passages_render_numbered_with_their_document_title() -> None:
    sample = sample_files(FIXTURE, limit=4, per_document=1)
    block = format_passages(sample.passages)

    assert block.startswith("[1]")
    assert "[2]" in block
    assert sample.passages[0].document_title in block


def test_an_empty_folder_is_a_clear_failure(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()

    with pytest.raises(DraftError, match="no supported documents"):
        sample_files(tmp_path / "notes", limit=4, per_document=1)


def test_a_missing_folder_is_a_clear_failure(tmp_path: Path) -> None:
    with pytest.raises(DraftError, match="does not exist"):
        sample_files(tmp_path / "nowhere", limit=4, per_document=1)
