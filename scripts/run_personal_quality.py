"""Real-model controlled acceptance with frozen labels and retained raw answers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from quality_runtime import LocalSemanticEmbedder, RecordedLLM
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from sci_rag.answer import AnswerEngine
from sci_rag.answer.generator import _CITATION_RE
from sci_rag.config import get_settings
from sci_rag.db import (
    Base,
    Chunk,
    Document,
    KgEntity,
    KgRelationship,
    dispose_engine,
    get_engine,
    get_session_factory,
)
from sci_rag.domain import load_domain
from sci_rag.embed import LocalHashEmbedder
from sci_rag.evals.report import domain_digest
from sci_rag.graph import extract_graph
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.projects import (
    ProjectRule,
    assign_project,
    classify_documents,
    create_project,
    set_manual_tags,
)
from sci_rag.retrieve import RetrievalScope, Retriever


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_source(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".docx":
        from docx import Document as WordDocument

        doc = WordDocument()
        doc.add_paragraph(body)
        doc.save(path)
    elif path.suffix == ".pptx":
        from pptx import Presentation

        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        from pptx.util import Inches

        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(4)).text_frame.text = body
        presentation.save(path)
    elif path.suffix == ".pdf":
        # Minimal Unicode test PDF, with explicit ToUnicode mapping for extraction.
        from pypdf import PdfWriter
        from pypdf.generic import (
            ArrayObject,
            DecodedStreamObject,
            DictionaryObject,
            NameObject,
            NumberObject,
            TextStringObject,
        )

        writer = PdfWriter()
        page = writer.add_blank_page(width=595, height=842)
        cmap = DecodedStreamObject()
        pairs = "\n".join(f"<{ord(c):04X}> <{ord(c):04X}>" for c in sorted(set(body)))
        cmap.set_data(
            (
                "/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
                "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def "
                "/CMapName /TestUnicode def /CMapType 2 def "
                "1 begincodespacerange <0000> <FFFF> endcodespacerange "
                f"{len(set(body))} beginbfchar\n{pairs}\nendbfchar endcmap "
                "CMapName currentdict /CMap defineresource pop end end"
            ).encode("ascii")
        )
        descendant = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/CIDFontType0"),
                NameObject("/BaseFont"): NameObject("/STSong-Light"),
                NameObject("/CIDSystemInfo"): DictionaryObject(
                    {
                        NameObject("/Registry"): TextStringObject("Adobe"),
                        NameObject("/Ordering"): TextStringObject("GB1"),
                        NameObject("/Supplement"): NumberObject(0),
                    }
                ),
            }
        )
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/STSong-Light"),
                NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/DescendantFonts"): ArrayObject([writer._add_object(descendant)]),
                NameObject("/ToUnicode"): writer._add_object(cmap),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        lines = [body[i : i + 36] for i in range(0, len(body), 36)]
        stream.set_data(
            (
                "BT /F1 12 Tf 36 780 Td 18 TL "
                + " ".join(f"<{line.encode('utf-16-be').hex()}> Tj T*" for line in lines)
                + " ET"
            ).encode("ascii")
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(path)
    elif path.suffix == ".html":
        path.write_text("<html><body><p>" + body + "</p></body></html>", encoding="utf-8")
    else:
        path.write_text(body, encoding="utf-8")


def normalize(value: str) -> str:
    return re.sub(r"[\s《》“”\"']", "", value).casefold()


def metrics(expected: set, predicted: set) -> dict[str, Any]:
    tp = len(expected & predicted)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(expected) if expected else 0.0
    return dict(
        expected=len(expected),
        predicted=len(predicted),
        matched=tp,
        precision=precision,
        recall=recall,
        f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        missed=sorted(expected - predicted),
        extra=sorted(predicted - expected),
    )


class FixedLayersRetriever(Retriever):
    def __init__(self, *, use_graph: bool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.use_graph = use_graph

    async def retrieve(self, query: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        return await super().retrieve(
            query,
            **kwargs,
            include_vector=True,
            include_keyword=True,
            include_graph=self.use_graph,
            include_community=False,
            include_hyde=False,
        )


async def run(args: argparse.Namespace) -> None:
    from sci_rag.llm import get_llm

    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.database_url != os.environ.get("SCI_RAG_TEST_DATABASE_URL")
        or url.host != "127.0.0.1"
        or not (url.database or "").endswith("_test")
    ):
        raise ValueError("Explicit loopback disposable _test database required")
    payload = json.loads(args.corpus.read_text(encoding="utf-8"))
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    factory = get_session_factory()
    embedder = LocalSemanticEmbedder(args.embedding_url)
    all_rows = payload["cases"] + payload["controls"]
    if args.phase == "seed":
        async with get_engine().begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        projects = {
            name: await create_project(factory, name) for name in ["星河", "海岚", "青岚", "云帆"]
        }
        seeded = {}
        for row in all_rows:
            path = args.files / row["id"] / ("input." + row["format"])
            rights = row.get("rights", "public")
            entry = CorpusEntry(
                path=path,
                title=row["id"],
                source="controlled-quality" if row in payload["cases"] else "quality-controls",
                license_class=rights,
            )
            if row["id"] == "p1-1":
                render_source(path, payload["old_revision_body"])
                old = await ingest_entries([entry], embedder=embedder, prefer_docling=False)
                assert old.ingested == 1
            render_source(path, row["body"])
            actual_embedder = embedder if rights == "public" else LocalHashEmbedder(1024)
            result = await ingest_entries([entry], embedder=actual_embedder, prefer_docling=False)
            assert result.ingested == 1, asdict(result)
            doc_id = result.outcomes[0].document_id
            seeded[row["id"]] = doc_id
            if row.get("manual"):
                await assign_project(factory, doc_id, projects[row["manual"]].id)
                await set_manual_tags(factory, doc_id, ["manual-control"])
        write_json(
            output / "seed.json",
            dict(
                ids=seeded,
                projects={k: v.id for k, v in projects.items()},
                corpus_sha256=hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
            ),
        )
        # Verify parsed text, not merely successful file opening, for all six formats.
        async with factory() as session:
            chunks = list((await session.scalars(select(Chunk))).all())
            for row in all_rows:
                actual = "".join(c.content for c in chunks if c.document_id == seeded[row["id"]])
                assert normalize(row["body"]) in normalize(actual), row["id"]
        print(json.dumps(dict(seeded=len(seeded), formats=sorted({r["format"] for r in all_rows}))))
    else:
        seed = json.loads((output / "seed.json").read_text(encoding="utf-8"))
        domain = load_domain(args.domain)
        calls: list[dict[str, Any]] = []
        llm = RecordedLLM(get_llm(settings, role="extraction"), calls, output / "model-calls.jsonl")
        stats = await extract_graph(
            session_factory=factory,
            llm=llm,
            domain=domain,
            batch_size=args.batch_size,
            rate_limit_s=0,
        )
        rules = [
            ProjectRule(r["rule"], (f"*/{r['id']}/*",))
            for r in payload["controls"]
            if r.get("rule")
        ]
        metadata = await classify_documents(factory=factory, domain=domain, llm=llm, rules=rules)
        repeated = await extract_graph(
            session_factory=factory,
            llm=llm,
            domain=domain,
            batch_size=args.batch_size,
            rate_limit_s=0,
        )
        async with factory() as session:
            documents = {d.id: d for d in (await session.scalars(select(Document))).all()}
            chunks = {c.id: c for c in (await session.scalars(select(Chunk))).all()}
            entities = {e.id: e for e in (await session.scalars(select(KgEntity))).all()}
            relationships = list((await session.scalars(select(KgRelationship))).all())
        per_case = []
        for row in payload["cases"]:
            doc_id = seed["ids"][row["id"]]
            expected_entities = {(normalize(name), kind) for name, kind in row["entities"]}
            mapped = {}
            predicted_entities = set()
            for entity in entities.values():
                if doc_id not in entity.document_ids:
                    continue
                forms = {normalize(n) for n in [entity.name, *entity.aliases]}
                candidates = [
                    name
                    for name, kind in expected_entities
                    if kind == entity.entity_type and name in forms
                ]
                name = candidates[0] if len(candidates) == 1 else normalize(entity.name)
                mapped[entity.id] = name
                predicted_entities.add((name, entity.entity_type))
            expected_relations = {
                (normalize(a), kind, normalize(b)) for a, kind, b in row["relations"]
            }
            predicted_relations = {
                (
                    mapped.get(r.source_entity_id, normalize(entities[r.source_entity_id].name)),
                    r.relation_type,
                    mapped.get(r.target_entity_id, normalize(entities[r.target_entity_id].name)),
                )
                for r in relationships
                if r.document_id == doc_id
            }
            per_case.append(
                dict(
                    id=row["id"],
                    split=row["split"],
                    entities=metrics(expected_entities, predicted_entities),
                    relations=metrics(expected_relations, predicted_relations),
                    ownership_correct=documents[doc_id].project_id
                    == seed["projects"][row["project"]],
                    ownership_source=documents[doc_id].project_source,
                )
            )
        controls = []
        for row in payload["controls"]:
            doc = documents[seed["ids"][row["id"]]]
            expected_id = seed["projects"].get(row["project"])
            controls.append(
                dict(
                    id=row["id"],
                    correct=doc.project_id == expected_id,
                    source=doc.project_source,
                    manual_tags=doc.tags,
                )
            )

        def aggregate(key: str, split: str) -> dict[str, Any]:
            selected = [r[key] for r in per_case if r["split"] == split or split == "all"]
            matched = sum(r["matched"] for r in selected)
            predicted = sum(r["predicted"] for r in selected)
            expected = sum(r["expected"] for r in selected)
            precision = matched / predicted if predicted else 0
            recall = matched / expected if expected else 0
            return dict(
                expected=expected,
                predicted=predicted,
                matched=matched,
                precision=precision,
                recall=recall,
                f1=2 * precision * recall / (precision + recall) if precision + recall else 0,
            )

        write_json(
            output / "extraction-checkpoint.json",
            dict(
                cases=per_case,
                controls=controls,
                extraction=asdict(stats),
                metadata=asdict(metadata),
                aggregate={
                    split: {key: aggregate(key, split) for key in ["entities", "relations"]}
                    for split in ["development", "heldout", "all"]
                },
            ),
        )
        qa = []
        scope = RetrievalScope(sources=("controlled-quality",), license_classes=("public",))
        for graph in [False, True]:
            retriever = FixedLayersRetriever(
                use_graph=graph, domain=domain, embedder=embedder, llm=llm, session_factory=factory
            )
            engine = AnswerEngine(settings=settings, retriever=retriever, llm=llm)
            for question in payload["questions"]:
                try:
                    result = await engine.answer(
                        question["question"],
                        profile="deep",
                        limit=8,
                        scope=scope,
                        include_compression=False,
                        max_tokens=1024,
                    )
                    cited_ids = {s.document_id for s in result.cited_sources}
                    cited_projects = {
                        name
                        for name, pid in seed["projects"].items()
                        if any(
                            doc_id in documents and documents[doc_id].project_id == pid
                            for doc_id in cited_ids
                        )
                    }
                    references = {s.index for s in result.cited_sources}
                    available_indices = {s.index for s in result.sources}
                    valid_refs = all(
                        int(value) in available_indices
                        for group in _CITATION_RE.findall(result.text)
                        for value in re.findall(r"\d+", group)
                    )
                    refusal = bool(
                        re.search(
                            r"未(?:提及|提供|包含|说明|记载)|没有|无法|不足|未能|不能|不清楚|not (?:contain|provided)|no information",
                            result.text,
                            re.I,
                        )
                    )
                    checks = dict(
                        terms=all(t in result.text for t in question.get("terms", [])),
                        forbidden_absent=not any(
                            t in result.text for t in question.get("forbidden", [])
                        ),
                        valid_references=valid_refs,
                        cited_expected_projects=set(question.get("cited_projects", []))
                        <= cited_projects,
                        citations_present=bool(references) or question.get("refusal", False),
                        refusal=refusal if question.get("refusal") else True,
                    )
                    qa.append(
                        dict(
                            id=question["id"],
                            configuration="kg" if graph else "rag",
                            text=result.text,
                            checks=checks,
                            mechanical_pass=all(checks.values()),
                            sources=[asdict(s) for s in result.sources],
                            degraded_stages=result.retrieval.degraded_stages,
                        )
                    )
                except Exception as exc:
                    qa.append(
                        dict(
                            id=question["id"],
                            configuration="kg" if graph else "rag",
                            error=type(exc).__name__,
                            mechanical_pass=False,
                        )
                    )
                write_json(output / "answers.json", qa)
        literal_failures = [
            r.id
            for r in relationships
            if not r.evidence
            or r.chunk_id not in chunks
            or "".join(r.evidence.casefold().split())
            not in "".join(chunks[r.chunk_id].content.casefold().split())
        ]
        summary = dict(
            label_status=payload["status"],
            domain_digest=domain_digest(args.domain),
            model=llm.describe(),
            embedding=embedder.version,
            extraction_batch_size=args.batch_size,
            extraction=asdict(stats),
            metadata=asdict(metadata),
            repeat_extraction=asdict(repeated),
            cases=per_case,
            controls=controls,
            aggregate={
                split: {key: aggregate(key, split) for key in ["entities", "relations"]}
                for split in ["development", "heldout", "all"]
            },
            positive_model_ownership=dict(
                correct=sum(r["ownership_correct"] for r in per_case), total=len(per_case)
            ),
            qa_mechanical={
                config: dict(
                    passed=sum(r["mechanical_pass"] for r in qa if r["configuration"] == config),
                    total=8,
                )
                for config in ["rag", "kg"]
            },
            literal_evidence_failures=literal_failures,
            protected_prompt_attempts=llm.blocked_attempts,
            caveats=[
                "Exact constructed-fact metrics; nonhuman provisional labels",
                "QA term/citation checks do not establish semantic correctness; inspect retained answers",
                "Small controlled comparison cannot establish general KG superiority",
            ],
        )
        write_json(output / "summary.json", summary)
        write_json(output / "model-calls.json", calls)
        write_json(
            output / "graph.json",
            dict(
                entities=[
                    dict(
                        id=e.id,
                        name=e.name,
                        type=e.entity_type,
                        aliases=e.aliases,
                        document_ids=e.document_ids,
                        chunk_ids=e.chunk_ids,
                    )
                    for e in entities.values()
                ],
                relationships=[
                    dict(
                        source=entities[r.source_entity_id].name,
                        type=r.relation_type,
                        target=entities[r.target_entity_id].name,
                        evidence=r.evidence,
                        document_id=r.document_id,
                        chunk_id=r.chunk_id,
                    )
                    for r in relationships
                ],
            ),
        )
        print(
            json.dumps(
                {
                    k: summary[k]
                    for k in [
                        "aggregate",
                        "positive_model_ownership",
                        "qa_mechanical",
                        "literal_evidence_failures",
                    ]
                }
            )
        )
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--phase", choices=["seed", "evaluate"], required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--domain", type=Path, required=True)
    parser.add_argument("--files", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--embedding-url", required=True)
    asyncio.run(run(parser.parse_args()))
