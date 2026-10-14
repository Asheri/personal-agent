"""Append-only campaign state for resumable network jobs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sci_rag.campaigns.discovery import normalize_doi


@dataclass(frozen=True)
class CampaignRecord:
    doi: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = ""


class CampaignState:
    """Read and durably append DOI status records in a JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: list[CampaignRecord] = []
        self.latest: dict[str, CampaignRecord] = {}
        self.truncated_final_line = False
        self._valid_size = 0
        self._needs_newline = False
        if path.exists():
            self._load()

    @property
    def processed_dois(self) -> set[str]:
        return set(self.latest)

    def is_processed(self, doi: str) -> bool:
        normalized = normalize_doi(doi)
        return normalized is not None and normalized in self.latest

    def append(
        self,
        *,
        doi: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        normalized = normalize_doi(doi)
        if normalized is None:
            raise ValueError(f"invalid DOI for campaign state: {doi!r}")
        status = status.strip()
        if not status:
            raise ValueError("campaign status must not be empty")
        record = CampaignRecord(
            doi=normalized,
            status=status,
            payload=dict(payload or {}),
            recorded_at=datetime.now(UTC).isoformat(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.truncated_final_line:
            with self.path.open("r+b") as handle:
                handle.truncate(self._valid_size)
                handle.flush()
                os.fsync(handle.fileno())
            self.truncated_final_line = False
        with self.path.open("a", encoding="utf-8") as handle:
            line = json.dumps(asdict(record), sort_keys=True) + "\n"
            if self._needs_newline:
                handle.write("\n")
                self._valid_size += 1
                self._needs_newline = False
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self._valid_size += len(line.encode("utf-8"))
        self._remember(record)

    def _load(self) -> None:
        lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, raw_line in enumerate(lines):
            if not raw_line.strip():
                self._valid_size += len(raw_line.encode("utf-8"))
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                is_truncated_final = index == len(lines) - 1 and not raw_line.endswith("\n")
                if is_truncated_final:
                    self.truncated_final_line = True
                    break
                raise ValueError(
                    f"{self.path.name} line {index + 1} is not valid JSON: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{self.path.name} line {index + 1} must be a JSON object")
            doi = normalize_doi(payload.get("doi", ""))
            status = payload.get("status")
            record_payload = payload.get("payload", {})
            recorded_at = payload.get("recorded_at", "")
            if (
                doi is None
                or not isinstance(status, str)
                or not status.strip()
                or not isinstance(record_payload, dict)
                or not isinstance(recorded_at, str)
            ):
                raise ValueError(f"{self.path.name} line {index + 1} has an invalid state record")
            self._remember(
                CampaignRecord(
                    doi=doi,
                    status=status.strip(),
                    payload=record_payload,
                    recorded_at=recorded_at,
                )
            )
            self._valid_size += len(raw_line.encode("utf-8"))
            if index == len(lines) - 1 and not raw_line.endswith("\n"):
                self._needs_newline = True

    def _remember(self, record: CampaignRecord) -> None:
        self.records.append(record)
        self.latest[record.doi] = record
