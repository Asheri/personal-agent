from sci_rag.retrieve.stages.keyword import _english_search_terms


def test_long_english_question_becomes_or_terms() -> None:
    terms = _english_search_terms(
        "How have Uber's Adjusted EBITDA and its margin as a percentage of "
        "Gross Bookings trended on a quarterly basis, and what key drivers "
        "have contributed to these trends?"
    )
    lowered = [term.casefold() for term in terms]
    assert "adjusted" in lowered
    assert "ebitda" in lowered
    assert "gross" in lowered
    assert "uber" in lowered
    # The default websearch AND would require every one of these words.
    assert "the" not in lowered
    assert "and" not in lowered
    assert len(terms) >= 8


def test_english_identifiers_survive() -> None:
    terms = _english_search_terms("Compare Q3-2024 with Q2-2025 and PC-2026-047")
    assert "Q3-2024" in terms
    assert "Q2-2025" in terms
    assert "PC-2026-047" in terms
