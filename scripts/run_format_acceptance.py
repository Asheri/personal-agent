"""Build controlled fixtures and exercise every declared suffix on a disposable DB."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from sci_rag.config import get_settings
from sci_rag.db import Base, Chunk, Document, dispose_engine, get_engine, get_session_factory
from sci_rag.embed import LocalHashEmbedder
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.ingest.parsers import parse_file
from sci_rag.ingest.suffixes import CODE_SUFFIXES, DATA_SUFFIXES, IMAGE_SUFFIXES, SUPPORTED_SUFFIXES
from sci_rag.reconcile import reconcile_entries
from sci_rag.retrieve import RetrievalScope
from sci_rag.retrieve.stages.keyword import keyword_stage

MARKER = "TYPES2026"
CHINESE = ["知识图谱课程资料", "星河项目负责人陈林", "实验编号 TYPES2026"]


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def image_lines(lines: list[str], font: Path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 320), "white")
    draw = ImageDraw.Draw(image)
    face = ImageFont.truetype(str(font), 48)
    for i, line in enumerate(lines):
        draw.text((48, 32 + 84 * i), line, font=face, fill="black")
    return image


def native_pdf(path: Path, scan: Path | None = None) -> None:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 14 Tf 30 200 Td (Native evidence TYPES2026 KEEP_NATIVE_TOKEN belongs to the controlled project.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    if scan:
        writer.add_page(PdfReader(scan).pages[0])
    writer.write(path)


def build_fixtures(folder: Path, font: Path) -> list[Path]:
    import mailbox
    from email.message import EmailMessage

    folder.mkdir(parents=True, exist_ok=True)
    body = "星河项目的受控资料，负责人陈林。编号 " + MARKER + "。"  # noqa: RUF001
    for suffix in SUPPORTED_SUFFIXES:
        path = folder / ("record" + suffix)
        if suffix in CODE_SUFFIXES:
            source = (
                "// Controlled source "
                + MARKER
                + '\nfunction record() { return "'
                + MARKER
                + '"; }\n'
            )
            if suffix in {".py", ".pyi"}:
                source = (
                    '"""Controlled source '
                    + MARKER
                    + '."""\ndef record(value: int) -> str:\n    return "'
                    + MARKER
                    + '"\n'
                )
            path.write_text(source, encoding="utf-8")
        elif suffix in DATA_SUFFIXES:
            data = {
                ".csv": "项目,编号\n星河," + MARKER + "\n",
                ".tsv": "项目\t编号\n星河\t" + MARKER + "\n",
                ".json": json.dumps({"project": "星河", "record": MARKER}, ensure_ascii=False),
                ".jsonl": '{"record":"' + MARKER + '"}\n{"value":0}\n',
                ".yaml": "project: 星河\nrecord: " + MARKER + "\n",
                ".yml": "record: " + MARKER + "\n",
            }
            path.write_text(data[suffix], encoding="utf-8")
        elif suffix in IMAGE_SUFFIXES:
            with image_lines(CHINESE, font) as image:
                if suffix == ".tiff":
                    with image_lines(
                        ["会议记录", "海岚项目使用声学建模", "实验编号 " + MARKER], font
                    ) as second:
                        image.save(path, save_all=True, append_images=[second])
                else:
                    image.save(path)
        elif suffix in {".md", ".markdown"}:
            path.write_text("# Controlled " + MARKER + "\n\n" + body, encoding="utf-8")
        elif suffix in {".html", ".htm"}:
            path.write_text("<html><body><p>" + body + "</p></body></html>", encoding="utf-8")
        elif suffix == ".txt":
            path.write_text(body, encoding="utf-8")
        elif suffix == ".pdf":
            native_pdf(path)
        elif suffix == ".docx":
            from docx import Document as WordDocument

            doc = WordDocument()
            doc.add_paragraph(body)
            table = doc.add_table(rows=2, cols=2)
            table.cell(0, 0).text = "项目"
            table.cell(0, 1).text = "编号"
            table.cell(1, 0).text = "星河"
            table.cell(1, 1).text = MARKER
            doc.save(path)
        elif suffix == ".pptx":
            from pptx import Presentation
            from pptx.util import Inches

            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.shapes.add_textbox(
                Inches(1), Inches(1), Inches(8), Inches(3)
            ).text_frame.text = body
            deck.save(path)
        elif suffix == ".xlsx":
            from openpyxl import Workbook

            book = Workbook()
            sheet = book.active
            sheet.append(["项目", "编号", "值"])
            sheet.append(["星河", MARKER, 0])
            book.save(path)
            book.close()
        else:

            def message(index: int) -> EmailMessage:
                msg = EmailMessage()
                msg["From"] = "fixture@example.invalid"
                msg["Subject"] = f"Controlled message {index}"
                msg["Message-ID"] = f"<format-{index}@example.invalid>"
                msg["Date"] = "Sun, 25 Oct 2026 09:00:00 +0800"
                msg.set_content(body)
                return msg

            if suffix == ".eml":
                path.write_bytes(message(0).as_bytes())
            else:
                if path.exists():
                    path.unlink()
                box = mailbox.mbox(path)
                for i in range(3):
                    box.add(message(i + 1))
                box.flush()
                box.close()
    with image_lines(CHINESE, font) as image:
        scan = folder.parent / "scan-fixture.pdf"
        image.save(scan, "PDF")
    native_pdf(folder / "mixed.pdf", scan)
    return sorted(folder.iterdir())


def distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(row[j] + 1, next_row[-1] + 1, row[j - 1] + (x != y)))
        row = next_row
    return row[-1]


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.database_url != os.environ.get("SCI_RAG_TEST_DATABASE_URL")
        or url.host != "127.0.0.1"
        or not (url.database or "").endswith("_test")
    ):
        raise ValueError("Explicit loopback disposable _test database required")
    args.output.mkdir(parents=True, exist_ok=True)
    files = build_fixtures(args.fixtures, args.font)
    assert {p.suffix for p in files} == SUPPORTED_SUFFIXES
    # Freeze effect thresholds before invoking the native OCR engine.
    save_json(
        args.output / "ocr-preregistration.json",
        {
            "character_accuracy_min": 0.90,
            "per_page_seconds_max": 10,
            "labels": "Constructed exact fixture text, not a human-reviewed field benchmark",
            "font_sha256": hashlib.sha256(args.font.read_bytes()).hexdigest(),
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        },
    )
    cases = []
    for suffix in [".png", ".jpg", ".webp"]:
        path = args.fixtures / ("record" + suffix)
        started = time.perf_counter()
        parsed = parse_file(path)
        actual = "".join(b.text for b in parsed.blocks or [] if b.kind == "text")
        expected = "".join(CHINESE)
        actual = "".join(actual.split())
        expected = "".join(expected.split())
        accuracy = max(0, 1 - distance(expected, actual) / len(expected))
        cases.append(
            dict(
                suffix=suffix,
                text=actual,
                expected=expected,
                accuracy=accuracy,
                seconds=time.perf_counter() - started,
                metadata=parsed.metadata,
            )
        )
    save_json(args.output / "ocr-effect.json", cases)
    assert all(c["accuracy"] >= 0.90 and c["seconds"] <= 10 for c in cases), (
        "OCR effect gate failed; inspect retained results"
    )
    async with get_engine().begin() as c:
        await c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)

    class CountedEmbedder(LocalHashEmbedder):
        calls = 0

        async def embed(self, texts, *, task):
            self.calls += 1
            return await super().embed(texts, task=task)

    embedder = CountedEmbedder(settings.embedding_dim)
    entries = [
        CorpusEntry(path=p, source="controlled-file-types", license_class="public") for p in files
    ]
    report = await ingest_entries(entries, embedder=embedder, prefer_docling=False)
    save_json(args.output / "ingestion.json", asdict(report))
    assert report.failed == 0
    factory = get_session_factory()
    async with factory() as session:
        document_count = await session.scalar(select(func.count(Document.id)))
        assert document_count == len(files) + 2  # One three-message mailbox adds two rows.
        assert await session.scalar(select(func.count(Chunk.id)).where(Chunk.is_table)) >= 3
        rows = list((await session.scalars(select(Document))).all())
        assert all(d.extra.get("parser") for d in rows)
        assert (
            next(d for d in rows if d.extra["path"].endswith("mixed.pdf")).extra["ocr"]["results"][
                0
            ]["page"]
            == 2
        )
    before = embedder.calls
    repeated = await reconcile_entries(
        entries,
        root=args.fixtures,
        session_factory=factory,
        embedder=embedder,
        prefer_docling=False,
    )
    assert repeated.counts()["unchanged"] == len(files) and embedder.calls == before
    hits = await keyword_stage(factory, MARKER, RetrievalScope(license_classes=("public",)), 200)
    mixed_hits = await keyword_stage(
        factory, "编号 " + MARKER, RetrievalScope(license_classes=("public",)), 200
    )
    async with factory() as session:
        english_found = set(
            (
                await session.scalars(
                    select(Chunk.document_id).where(Chunk.id.in_([k for _, k in hits]))
                )
            ).all()
        )
        mixed_found = set(
            (
                await session.scalars(
                    select(Chunk.document_id).where(Chunk.id.in_([k for _, k in mixed_hits]))
                )
            ).all()
        )
        found = english_found | mixed_found
        body_found = set(
            (
                await session.scalars(
                    select(Chunk.document_id).where(Chunk.content.contains(MARKER))
                )
            ).all()
        )
        assert len(body_found) == document_count, "A parser dropped the source marker"
        missing = []
        for document in rows:
            if document.id not in found:
                chunks = list(
                    (
                        await session.scalars(select(Chunk).where(Chunk.document_id == document.id))
                    ).all()
                )
                missing.append(
                    dict(
                        path=document.extra["path"],
                        parser=document.extra["parser"],
                        texts=[c.content for c in chunks],
                    )
                )
    save_json(
        args.output / "keyword-diagnostic.json", dict(hit_documents=len(found), missing=missing)
    )
    assert len(found) == document_count, "Some formats were absent from both keyword query routes"
    save_json(
        args.output / "summary.json",
        dict(
            suffixes=sorted(SUPPORTED_SUFFIXES),
            source_files=len(files),
            documents=document_count,
            keyword_hit_documents=len(found),
            keyword_queries={
                "english": {"query": MARKER, "documents": len(english_found)},
                "mixed": {"query": "编号 " + MARKER, "documents": len(mixed_found)},
            },
            keyword_limit="Union of two existing query routes; pure English marker next to Chinese punctuation can miss documents",
            body_marker_documents=len(body_found),
            unchanged_sources=repeated.counts()["unchanged"],
            repeat_embedding_calls=embedder.calls - before,
            ocr_cases=cases,
            native_runtime="Tesseract, offline CPU",
            embedding="local-hash, pipeline mechanics only; no semantic quality claim",
            license_note="Controlled fixtures explicitly public; ordinary folder/manifest defaults remain unknown",
            parser_counts=repeated.parser_counts(),
            status="Controlled acceptance; independent review pending",
        ),
    )
    print(
        json.dumps(
            {
                "source_files": len(files),
                "documents": document_count,
                "keyword_hit_documents": len(found),
                "ocr_accuracy": [c["accuracy"] for c in cases],
                "ocr_seconds": [c["seconds"] for c in cases],
            }
        )
    )
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
