"""Measure the same constructed language-boundary queries before and after repair."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from sci_rag.config import get_settings
from sci_rag.db import Base, Chunk, Document, dispose_engine, get_engine, get_session_factory
from sci_rag.retrieve import RetrievalScope
from sci_rag.retrieve.stages.keyword import keyword_stage


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.database_url != os.environ.get("SCI_RAG_TEST_DATABASE_URL")
        or url.host != "127.0.0.1"
        or not (url.database or "").endswith("_test")
    ):
        raise ValueError("Explicit loopback disposable _test database required")
    async with get_engine().begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    fixtures = []
    queries = []
    names = ["陈林", "王宁", "李明", "赵敏", "周安", "孙晴", "吴凡", "郑宇"]
    for index, name in enumerate(names):
        marker = f"KGCASE2026A{index}"
        keys = []
        for kind, body in enumerate(
            [f"编号 {marker}。负责人{name}。", f"English source {marker}", f"实验编号{marker}。"]
        ):
            key = f"{index:02}{kind}"
            keys.append(key)
            fixtures.append(dict(key=key, text=body))
        queries.extend(
            [
                dict(query=marker, expected=keys, bucket="identifier"),
                dict(query="编号 " + marker, expected=keys, bucket="mixed"),
                dict(query=name, expected=[keys[0]], bucket="name"),
            ]
        )
    factory = get_session_factory()
    async with factory() as session:
        for row in fixtures:
            doc = Document(
                id=row["key"].zfill(32),
                title="Controlled " + row["key"],
                content_hash=hashlib.sha256(row["text"].encode()).hexdigest(),
                source="controlled",
                license_class="public",
            )
            session.add(doc)
            await session.flush()
            session.add(
                Chunk(
                    id=row["key"].zfill(32),
                    document_id=doc.id,
                    chunk_index=0,
                    content=row["text"],
                    token_count=30,
                )
            )
        await session.commit()
    scope = RetrievalScope(sources=("controlled",), license_classes=("public",))
    results = []
    for row in queries:
        await keyword_stage(factory, row["query"], scope, 20)
        elapsed = []
        for _ in range(3):
            started = time.perf_counter()
            hits = await keyword_stage(factory, row["query"], scope, 20)
            elapsed.append((time.perf_counter() - started) * 1000)
        found = {key.lstrip("0") or "0" for _, key in hits}
        expected = {key.lstrip("0") or "0" for key in row["expected"]}
        results.append(
            {
                **row,
                "hits": [key for _, key in hits],
                "recall": len(found & expected) / len(expected),
                "ms": elapsed,
            }
        )
    latencies = sorted(ms for row in results for ms in row["ms"])
    summary = {
        bucket: sum(row["recall"] for row in results if row["bucket"] == bucket) / 8
        for bucket in ["identifier", "mixed", "name"]
    }
    payload = dict(
        phase=args.phase,
        corpus_sha256=hashlib.sha256(
            json.dumps(fixtures, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        fixtures=fixtures,
        results=results,
        summary=summary,
        p95_ms=latencies[int(len(latencies) * 0.95)],
        note="Constructed warm 24-query boundary test; not semantic embedding or field accuracy",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / (args.phase + ".json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.phase == "after":
        previous = json.loads((args.output / "before.json").read_text(encoding="utf-8"))
        assert previous["corpus_sha256"] == payload["corpus_sha256"]
        assert all(value == 1 for value in summary.values()) and payload["p95_ms"] <= 300
    print(json.dumps(dict(phase=args.phase, summary=summary, p95_ms=payload["p95_ms"])))
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
