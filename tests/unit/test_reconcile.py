"""Reconcile decisions and failure guards without a database or model service."""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from sci_rag.db.models import Document
from sci_rag.ingest import CorpusEntry, IngestOutcome, IngestReport, ingester
from sci_rag.ingest.fingerprint import (
    PlaceholderFileError,
    SourceFingerprint,
    fingerprint,
    ingest_signature,
)
from sci_rag.ingest.ingester import PendingIngest
from sci_rag.reconcile import (
    ReconcileBusyError,
    _remove_missing,
    _single_reconcile,
    plan_reconcile,
    reconcile_entries,
)
from sci_rag.versions import canonical_source_path, identity_key_for


def _document(path, *, current=True, seq=1, member=""):  # type: ignore[no-untyped-def]
    return Document(
        id=f"row-{seq}-{member}",
        title="Controlled record",
        source_ref=str(path),
        identity_key=identity_key_for(path, member),
        version_seq=seq,
        is_current=current,
        license_class="public",
        extra={"path": canonical_source_path(path), "source_member": member},
    )


def _file(tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "record.txt"
    path.write_text(
        "A controlled record used to check ingestion decisions without model calls.",
        encoding="utf-8",
    )
    return path


def _factory(documents=()):  # type: ignore[no-untyped-def]
    session = AsyncMock()
    session.scalar.return_value = True
    session.scalars.return_value = Mock(all=Mock(return_value=list(documents)))
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    return Mock(return_value=manager), session


def test_matching_fingerprint_and_configuration_need_no_parse(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=_file(tmp_path))
    row = _document(entry.path)
    row.extra.update(
        source_fingerprint=fingerprint(entry.path).as_dict(),
        ingest_signature=ingest_signature(
            entry, target_tokens=800, overlap_tokens=150, prefer_docling=True
        ),
    )
    parse = Mock(side_effect=AssertionError("unchanged source must not be parsed"))
    monkeypatch.setattr(ingester, "parse_file", parse)
    plan = plan_reconcile([entry], [row], root=tmp_path)
    assert [o.status for o in plan.source_outcomes] == ["unchanged"]
    assert plan.pending == [] and not parse.called


@pytest.mark.parametrize("change", ["rights", "chunking", "legacy"])
def test_metadata_configuration_and_legacy_sources_require_verification(tmp_path, change):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=_file(tmp_path), license_class="public")
    row = _document(entry.path)
    row.extra.update(
        source_fingerprint=fingerprint(entry.path).as_dict(),
        ingest_signature=ingest_signature(
            entry, target_tokens=800, overlap_tokens=150, prefer_docling=True
        ),
    )
    if change == "rights":
        entry.license_class = "unknown"
    if change == "legacy":
        row.extra.pop("source_fingerprint")
    plan = plan_reconcile(
        [entry], [row], root=tmp_path, target_tokens=400 if change == "chunking" else 800
    )
    assert plan.source_outcomes[0].status == "verify"
    assert plan.pending[0][0].predecessor_id == row.id and plan.pending[0][0].version_seq == 2


def test_equal_content_at_different_paths_has_separate_pending_sources(tmp_path):  # type: ignore[no-untyped-def]
    first = _file(tmp_path)
    second = tmp_path / "copy.txt"
    second.write_bytes(first.read_bytes())
    plan = plan_reconcile([CorpusEntry(path=first), CorpusEntry(path=second)], [], root=tmp_path)
    assert len(plan.pending) == 2
    assert all(p.predecessor_id is None for p, _ in plan.pending)


def test_missing_source_groups_the_whole_chain_and_preserves_outside_root(tmp_path):  # type: ignore[no-untyped-def]
    root = tmp_path / "selected"
    root.mkdir()
    missing = root / "gone.txt"
    old, current = _document(missing, current=False), _document(missing, seq=2)
    outside = _document(tmp_path / "elsewhere.txt")
    unknown = Document(
        id="unknown", title="No path", source_ref="https://example.test/source", extra={}
    )
    plan = plan_reconcile([], [old, current, outside, unknown], root=root)
    assert plan.missing == [(canonical_source_path(missing), current.identity_key)]
    assert sorted(o.status for o in plan.database_outcomes) == ["no_path_recorded", "out_of_scope"]
    assert plan.database_rows_seen == 4


def test_manifest_omission_does_not_delete_a_still_existing_file(tmp_path):  # type: ignore[no-untyped-def]
    path = _file(tmp_path)
    assert plan_reconcile([], [_document(path)], root=tmp_path).missing == []


def test_missing_root_and_duplicate_manifest_are_rejected(tmp_path):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=_file(tmp_path))
    with pytest.raises(ValueError, match="root_not_directory"):
        plan_reconcile([], [], root=tmp_path / "absent")
    with pytest.raises(ValueError, match="duplicate_manifest"):
        plan_reconcile([entry, entry], [], root=tmp_path)


def test_unreadable_missing_candidate_is_a_failure_not_a_deletion(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    row = _document(tmp_path / "inaccessible.txt")
    monkeypatch.setattr("sci_rag.reconcile._missing", Mock(side_effect=PermissionError()))
    plan = plan_reconcile([], [row], root=tmp_path)
    assert plan.missing == [] and plan.database_outcomes[0].status == "failed"


def test_placeholder_and_multi_member_sources_keep_existing_data(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=_file(tmp_path))
    monkeypatch.setattr("sci_rag.reconcile.fingerprint", Mock(side_effect=PlaceholderFileError()))
    plan = plan_reconcile([entry], [_document(entry.path)], root=tmp_path)
    assert plan.source_outcomes[0].status == "placeholder_skipped" and not plan.pending
    plan = plan_reconcile([entry], [_document(entry.path, member="mail-1")], root=tmp_path)
    assert plan.source_outcomes[0].status == "failed" and not plan.pending


@pytest.mark.parametrize("attributes", [0x1000, 0x40000, 0x400000])
def test_windows_placeholder_flags_do_not_open_contents(attributes):  # type: ignore[no-untyped-def]
    path = Mock()
    path.stat.return_value = SimpleNamespace(st_file_attributes=attributes)
    with pytest.raises(PlaceholderFileError):
        fingerprint(path)
    path.open.assert_not_called()


@pytest.mark.parametrize("phase", ["before_parse", "during_parse", "parse_failure"])
async def test_source_read_failure_does_not_open_a_write_transaction(tmp_path, monkeypatch, phase):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=_file(tmp_path))
    original = fingerprint(entry.path)
    pending = PendingIngest(entry, "head", 2, original)
    factory = Mock(side_effect=AssertionError("write attempted"))
    embedder = Mock(embed=AsyncMock())
    parsed = Mock()
    monkeypatch.setattr(ingester, "parse_file", Mock(return_value=parsed))
    if phase == "before_parse":
        entry.path.write_text("changed", encoding="utf-8")
    elif phase == "during_parse":
        monkeypatch.setattr(
            ingester, "fingerprint", Mock(side_effect=[original, SourceFingerprint(0, 0)])
        )
    else:
        monkeypatch.setattr(
            ingester, "parse_file", Mock(side_effect=ValueError("untrusted source detail"))
        )
    report = await ingester.ingest_entries([pending], embedder=embedder, session_factory=factory)
    assert report.failed == 1 and not factory.called and not embedder.embed.called
    assert "untrusted source detail" not in report.outcomes[0].detail


async def test_stale_plan_does_not_embed_or_replace_the_current_version(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=_file(tmp_path))
    session = AsyncMock()
    session.scalar.return_value = None

    @asynccontextmanager
    async def transaction(**kwargs):  # type: ignore[no-untyped-def]
        yield session

    monkeypatch.setattr(ingester, "session_scope", transaction)
    embedder = Mock(embed=AsyncMock())
    report = await ingester.ingest_entries(
        [PendingIngest(entry, "old-head", 2, fingerprint(entry.path))], embedder=embedder
    )
    assert report.failed == 1 and report.outcomes[0].detail == "stale_reconcile_plan"
    assert not embedder.embed.called


async def test_busy_reconcile_exits_before_loading_or_writing_sources(tmp_path):  # type: ignore[no-untyped-def]
    factory, session = _factory()
    session.scalar.return_value = False
    embedder = Mock(embed=AsyncMock())
    with pytest.raises(ReconcileBusyError):
        await reconcile_entries([], root=tmp_path, session_factory=factory, embedder=embedder)
    session.scalars.assert_not_called()
    embedder.embed.assert_not_called()


async def test_reconcile_unlocks_on_an_application_error():
    factory, session = _factory()
    with pytest.raises(RuntimeError, match="interrupted"):
        async with _single_reconcile(factory):
            raise RuntimeError("interrupted")
    assert "pg_advisory_unlock" in str(session.execute.call_args.args[0])


async def test_a_failed_source_defers_missing_source_deletion(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    entry = CorpusEntry(path=_file(tmp_path))
    factory, _ = _factory([_document(tmp_path / "gone.txt")])
    ingest = AsyncMock(
        return_value=IngestReport([IngestOutcome(str(entry.path), "failed", "parse_error")])
    )
    remove = AsyncMock()
    monkeypatch.setattr("sci_rag.reconcile.ingest_entries", ingest)
    monkeypatch.setattr("sci_rag.reconcile._remove_missing", remove)
    report = await reconcile_entries(
        [entry], root=tmp_path, session_factory=factory, embedder=Mock()
    )
    assert report.failed == 2 and sum(report.counts().values()) == 1
    assert report.database_outcomes[0].detail == "deletion_deferred_after_source_failure"
    assert not remove.called
    assert ingest.call_args.kwargs["session_factory"] is factory


@pytest.mark.parametrize("reason", ["reappeared", "root_changed"])
async def test_delete_rechecks_source_and_root_before_removing_any_rows(
    tmp_path, monkeypatch, reason
):  # type: ignore[no-untyped-def]
    factory, _ = _factory()
    delete = AsyncMock()
    monkeypatch.setattr("sci_rag.reconcile.delete_documents_in_session", delete)
    path = tmp_path / "gone.txt"
    observed = tmp_path.stat()
    root_identity = (observed.st_dev, observed.st_ino)
    if reason == "reappeared":
        path.write_text("came back", encoding="utf-8")
    else:
        root_identity = (0, 0)
    with pytest.raises(ValueError):
        await _remove_missing(
            factory, Path(canonical_source_path(tmp_path)), root_identity, str(path), "identity"
        )
    assert not delete.called
