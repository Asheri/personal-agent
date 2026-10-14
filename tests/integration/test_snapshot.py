"""Corpus snapshots: a named, content-addressed fingerprint of what you have.

A snapshot pins counts, per-document content hashes, embedding versions,
and the git commit under a name that eval reports can reference, which
is what makes "the numbers were measured on corpus X" reproducible
instead of folklore.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.db import get_session_factory
from sci_rag.evals.report import retrieval_payload
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.snapshot import list_snapshots, load_snapshot, write_snapshot

pytestmark = pytest.mark.integration


@pytest.fixture()
def corpus_entries(tmp_path: Path) -> list[CorpusEntry]:
    docs = []
    for name, text in (
        ("rice", "Rice straw availability is near 310,000 tons per year."),
        ("almond", "Almond prunings are chipped in winter."),
    ):
        p = tmp_path / f"{name}.md"
        p.write_text(text)
        docs.append(CorpusEntry(path=p, title=name, license_class="public", source="tests"))
    return docs


async def test_snapshot_matches_database_state(
    clean_tables, corpus_entries, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    info = await write_snapshot(get_session_factory(), name="baseline", base_dir=tmp_path / "snaps")
    assert info.name == "baseline"
    payload = json.loads(info.path.read_text())
    assert payload["counts"]["documents"] == 2
    assert payload["counts"]["chunks"] >= 2
    assert len(payload["documents"]) == 2
    assert all(len(d["content_hash"]) == 64 for d in payload["documents"])
    assert payload["embedding_versions"] == [local_embedder.version]
    assert payload["corpus_digest"]


async def test_snapshot_digest_changes_when_corpus_changes(
    clean_tables, corpus_entries, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries[:1], embedder=local_embedder)
    first = await write_snapshot(get_session_factory(), name="one", base_dir=tmp_path / "snaps")
    await ingest_entries(corpus_entries[1:], embedder=local_embedder)
    second = await write_snapshot(get_session_factory(), name="two", base_dir=tmp_path / "snaps")
    digest_one = json.loads(first.path.read_text())["corpus_digest"]
    digest_two = json.loads(second.path.read_text())["corpus_digest"]
    assert digest_one != digest_two


async def test_list_and_load_round_trip(clean_tables, corpus_entries, local_embedder, tmp_path):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    base = tmp_path / "snaps"
    await write_snapshot(get_session_factory(), name="alpha", base_dir=base)
    await write_snapshot(get_session_factory(), name="beta", base_dir=base)
    names = [s.name for s in list_snapshots(base)]
    assert names == ["alpha", "beta"]
    loaded = load_snapshot("alpha", base_dir=base)
    assert loaded["name"] == "alpha"


async def test_duplicate_snapshot_name_rejected(
    clean_tables, corpus_entries, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    await ingest_entries(corpus_entries, embedder=local_embedder)
    base = tmp_path / "snaps"
    await write_snapshot(get_session_factory(), name="alpha", base_dir=base)
    with pytest.raises(FileExistsError):
        await write_snapshot(get_session_factory(), name="alpha", base_dir=base)


def test_eval_payload_records_snapshot_name() -> None:
    payload = retrieval_payload([], {"documents": 2}, snapshot="baseline")
    assert payload["snapshot"] == "baseline"
    without = retrieval_payload([], {"documents": 2})
    assert without.get("snapshot") is None


async def test_a_written_snapshot_is_committable_as_it_stands(
    clean_tables, corpus_entries, local_embedder, tmp_path
):  # type: ignore[no-untyped-def]
    """The file ends with a newline, because these get committed.

    Snapshots live in `data/snapshots/` and are tracked, and this
    repository runs `end-of-file-fixer` over every file in CI. A writer
    that omits the final newline produces an artifact that fails the
    project's own hook the first time anyone commits one, which is what
    happened to `benchmark-20260831-041957.json`. The three snapshots
    already in the tree end with a newline only because the hook rewrote
    them on the way in.
    """
    await ingest_entries(corpus_entries, embedder=local_embedder)
    info = await write_snapshot(get_session_factory(), name="committable", base_dir=tmp_path)

    raw = info.path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert not raw.endswith("\n\n")
