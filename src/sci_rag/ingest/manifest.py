"""The corpus manifest: one line of JSON per document.

A manifest is how you tell the kit what you know about your documents:
where the file lives, who wrote it, when, under what license. Everything
except ``path`` is optional; the kit does something sensible with whatever
you provide. You can also skip the manifest entirely and point ``ingest``
at a folder, which auto-builds an entry per supported file.

Example line::

    {"path": "data/raw/fresno_2023.pdf", "title": "Fresno County Crop Report 2023",
     "authors": ["Fresno County Dept. of Agriculture"], "year": 2023,
     "license_class": "public", "source": "county_ag_reports"}

:func:`load_manifest` reads one for ingestion. :func:`lint_manifest` checks one
without ingesting it, and deliberately does not reuse the loader: see its
docstring for the two reasons why.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from sci_rag.ingest.parsers import SUPPORTED_SUFFIXES
from sci_rag.licensing import LICENSE_CLASSES, normalize_license_class


class CorpusEntry(BaseModel):
    path: Path
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    url: str | None = None
    license_class: str = "unknown"
    license_source: str | None = None
    source: str = "local"

    @field_validator("license_class", mode="before")
    @classmethod
    def _normalize_license(cls, value: str | None) -> str:
        return normalize_license_class(value)


def load_manifest(manifest_path: Path) -> list[CorpusEntry]:
    """Read a JSONL manifest. Paths are resolved relative to the manifest file."""
    entries: list[CorpusEntry] = []
    base = manifest_path.parent
    for line_number, line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{manifest_path.name} line {line_number} is not valid JSON: {exc}"
            ) from exc
        entry = CorpusEntry.model_validate(data)
        if not entry.path.is_absolute():
            entry.path = (base / entry.path).resolve()
        entries.append(entry)
    return entries


def discover_folder(folder: Path, *, source: str = "local") -> list[CorpusEntry]:
    """Build manifest entries for every supported file under a folder."""
    entries = [
        CorpusEntry(path=path.resolve(), source=source)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return entries


LintLevel = Literal["error", "warning"]


@dataclass(frozen=True)
class LintFinding:
    """One problem, anchored to the manifest line that caused it."""

    line: int
    level: LintLevel
    code: str
    message: str


@dataclass
class LintReport:
    path: Path
    findings: list[LintFinding] = field(default_factory=list)
    entry_count: int = 0

    @property
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[LintFinding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        """Warnings do not fail a manifest; unknown keys are forward compatibility."""
        return not self.errors


def lint_manifest(manifest_path: Path) -> LintReport:
    """Check a manifest without ingesting it, collecting every problem at once.

    :func:`load_manifest` is the wrong tool for this even though it parses the
    same file. It raises on the first malformed line, so it can only ever report
    one problem; and ``CorpusEntry`` normalizes an unrecognized ``license_class``
    to ``unknown``, which is right for ingestion and destroys exactly the mistake
    a linter exists to catch. So this walks the raw lines under the same rules
    (blank and ``#`` lines skipped, paths resolved against the manifest's own
    directory) and validates through the same model.
    """
    report = LintReport(path=manifest_path)
    first_seen: dict[Path, int] = {}
    base = manifest_path.parent

    for line_number, raw_line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            report.findings.append(
                LintFinding(line_number, "error", "invalid_json", f"not valid JSON: {exc.msg}")
            )
            continue

        if not isinstance(data, dict):
            report.findings.append(
                LintFinding(
                    line_number,
                    "error",
                    "not_an_object",
                    f"expected a JSON object, found {type(data).__name__}",
                )
            )
            continue

        report.entry_count += 1
        _lint_unknown_keys(data, line_number, report)
        _lint_license_class(data, line_number, report)

        try:
            entry = CorpusEntry.model_validate(data)
        except ValidationError as exc:
            for error in exc.errors():
                field_name = ".".join(str(part) for part in error["loc"]) or "entry"
                report.findings.append(
                    LintFinding(
                        line_number, "error", "invalid_field", f"{field_name}: {error['msg']}"
                    )
                )
            continue

        _lint_title(entry, line_number, report)
        resolved = entry.path if entry.path.is_absolute() else (base / entry.path).resolve()
        _lint_path(resolved, line_number, report, first_seen)

    return report


def _lint_unknown_keys(data: dict[str, Any], line_number: int, report: LintReport) -> None:
    """A key the model ignores is a typo more often than it is a future field."""
    unknown = sorted(set(data) - set(CorpusEntry.model_fields))
    if unknown:
        report.findings.append(
            LintFinding(
                line_number,
                "warning",
                "unknown_key",
                f"ignored by the loader: {', '.join(unknown)}",
            )
        )


def _lint_license_class(data: dict[str, Any], line_number: int, report: LintReport) -> None:
    """Catch the value before ``CorpusEntry`` normalizes it away.

    Fail-closed means an unrecognized class silently becomes ``unknown``, which
    is the safe behavior at ingestion and a silent demotion here: a document the
    author believed was ``CC-BY`` gets scoped as if nobody had said anything.
    """
    declared = data.get("license_class")
    if declared is None:
        return
    if not isinstance(declared, str):
        return  # The model's own validation reports the type error.
    if normalize_license_class(declared) == "unknown" and declared.strip().lower() != "unknown":
        report.findings.append(
            LintFinding(
                line_number,
                "error",
                "unknown_license_class",
                f"{declared!r} is not a license class, so it would scope as 'unknown'. "
                f"Known: {', '.join(LICENSE_CLASSES)}",
            )
        )


def _lint_title(entry: CorpusEntry, line_number: int, report: LintReport) -> None:
    """A missing title becomes the filename stem in every citation of the document."""
    if entry.title is None or not entry.title.strip():
        report.findings.append(
            LintFinding(
                line_number,
                "error",
                "missing_title",
                f"no title, so citations would read {entry.path.stem!r}",
            )
        )


def _lint_path(
    resolved: Path, line_number: int, report: LintReport, first_seen: dict[Path, int]
) -> None:
    if resolved in first_seen:
        report.findings.append(
            LintFinding(
                line_number,
                "error",
                "duplicate_path",
                f"{resolved.name} is already claimed by line {first_seen[resolved]}",
            )
        )
        return
    first_seen[resolved] = line_number

    if not resolved.is_file():
        report.findings.append(
            LintFinding(line_number, "error", "missing_file", f"no file at {resolved}")
        )
        return

    if resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
        report.findings.append(
            LintFinding(
                line_number,
                "error",
                "unsupported_file_type",
                f"{resolved.suffix or 'no extension'} cannot be parsed. "
                f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}",
            )
        )
