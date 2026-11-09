"""Persist content-free parser totals without storing paths, headers, or text."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sci_rag.reconcile import ReconcileReport


def write_parser_summary(report: ReconcileReport, directory: Path | None = None) -> Path:
    directory = directory or Path.cwd() / ".context/ingest-reports"
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    target = directory / ("summary-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    target.write_text(
        json.dumps(
            {
                "created_at": now.isoformat(),
                "unit": "source files; unchanged sources are skipped, not parsed",
                "parsers": report.parser_counts(),
                "source_files": len(report.source_outcomes),
                "failed": report.failed,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target
