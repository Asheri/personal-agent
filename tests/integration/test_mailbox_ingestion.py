"""Host writes, revisions, missing members, and failures are atomic."""

import mailbox
from email.message import EmailMessage

from sqlalchemy import select

from sci_rag.db import Chunk, Document, get_session_factory
from sci_rag.embed import LocalHashEmbedder
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.ingest.fingerprint import fingerprint
from sci_rag.ingest.ingester import PendingHostIngest
from sci_rag.reconcile import reconcile_entries


def write_box(path, rows):
    if path.exists():
        path.unlink()
    box = mailbox.mbox(path)
    for identity, body in rows:
        msg = EmailMessage()
        msg["From"] = "sender@example.invalid"
        msg["Subject"] = "Record " + identity
        msg["Message-ID"] = f"<{identity}@example.invalid>"
        msg.set_content(body + " Controlled source evidence for this mailbox message.")
        box.add(msg)
    box.flush()
    box.close()


async def records():
    async with get_session_factory()() as session:
        return list((await session.scalars(select(Document))).all())


async def test_mailbox_members_update_independently_and_remove_entire_missing_chains(
    clean_tables, tmp_path, local_embedder
):
    path = tmp_path / "mail.mbox"
    write_box(path, [("a", "first"), ("b", "second"), ("c", "third")])
    entry = CorpusEntry(path=path)
    report = await ingest_entries([entry], embedder=local_embedder)
    assert report.ingested == 1 and report.outcomes[0].document_count == 3
    before = {d.title: d for d in await records()}
    assert all(d.license_class == "unknown" for d in before.values())
    write_box(path, [("c", "third"), ("b", "second revised"), ("d", "fourth")])
    report = await reconcile_entries(
        [entry], root=tmp_path, session_factory=get_session_factory(), embedder=local_embedder
    )
    assert report.failed == 0 and report.source_outcomes[0].status == "updated"
    after = await records()
    current = {d.title: d for d in after if d.is_current}
    assert len(after) == 4 and set(current) == {"Record b", "Record c", "Record d"}
    assert (
        current["Record b"].version_seq == 2
        and current["Record b"].version_of == before["Record b"].id
    )
    assert current["Record c"].id == before["Record c"].id
    assert before["Record a"].id not in {d.id for d in after}
    assert len({d.extra["host_members_digest"] for d in current.values()}) == 1
    repeated = await reconcile_entries(
        [entry], root=tmp_path, session_factory=get_session_factory(), embedder=local_embedder
    )
    assert repeated.source_outcomes[0].status == "unchanged"
    path.unlink()
    removed = await reconcile_entries(
        [], root=tmp_path, session_factory=get_session_factory(), embedder=local_embedder
    )
    assert removed.failed == 0 and await records() == []


async def test_mid_host_embedding_failure_rolls_back_all_members(
    clean_tables, tmp_path, local_embedder
):
    path = tmp_path / "mail.mbox"
    entry = CorpusEntry(path=path)
    write_box(path, [("a", "original a"), ("b", "original b")])
    assert (await ingest_entries([entry], embedder=local_embedder)).failed == 0
    before = {(d.id, d.content_hash, d.is_current, d.version_seq) for d in await records()}

    class FailingEmbedder(LocalHashEmbedder):
        calls = 0

        async def embed(self, texts, *, task):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("controlled provider failure")
            return await super().embed(texts, task=task)

    write_box(path, [("a", "updated a"), ("b", "updated b")])
    report = await ingest_entries([entry], embedder=FailingEmbedder(64))
    assert report.failed == 1
    assert {(d.id, d.content_hash, d.is_current, d.version_seq) for d in await records()} == before


async def test_bad_host_and_stale_snapshot_preserve_data_then_empty_host_clears_members(
    clean_tables, tmp_path, local_embedder
):
    path = tmp_path / "mail.mbox"
    entry = CorpusEntry(path=path)
    write_box(path, [("a", "original a"), ("b", "original b")])
    await ingest_entries([entry], embedder=local_embedder)
    before = {d.id for d in await records()}
    pending = PendingHostIngest(entry, fingerprint(path), {})
    report = await ingest_entries([pending], embedder=local_embedder)
    assert report.failed == 1 and report.outcomes[0].detail == "stale_reconcile_plan"
    write_box(path, [("same", "one"), ("same", "two")])
    report = await ingest_entries([entry], embedder=local_embedder)
    assert report.failed == 1 and report.outcomes[0].detail == "duplicate_message_id"
    assert {d.id for d in await records()} == before
    path.write_bytes(b"")
    report = await ingest_entries([entry], embedder=local_embedder)
    assert (
        report.failed == 0 and report.outcomes[0].documents_removed == 2 and await records() == []
    )
    async with get_session_factory()() as session:
        assert not list((await session.scalars(select(Chunk))).all())
