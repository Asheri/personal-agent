"""Document date precedence, independent of publication year."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
    return None


def document_date(
    metadata: dict[str, Any], mtime_ns: int | None, ingested_at: datetime | None = None
) -> tuple[date, str]:
    mail = _date(metadata.get("email_datetime"))
    if mail is None and str(metadata.get("doc_date_source", "")).startswith("email"):
        mail = _date(metadata.get("doc_date"))
    if mail is not None:
        return mail, "email_header"
    modified = _date(metadata.get("modified"))
    if modified is not None:
        return modified, "doc_property"
    if mtime_ns is not None:
        try:
            return datetime.fromtimestamp(mtime_ns / 1_000_000_000, UTC).date(), "file_mtime"
        except (OverflowError, OSError, ValueError):
            pass
    return (ingested_at or datetime.now(UTC)).date(), "ingested_at"
