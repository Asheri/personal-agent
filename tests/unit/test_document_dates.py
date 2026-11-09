"""Document dates use source evidence rather than publication-year guesses."""

from datetime import UTC, date, datetime

import pytest

from sci_rag.document_dates import document_date


@pytest.mark.parametrize(
    "metadata,mtime,expected,source",
    [
        (
            {"email_datetime": "2026-02-03T04:05:00+08:00", "modified": "2025-01-01"},
            0,
            date(2026, 2, 3),
            "email_header",
        ),
        (
            {"doc_date": "2026-03-04", "doc_date_source": "email_date_header"},
            0,
            date(2026, 3, 4),
            "email_header",
        ),
        ({"modified": "2024-01-02T23:00:00"}, 0, date(2024, 1, 2), "doc_property"),
        ({"modified": "invalid"}, 0, date(1970, 1, 1), "file_mtime"),
        ({}, None, date(2026, 1, 1), "ingested_at"),
    ],
)
def test_date_precedence(metadata, mtime, expected, source):
    assert document_date(metadata, mtime, datetime(2026, 1, 1, tzinfo=UTC)) == (expected, source)
