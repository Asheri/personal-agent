import json
from pathlib import Path

import pytest

from sci_rag.enrich import parse_crossref_work

FIXTURES = Path(__file__).parents[1] / "fixtures" / "campaigns"


def _work(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())["message"]


def test_crossref_parser_marks_an_explicit_retraction() -> None:
    metadata = parse_crossref_work(_work("crossref_retracted.json"))  # type: ignore[arg-type]

    assert metadata.is_retracted is True
    assert metadata.retraction_notice_doi == "10.1000/retraction-notice"
    assert metadata.citation_count == 17
    assert metadata.journal == "Journal of Reproducible Results"


def test_crossref_parser_accepts_current_updated_by_direction() -> None:
    metadata = parse_crossref_work(  # type: ignore[arg-type]
        _work("crossref_retracted_updated_by.json")
    )

    assert metadata.is_retracted is True
    assert metadata.retraction_notice_doi == "10.1021/acsami.9b11759"
    assert metadata.journal == "ACS Applied Materials & Interfaces"


def test_crossref_parser_does_not_infer_retraction_from_missing_notices() -> None:
    metadata = parse_crossref_work(_work("crossref_current.json"))  # type: ignore[arg-type]

    assert metadata.is_retracted is False
    assert metadata.retraction_notice_doi is None
    assert metadata.citation_count == 0
    assert metadata.journal is None


def test_crossref_parser_caches_normalized_reference_dois() -> None:
    work = _work("crossref_current.json")
    work["reference"] = [
        {"DOI": "https://doi.org/10.1000/Cited"},
        {"DOI": "10.1000/cited"},
        {"article-title": "Reference without DOI"},
    ]

    metadata = parse_crossref_work(work)  # type: ignore[arg-type]

    assert metadata.reference_dois == ("10.1000/cited",)


def test_crossref_parser_rejects_malformed_update_notices() -> None:
    with pytest.raises(ValueError, match="update-to"):
        parse_crossref_work(_work("crossref_malformed.json"))  # type: ignore[arg-type]
