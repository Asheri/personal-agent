"""Measure a frozen Chinese corpus on an explicitly disposable test database."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from sci_rag.config import get_settings
from sci_rag.db import Base, Chunk, Document, dispose_engine, get_engine, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.embed import LocalHashEmbedder
from sci_rag.evals.report import corpus_fingerprint, retrieval_markdown, retrieval_payload
from sci_rag.evals.retrieval_eval import AblationConfig, run_retrieval_eval
from sci_rag.evals.seeds import SeedQuestion
from sci_rag.retrieve import RetrievalScope, Retriever
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
    payload = json.loads(args.corpus.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    factory = get_session_factory()
    if args.embedding_url:
        from quality_runtime import LocalSemanticEmbedder

        embedder = LocalSemanticEmbedder(args.embedding_url)
    else:
        embedder = LocalHashEmbedder(settings.embedding_dim)
    if args.mode == "seed":
        async with get_engine().begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                text("CREATE INDEX spike_trgm ON chunks USING gin(content gin_trgm_ops)")
            )
        async with factory() as session:
            for row in payload["documents"]:
                doc = Document(
                    title=row["title"],
                    source="controlled-spike",
                    license_class="public",
                    content_hash=hashlib.sha256(row["body"].encode()).hexdigest(),
                )
                session.add(doc)
                await session.flush()
                vector = (await embedder.embed([row["body"]], task="document"))[0]
                session.add(
                    Chunk(
                        document_id=doc.id,
                        chunk_index=0,
                        content=row["body"],
                        token_count=80,
                        embedding=vector,
                        embedding_version=embedder.version,
                    )
                )
            await session.commit()
        print(json.dumps({"seeded": len(payload["documents"])}))
    else:
        scope = RetrievalScope(sources=("controlled-spike",), license_classes=("public",))
        questions = [
            SeedQuestion(
                id=q["id"],
                question=q["question"],
                reference_titles=q["reference_titles"],
                tags=[q["category"], "controlled", "drafted"],
            )
            for q in payload["queries"]
        ]
        configs = [
            AblationConfig(
                layer + "_only",
                "Controlled " + layer,
                dict(
                    include_vector=layer == "vector",
                    include_keyword=layer == "keyword",
                    include_graph=False,
                    include_hyde=False,
                    include_community=False,
                ),
                scope=scope,
            )
            for layer in ["vector", "keyword"]
        ]
        retriever = Retriever(
            domain=load_domain(args.domain), embedder=embedder, session_factory=factory
        )
        results = await run_retrieval_eval(retriever, questions, configs=configs, limit=20)
        fingerprint = await corpus_fingerprint(factory)
        report = retrieval_payload(
            results,
            fingerprint,
            questions=questions,
            provenance={
                "embedding": embedder.version,
                "fixture_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
                "labels": payload["label_status"],
                "mode": args.mode,
            },
        )
        (args.output / f"{args.mode}-retrieval.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (args.output / f"{args.mode}-retrieval.md").write_text(
            retrieval_markdown(results, fingerprint, questions=questions), encoding="utf-8"
        )
        async with factory() as session:
            titles = dict(
                (await session.execute(select(Chunk.id, Document.title).join(Document))).all()
            )
        matrix = []
        for row in payload["queries"]:
            for candidate in ["keyword", "B:pg_trgm", "vector"]:
                elapsed = []
                keys = []
                for _ in range(payload["preregistration"]["repetitions"]):
                    start = time.perf_counter()
                    if candidate == "keyword":
                        keys = [
                            key
                            for _, key in await keyword_stage(factory, row["question"], scope, 20)
                        ]
                    elif candidate == "vector":
                        result = await retriever.retrieve(
                            row["question"],
                            scope=scope,
                            limit=20,
                            include_vector=True,
                            include_keyword=False,
                            include_graph=False,
                            include_hyde=False,
                            include_community=False,
                        )
                        keys = [item.id for item in result.items]
                    else:
                        async with factory() as session:
                            keys = list(
                                (
                                    await session.scalars(
                                        text(
                                            "SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id "
                                            "WHERE c.content % :q AND d.source='controlled-spike' "
                                            "AND d.license_class='public' AND d.is_current "
                                            "ORDER BY similarity(c.content,:q) DESC,c.id LIMIT 20"
                                        ),
                                        {"q": row["question"]},
                                    )
                                ).all()
                            )
                    elapsed.append((time.perf_counter() - start) * 1000)
                hits = [titles[k] for k in keys]
                matrix.append(
                    dict(
                        id=row["id"],
                        category=row["category"],
                        candidate=candidate,
                        hit=bool(set(hits) & set(row["reference_titles"])),
                        titles=hits,
                        latency_ms=elapsed,
                    )
                )
        summaries = {}
        for candidate in ["keyword", "B:pg_trgm", "vector"]:
            selected = [r for r in matrix if r["candidate"] == candidate]
            times = sorted(t for r in selected for t in r["latency_ms"])
            summaries[candidate] = {
                "hit_at_20": sum(r["hit"] for r in selected) / len(selected),
                "p95_ms": times[math.ceil(0.95 * len(times)) - 1],
                "categories": {
                    cat: sum(r["hit"] for r in selected if r["category"] == cat) / 8
                    for cat in ["name", "identifier", "sentence"]
                },
            }
        (args.output / f"{args.mode}-matrix.json").write_text(
            json.dumps(dict(matrix=matrix, summary=summaries), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "matrix": summaries,
                    "eval": {r.config.name: r.metrics for r in results},
                }
            )
        )
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["seed", "before", "after"], required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--domain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--embedding-url", default="")
    asyncio.run(run(parser.parse_args()))
