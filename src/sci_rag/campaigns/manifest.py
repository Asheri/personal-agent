"""Write downloaded campaign works in the existing ingest manifest shape."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from sci_rag.campaigns.discovery import CandidateWork
from sci_rag.campaigns.resolve import OaResolution
from sci_rag.licensing import LICENSE_CLASSES


@dataclass(frozen=True)
class ManifestItem:
    work: CandidateWork
    resolution: OaResolution
    pdf_path: Path


def write_campaign_manifest(
    path: Path,
    items: list[ManifestItem],
    *,
    source: str,
) -> None:
    """Atomically replace a deterministic JSONL manifest for downloaded PDFs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", encoding="utf-8") as handle:
        for item in items:
            if item.resolution.license_class not in LICENSE_CLASSES:
                raise ValueError(f"invalid license class: {item.resolution.license_class}")
            license_signal = item.resolution.license_string or "unknown"
            row = {
                "path": os.path.relpath(item.pdf_path, path.parent),
                "title": item.work.title,
                "authors": item.work.authors,
                "year": item.work.year,
                "doi": item.work.doi,
                "journal": item.work.journal,
                "url": item.resolution.landing_page_url or item.resolution.pdf_url,
                "license_class": item.resolution.license_class,
                "license_source": f"unpaywall:{license_signal}",
                "source": source,
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()
    temporary.replace(path)
