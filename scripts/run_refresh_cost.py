"""Measure bounded constructed-corpus refresh and discovery costs without a model."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from sci_rag.config import get_settings
from sci_rag.db import Base, Document, dispose_engine, get_engine, get_session_factory
from sci_rag.embed import LocalHashEmbedder
from sci_rag.ingest import discover_folder
from sci_rag.reconcile import plan_reconcile
from sci_rag.refresh import refresh_corpus


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.database_url != os.environ.get("SCI_RAG_TEST_DATABASE_URL")
        or url.host != "127.0.0.1"
        or not (url.database or "").endswith("_test")
    ):
        raise ValueError("Explicit loopback disposable database required")
    if not 1 <= args.files <= 200:
        raise ValueError("Keep this acceptance corpus at 1 to 200 files")
    args.corpus.mkdir(parents=True, exist_ok=True)
    for index in range(args.files):
        (args.corpus / f"record-{index:03}.txt").write_text(
            f"Controlled polling record {index}. This source is used only to measure local mechanism cost.",
            encoding="utf-8",
        )
    async with get_engine().begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    class Counted(LocalHashEmbedder):
        calls = 0

        async def embed(self, texts, *, task):
            self.calls += 1
            return await super().embed(texts, task=task)

    embedder = Counted(settings.embedding_dim)
    first = await refresh_corpus(
        root=args.corpus, channel="poll", embedder=embedder, update_graph=False
    )
    assert first["status"] == "success" and first["counts"]["added"] == args.files
    original = embedder.calls
    repeated = []
    for _ in range(3):
        result = await refresh_corpus(
            root=args.corpus, channel="poll", embedder=embedder, update_graph=False
        )
        assert result["counts"]["unchanged"] == args.files and result["status"] == "success"
        repeated.append(result["elapsed_ms"])
    assert embedder.calls == original
    factory = get_session_factory()
    async with factory() as session:
        documents = list((await session.scalars(select(Document))).all())
    scanning = []
    for _ in range(5):
        started = time.perf_counter()
        entries = discover_folder(args.corpus)
        discovered = time.perf_counter()
        plan = plan_reconcile(entries, documents, root=args.corpus)
        finished = time.perf_counter()
        assert len(plan.pending) == 0
        scanning.append(
            dict(discover_ms=(discovered - started) * 1000, plan_ms=(finished - discovered) * 1000)
        )
    payload = dict(
        files=args.files,
        embedding="local-hash, no semantic/model claim",
        first_refresh_ms=first["elapsed_ms"],
        repeat_refresh_ms=repeated,
        repeat_embedding_calls=embedder.calls - original,
        stat_scan_samples=scanning,
        limits="Constructed small corpus, warm local disk, sequential single-user run; not a large-corpus or concurrency SLA. Full refresh includes audit, local rules, mentions, and freshness maintenance.",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--files", type=int, default=100)
    asyncio.run(run(parser.parse_args()))
