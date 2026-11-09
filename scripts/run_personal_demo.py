"""Run real-model personal extraction on an explicitly disposable sample database."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from sci_rag.config import get_settings
from sci_rag.db import (
    Base,
    Chunk,
    Document,
    EntityResolutionAudit,
    KgEntity,
    KgRelationship,
    dispose_engine,
    get_engine,
    get_session_factory,
)
from sci_rag.domain import load_domain
from sci_rag.embed import LocalHashEmbedder
from sci_rag.graph import extract_graph
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import LLMClient, get_llm
from sci_rag.projects import (
    assign_project,
    classify_documents,
    create_project,
    load_project_rules,
    set_manual_tags,
)
from sci_rag.retrieve import RetrievalScope
from sci_rag.retrieve.stages.graph import graph_stage


class RecordedLLM(LLMClient):
    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.model, self.spec = client.model, client.spec
        self.calls: list[dict] = []

    async def generate(
        self, prompt, *, system=None, temperature=0.2, max_tokens=2048, json_mode=False
    ):  # type: ignore[no-untyped-def]
        started = time.monotonic()
        raw = await self.client.generate(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        self.calls.append(
            {
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "response": raw,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        )
        return raw

    def stream(self, prompt, *, system=None, temperature=0.2, max_tokens=2048):  # type: ignore[no-untyped-def]
        return self.client.stream(
            prompt, system=system, temperature=temperature, max_tokens=max_tokens
        )


def _normalize(value: str) -> str:
    return "".join(value.casefold().split())


async def run(corpus: Path, output: Path, *, reset: bool) -> None:
    settings = get_settings()
    database = make_url(settings.database_url)
    if (
        settings.database_url != os.environ.get("SCI_RAG_TEST_DATABASE_URL")
        or database.host not in {"127.0.0.1", "localhost"}
        or not (database.database or "").endswith("_test")
    ):
        raise ValueError("Demo requires an explicit loopback-only disposable test database")
    output.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        if reset:
            await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        if (await session.scalars(select(Document.id))).first() is not None:
            raise ValueError("Demo database is not empty; use a new database or explicit --reset")
    targets = json.loads((corpus / "targets.json").read_text(encoding="utf-8"))
    entries = [
        CorpusEntry(
            path=corpus / row["path"],
            title=row["title"],
            source="synthetic-personal",
            authors=["Synthetic catalog author"],
            license_class=row.get("license_class", "public"),
        )
        for row in targets["documents"]
    ]
    ingest = await ingest_entries(entries, embedder=LocalHashEmbedder(settings.embedding_dim))
    assert ingest.failed == 0 and ingest.ingested == len(entries)
    ids = {
        row["path"]: outcome.document_id
        for row, outcome in zip(targets["documents"], ingest.outcomes, strict=True)
    }
    projects = {name: await create_project(factory, name) for name in ("Atlas", "Horizon")}
    for row in targets["documents"]:
        if row.get("manual"):
            await assign_project(factory, ids[row["path"]], projects[row["project"]].id)
            await set_manual_tags(factory, ids[row["path"]], ["人工标记"])
    domain = load_domain(Path(__file__).resolve().parents[1] / "domain-personal")
    llm = RecordedLLM(get_llm(settings, role="extraction"))
    stats = await extract_graph(
        session_factory=factory, llm=llm, domain=domain, batch_size=1, rate_limit_s=0
    )
    metadata = await classify_documents(
        factory=factory,
        domain=domain,
        llm=llm,
        rules=load_project_rules(corpus / "project_rules.yaml"),
    )
    repeated = await extract_graph(
        session_factory=factory, llm=llm, domain=domain, batch_size=1, rate_limit_s=0
    )
    project_keys = await graph_stage(
        factory,
        llm,
        domain,
        "Atlas 项目有哪些相关材料",
        RetrievalScope(license_classes=("public",)),
        8,
    )
    keys = await graph_stage(
        factory,
        llm,
        domain,
        "陈林参与了哪些项目、有哪些相关材料?",
        RetrievalScope(license_classes=("public",)),
        8,
    )
    async with factory() as session:
        documents = list((await session.scalars(select(Document))).all())
        entities = list((await session.scalars(select(KgEntity))).all())
        relationships = list((await session.scalars(select(KgRelationship))).all())
        audits = list((await session.scalars(select(EntityResolutionAudit))).all())
        chunks = {c.id: c for c in (await session.scalars(select(Chunk))).all()}
    by_id = {d.id: d for d in documents}
    observed, found, expected = [], 0, 0
    for target in targets["documents"]:
        document = by_id[ids[target["path"]]]
        expected_id = projects[target["project"]].id if target["project"] else None
        matches = []
        for name, kind in target["entities"]:
            expected += 1
            aliases = {_normalize(name)}
            if kind == "Project":
                aliases.add(_normalize(name + " 项目"))
            hit = any(
                e.entity_type == kind
                and document.id in e.document_ids
                and aliases.intersection(_normalize(n) for n in [e.name, *e.aliases])
                for e in entities
            )
            found += hit
            matches.append({"name": name, "type": kind, "found": hit})
        observed.append(
            {
                "path": target["path"],
                "document_id": document.id,
                "expected_project": target["project"],
                "ownership_correct": document.project_id == expected_id,
                "project_source": document.project_source,
                "tags": document.tags,
                "auto_tags": document.auto_tags,
                "target_entities": matches,
            }
        )
    paths = []
    for entity in entities:
        witnesses = {
            r.document_id
            for r in relationships
            if r.source_entity_id == entity.id or r.target_entity_id == entity.id
        }
        witnesses.intersection_update(entity.document_ids)
        if len(witnesses) >= 2:
            paths.append(
                {
                    "entity": entity.name,
                    "entity_type": entity.entity_type,
                    "documents": [
                        {"id": key, "title": by_id[key].title} for key in sorted(witnesses)
                    ],
                    "relationships": [
                        {
                            "type": r.relation_type,
                            "document_id": r.document_id,
                            "chunk_id": r.chunk_id,
                            "evidence": r.evidence,
                        }
                        for r in relationships
                        if (r.source_entity_id == entity.id or r.target_entity_id == entity.id)
                        and r.document_id in witnesses
                    ],
                }
            )
    retrieved_documents = sorted(
        {chunks[key].document_id for kind, key in keys if kind == "chunk" and key in chunks}
    )
    ungrounded = [
        r.id
        for r in relationships
        if not r.evidence
        or r.chunk_id not in chunks
        or _normalize(r.evidence) not in _normalize(chunks[r.chunk_id].content)
    ]
    summary = {
        "model": llm.describe(),
        "embedding": "local-hash; no semantic-vector quality claim",
        "labels": targets["status"],
        "domain_digest": stats.domain_digest,
        "corpus_sha256": {
            row["path"]: hashlib.sha256((corpus / row["path"]).read_bytes()).hexdigest()
            for row in targets["documents"]
        },
        "ingested": ingest.ingested,
        "extraction": asdict(stats),
        "metadata": asdict(metadata),
        "repeat_extraction": asdict(repeated),
        "entity_count": len(entities),
        "relationship_count": len(relationships),
        "exact_receipts": sum(a.method == "exact" for a in audits),
        "documents": observed,
        "ownership_correct": sum(row["ownership_correct"] for row in observed),
        "target_entity_recall": {
            "found": found,
            "expected": expected,
            "recall": found / expected if expected else None,
            "note": "Provisional target recall only; labels are not exhaustive or human-approved, so no precision/F1 claim",
        },
        "cross_file_paths": paths,
        "graph_retrieval_document_ids": retrieved_documents,
        "project_query_document_ids": sorted(
            {
                chunks[key].document_id
                for kind, key in project_keys
                if kind == "chunk" and key in chunks
            }
        ),
        "ungrounded_relationship_ids": ungrounded,
        "model_calls": len(llm.calls),
        "limits": [
            "Small synthetic corpus",
            "No representative course-quality benchmark",
            "No human nonauthor approval",
            "Model entity spelling can prevent project-name matching; both project and person query probes are retained",
        ],
    }
    (output / "raw-responses.json").write_text(
        json.dumps(llm.calls, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ingested": ingest.ingested,
                "entities": len(entities),
                "relationships": len(relationships),
                "ownership_correct": summary["ownership_correct"],
                "target_entity_recall": summary["target_entity_recall"],
                "cross_file_paths": len(paths),
                "retrieved_documents": len(retrieved_documents),
                "ungrounded_relationships": len(ungrounded),
                "calls": len(llm.calls),
            }
        )
    )
    await dispose_engine()
    assert stats.batches_failed == 0 and repeated.chunks_processed == 0
    assert summary["ownership_correct"] == len(observed)
    assert paths and len(retrieved_documents) >= 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("examples/personal-files"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset only the explicitly configured disposable test database",
    )
    args = parser.parse_args()
    asyncio.run(run(args.corpus.resolve(), args.output.resolve(), reset=args.reset))
