"""Offline OCR with an injectable engine and an optional native Tesseract route."""

from __future__ import annotations

import csv
import io
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from sci_rag.ingest.errors import ParserError
from sci_rag.ingest.parsers import Block, ParsedDocument

# `subprocess.CREATE_NO_WINDOW` exists on Windows only. `getattr` keeps the
# module importable, and type-checkable, on macOS and Linux.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class OcrEngine(Protocol):
    name: str

    def text_from_image(self, path: Path) -> tuple[str, float | None]: ...


class TesseractOcrEngine:
    name = "tesseract"

    def __init__(self) -> None:
        from sci_rag.config import get_settings

        settings = get_settings()
        self.command = settings.ocr_tesseract_cmd or shutil.which("tesseract")
        self.languages = settings.ocr_languages
        self.data_dir = settings.ocr_tessdata_dir
        if not self.command or not re.fullmatch(r"[A-Za-z0-9_+]+", self.languages):
            raise ParserError("ocr_unavailable", "ocr_image")

    def text_from_image(self, path: Path) -> tuple[str, float | None]:
        command = [str(self.command), str(path), "stdout", "-l", self.languages, "--psm", "6"]
        if self.data_dir is not None:
            command += ["--tessdata-dir", str(self.data_dir)]
        # Portable runtimes may contain traineddata without tessdata/configs/tsv.
        command += ["-c", "tessedit_create_tsv=1"]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=60,
                creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ParserError("ocr_unavailable", "ocr_image") from exc
        if result.returncode:
            raise ParserError("ocr_engine_failed", "ocr_image")
        lines: dict[tuple[str, ...], list[str]] = {}
        scores = []
        reader = csv.DictReader(io.StringIO(result.stdout.decode("utf-8-sig")), delimiter="\t")
        if not {"text", "conf"}.issubset(reader.fieldnames or []):
            raise ParserError("ocr_invalid_output", "ocr_image")
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            key = tuple(row.get(k, "") for k in ("page_num", "block_num", "par_num", "line_num"))
            lines.setdefault(key, []).append(text)
            try:
                score = float(row["conf"])
            except (KeyError, ValueError):
                continue
            if math.isfinite(score) and 0 <= score <= 100:
                scores.append(score / 100)
        # Tesseract emits word-level spaces between Han characters.
        body = "\n".join(" ".join(words) for words in lines.values())
        body = re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", "", body)
        return body, sum(scores) / len(scores) if scores else None


def _recognize(engine: OcrEngine, image: object, destination: Path) -> tuple[str, float | None]:
    image.save(destination)  # type: ignore[attr-defined]
    text, confidence = engine.text_from_image(destination)
    if not isinstance(text, str) or not text.strip():
        raise ParserError("ocr_no_text", "ocr_image")
    if confidence is not None and (
        not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ParserError("ocr_invalid_confidence", "ocr_image")
    return text.strip(), confidence


def parse_image(path: Path, engine: OcrEngine | None = None) -> ParsedDocument:
    engine = engine or TesseractOcrEngine()
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ParserError("ocr_unavailable", "ocr_image") from exc
    blocks = []
    scores = []
    with Image.open(path) as source, tempfile.TemporaryDirectory(prefix="pcmem-ocr-") as directory:
        for index in range(getattr(source, "n_frames", 1)):
            source.seek(index)
            with ImageOps.exif_transpose(source).convert("RGB") as image:
                text, confidence = _recognize(engine, image, Path(directory) / "page.png")
            blocks.extend(
                [
                    Block(kind="heading", text=f"Page {index + 1}", level=1),
                    Block(kind="text", text=text),
                ]
            )
            scores.append(confidence)
    return ParsedDocument(
        title=path.stem,
        blocks=blocks,
        page_count=len(scores),
        metadata={
            "parser": "ocr_image",
            "ocr": {"engine": engine.name, "pages": len(scores), "confidence": scores},
        },
    )


def scan_pages(
    path: Path, native: ParsedDocument, pages: list[int], engine: OcrEngine | None
) -> ParsedDocument:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ParserError("ocr_unavailable", "ocr_scan") from exc
    try:
        engine = engine or TesseractOcrEngine()
        texts = (native.raw_text or "").split("\f")
        scores = []
        with (
            pdfium.PdfDocument(path) as pdf,
            tempfile.TemporaryDirectory(prefix="pcmem-ocr-") as directory,
        ):
            for number in pages:
                page = pdf[number]
                try:
                    bitmap = page.render(scale=2.5)
                    try:
                        with bitmap.to_pil() as image:
                            text, confidence = _recognize(
                                engine, image, Path(directory) / "page.png"
                            )
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                texts[number] = text
                scores.append({"page": number + 1, "confidence": confidence})
        return ParsedDocument(
            title=native.title,
            raw_text="\f".join(texts),
            page_count=native.page_count,
            metadata={
                **native.metadata,
                "parser": "ocr_scan",
                "ocr": {"engine": engine.name, "pages": len(pages), "results": scores},
            },
        )
    except ParserError as exc:
        raise ParserError(exc.code, "ocr_scan") from exc
