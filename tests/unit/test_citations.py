from sci_rag.citations import normalize_doi, reference_dois_from_crossref


def test_normalize_doi_accepts_common_crossref_forms() -> None:
    assert normalize_doi(" DOI:10.1000/ABC.123 ") == "10.1000/abc.123"
    assert normalize_doi("https://doi.org/10.5555/Some.Path") == "10.5555/some.path"
    assert normalize_doi("http://dx.doi.org/10.1234/X-1.") == "10.1234/x-1"


def test_normalize_doi_rejects_non_doi_values() -> None:
    assert normalize_doi("") is None
    assert normalize_doi("not-a-doi") is None
    assert normalize_doi(None) is None


def test_reference_dois_collapse_duplicates_and_ignore_malformed_entries() -> None:
    work = {
        "reference": [
            {"DOI": "10.1000/Target"},
            {"DOI": "https://doi.org/10.1000/target"},
            {"DOI": "not-a-doi"},
            {"article-title": "No DOI"},
        ]
    }

    assert reference_dois_from_crossref(work) == ["10.1000/target"]


def test_reference_parser_rejects_a_malformed_reference_list() -> None:
    try:
        reference_dois_from_crossref({"reference": "not-a-list"})
    except ValueError as exc:
        assert "reference" in str(exc)
    else:
        raise AssertionError("malformed Crossref references must fail visibly")
