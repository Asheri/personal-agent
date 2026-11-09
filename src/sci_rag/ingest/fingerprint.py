"""Cheap change hints; a file fingerprint is not a content proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from stat import S_ISREG

from sci_rag.ingest.errors import PlaceholderFileError as PlaceholderFileError
from sci_rag.ingest.errors import check_placeholder
from sci_rag.ingest.manifest import CorpusEntry


@dataclass(frozen=True)
class SourceFingerprint:
    size: int
    mtime_ns: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def fingerprint(path: Path) -> SourceFingerprint:
    info = path.stat()
    # Windows OFFLINE, RECALL_ON_OPEN and RECALL_ON_DATA_ACCESS.
    check_placeholder(info)
    if not S_ISREG(info.st_mode):
        raise OSError("source_not_regular_file")
    return SourceFingerprint(info.st_size, info.st_mtime_ns)


def ingest_signature(
    entry: CorpusEntry, *, target_tokens: int, overlap_tokens: int, prefer_docling: bool
) -> str:
    payload = {
        "entry": entry.model_dump(mode="json", exclude={"path"}),
        "target_tokens": target_tokens,
        "overlap_tokens": overlap_tokens,
        "prefer_docling": prefer_docling,
        "format": 3,
    }
    from sci_rag.ingest.suffixes import IMAGE_SUFFIXES

    if entry.path.suffix.lower() in IMAGE_SUFFIXES | {".pdf"}:
        from sci_rag.config import get_settings

        settings = get_settings()
        payload["ocr"] = {
            "command": settings.ocr_tesseract_cmd,
            "data_dir": str(settings.ocr_tessdata_dir) if settings.ocr_tessdata_dir else None,
            "languages": settings.ocr_languages,
        }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
