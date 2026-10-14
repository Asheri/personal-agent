from sci_rag.ingest.chunker import chunk_document
from sci_rag.ingest.parsers import ParsedDocument, parse_markdown

MARKDOWN = """# Biomass Conversion Handbook

## 1 Introduction

Agricultural residues are an abundant feedstock for biofuel production.
Their availability varies strongly by county and by crop calendar.

## 2 Methods

### 2.1 Feedstock handling

Almond prunings are chipped in the field before transport. Moisture content
at collection typically ranges from 30 to 45 percent.

| Feedstock | Yield (t/ac) | Moisture (%) |
|-----------|--------------|--------------|
| Almond prunings | 1.2 | 38 |
| Rice straw | 2.9 | 22 |

Chipped material is screened to remove oversize particles before storage.
"""


def _chunks(markdown: str = MARKDOWN, **kwargs):  # type: ignore[no-untyped-def]
    doc = parse_markdown(markdown, fallback_title="fallback")
    return chunk_document(doc, **kwargs)


def test_title_comes_from_h1() -> None:
    doc = parse_markdown(MARKDOWN, fallback_title="fallback")
    assert doc.title == "Biomass Conversion Handbook"


def test_every_chunk_carries_a_breadcrumb() -> None:
    for chunk in _chunks():
        first_line = chunk.content.splitlines()[0]
        assert first_line.startswith("Biomass Conversion Handbook")


def test_section_paths_track_heading_hierarchy() -> None:
    chunks = _chunks()
    paths = [c.section_path for c in chunks]
    assert "1 Introduction" in paths
    assert any(p == "2 Methods > 2.1 Feedstock handling" for p in paths)


def test_tables_are_isolated_and_intact() -> None:
    tables = [c for c in _chunks() if c.is_table]
    assert len(tables) == 1
    assert "Almond prunings" in tables[0].body
    assert "Rice straw" in tables[0].body
    # The table header never bleeds into a prose chunk. (Up to two trailing
    # data rows may carry over as bounded overlap; that is by design.)
    for chunk in _chunks():
        if not chunk.is_table:
            assert "| Feedstock |" not in chunk.content
            assert "|---" not in chunk.content


def test_chunks_do_not_span_sections() -> None:
    for chunk in _chunks():
        assert "Introduction" not in chunk.body or "chipped" not in chunk.body.lower()


def test_overlap_carries_tail_into_next_chunk() -> None:
    # Force tiny chunks so the same section splits into several.
    long_section = "# T\n\n## S\n\n" + "\n\n".join(
        f"Sentence number {i} talks about biomass logistics in detail." for i in range(12)
    )
    doc = parse_markdown(long_section, fallback_title="T")
    chunks = chunk_document(doc, target_tokens=40, overlap_tokens=15)
    assert len(chunks) >= 2
    # The start of chunk N+1 repeats the tail of chunk N.
    tail_sentence = chunks[0].body.split("Sentence")[-1]
    marker = f"Sentence{tail_sentence.split('.')[0]}."
    assert marker in chunks[1].body


def test_overlap_does_not_cross_headings() -> None:
    md = (
        "# T\n\n## A\n\nAlpha content sentence one. Alpha content sentence two.\n\n"
        "## B\n\nBeta content only here."
    )
    doc = parse_markdown(md, fallback_title="T")
    chunks = chunk_document(doc, target_tokens=30, overlap_tokens=20)
    beta = [c for c in chunks if c.section_path == "B"]
    assert beta and all("Alpha" not in c.body for c in beta)


def test_oversized_paragraph_splits_on_sentences() -> None:
    huge = " ".join(f"This is sentence {i} about pretreatment chemistry." for i in range(80))
    doc = ParsedDocument(title="T", raw_text=huge)
    chunks = chunk_document(doc, target_tokens=100, overlap_tokens=0)
    assert len(chunks) > 1
    assert all(c.token_count <= 160 for c in chunks)  # header adds a little


def test_raw_text_heading_and_table_heuristics() -> None:
    raw = (
        "2.1 Feedstock Supply\n\n"
        "Rice straw is collected after harvest and baled for storage. The bales are wrapped.\n\n"
        "Feedstock\tYield\tMoisture\nRice straw\t2.9\t22\nAlmond\t1.2\t38\n\n"
        "MATERIALS AND METHODS\n\n"
        "Samples were dried at 105 degrees Celsius until mass stabilized overnight."
    )
    doc = ParsedDocument(title="Report", raw_text=raw)
    chunks = chunk_document(doc)
    assert any(c.is_table for c in chunks)
    paths = {c.section_path for c in chunks}
    assert "2.1 Feedstock Supply" in paths
    assert "MATERIALS AND METHODS" in paths


def test_chunking_is_deterministic() -> None:
    a = [c.content for c in _chunks()]
    b = [c.content for c in _chunks()]
    assert a == b


def test_dehyphenation_and_page_numbers() -> None:
    raw = "Fermentation of ligno-\ncellulosic feedstocks is challenging for many reasons.\n\n42\n\nThe process continues normally afterward with steady conversion rates."
    doc = ParsedDocument(title="T", raw_text=raw)
    chunks = chunk_document(doc)
    joined = " ".join(c.body for c in chunks)
    assert "lignocellulosic" in joined
    assert "\n42\n" not in joined
