"""Drafting a corpus manifest, without letting a model decide your rights.

Everything else in a manifest row is metadata a model can read off a title
page and a human can correct. `license_class` is different: it is the input
to a scoping boundary that decides what a public endpoint may quote. So the
drafter fails closed on it by construction, and these tests hold that line
against a model that asserts otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_rag.draft import DraftError
from sci_rag.draft.manifest import (
    DocumentHead,
    DraftedManifest,
    draft_manifest,
    parse_reply,
    read_heads,
    render_jsonl,
    render_prompt,
)
from sci_rag.llm import MockLLM

REPO_ROOT = Path(__file__).parents[2]
DOMAIN_DIR = REPO_ROOT / "domain"


def _corpus(tmp_path: Path) -> Path:
    folder = tmp_path / "raw"
    folder.mkdir()
    (folder / "colusa-2023.md").write_text(
        "# Colusa Basin Rice Straw Resource Assessment 2023\n\n"
        "Prepared by the Demo Region Biomass Office, 2023.\n\n"
        "This work is released under a Creative Commons CC-BY 4.0 license.\n\n"
        "The basin generated 302,000 dry tons of rice straw during the season.\n",
        encoding="utf-8",
    )
    (folder / "almond-guide.md").write_text(
        "# Almond Pruning and Orchard Residue Logistics Guide\n\n"
        "University Extension, 2022. doi:10.1000/demo.almond\n\n"
        "Mature almond blocks average 0.9 dry tons of prunings per acre.\n",
        encoding="utf-8",
    )
    return folder


_GOOD_REPLY = json.dumps(
    {
        "source_buckets": ["agency_reports", "extension_guides"],
        "documents": [
            {
                "filename": "colusa-2023.md",
                "title": "Colusa Basin Rice Straw Resource Assessment 2023",
                "authors": ["Demo Region Biomass Office"],
                "year": 2023,
                "source": "agency_reports",
                "license_statement": "This work is released under a Creative Commons CC-BY 4.0 license.",
            },
            {
                "filename": "almond-guide.md",
                "title": "Almond Pruning and Orchard Residue Logistics Guide",
                "authors": ["University Extension"],
                "year": 2022,
                "doi": "10.1000/demo.almond",
                "source": "extension_guides",
            },
        ],
    }
)


def test_heads_are_read_through_the_existing_parsers(tmp_path: Path) -> None:
    heads = read_heads(_corpus(tmp_path))

    assert [head.filename for head in heads] == ["almond-guide.md", "colusa-2023.md"]
    assert "302,000 dry tons" in next(h for h in heads if h.filename == "colusa-2023.md").text


def test_the_prompt_shows_the_title_the_parser_already_found(tmp_path: Path) -> None:
    """The markdown parser consumes the leading H1 into `title`, so the title
    is absent from the body text. Without this the model is asked to read a
    document title that was removed before it ever saw the document."""
    heads = read_heads(_corpus(tmp_path))
    prompt = render_prompt(DOMAIN_DIR, heads=heads, source_buckets=[])

    assert "Colusa Basin Rice Straw Resource Assessment 2023" in prompt


def test_a_row_with_no_title_falls_back_to_the_parsed_one(tmp_path: Path) -> None:
    """The parser's title is the file's own H1 or PDF metadata, not a guess."""
    heads = read_heads(_corpus(tmp_path))
    untitled = json.dumps({"documents": [{"filename": "colusa-2023.md"}]})

    result = parse_reply(untitled, heads=heads)

    (entry,) = result.entries
    assert entry.title == "Colusa Basin Rice Straw Resource Assessment 2023"


def test_the_prompt_carries_every_filename_and_the_buckets_so_far(tmp_path: Path) -> None:
    heads = read_heads(_corpus(tmp_path))
    prompt = render_prompt(DOMAIN_DIR, heads=heads, source_buckets=["agency_reports"])

    assert "colusa-2023.md" in prompt
    assert "almond-guide.md" in prompt
    assert "agency_reports" in prompt
    assert "302,000 dry tons" in prompt


def test_a_permissive_license_the_model_asserts_is_ignored(tmp_path: Path) -> None:
    """The whole point: rights are a human decision, never a model's."""
    heads = read_heads(_corpus(tmp_path))
    asserted = json.dumps(
        {
            "documents": [
                {
                    "filename": "colusa-2023.md",
                    "title": "Colusa Basin Rice Straw Resource Assessment 2023",
                    "license_class": "public",
                    "source": "agency_reports",
                }
            ]
        }
    )

    result = parse_reply(asserted, heads=heads)

    (entry,) = result.entries
    assert entry.license_class == "unknown"
    assert any("license" in note.lower() for note in result.notes)


def test_a_license_statement_found_verbatim_becomes_evidence_only(tmp_path: Path) -> None:
    heads = read_heads(_corpus(tmp_path))

    result = parse_reply(_GOOD_REPLY, heads=heads)

    colusa = next(e for e in result.entries if e.path.name == "colusa-2023.md")
    assert colusa.license_class == "unknown"
    assert colusa.license_source is not None
    assert "CC-BY 4.0" in colusa.license_source


def test_a_license_statement_the_document_does_not_contain_is_dropped(tmp_path: Path) -> None:
    """Fail closed on evidence too: an invented quote is not evidence."""
    heads = read_heads(_corpus(tmp_path))
    invented = json.dumps(
        {
            "documents": [
                {
                    "filename": "almond-guide.md",
                    "title": "Almond Pruning and Orchard Residue Logistics Guide",
                    "license_statement": "Released into the public domain by the authors.",
                }
            ]
        }
    )

    result = parse_reply(invented, heads=heads)

    (entry,) = result.entries
    assert entry.license_source is None
    assert any("not in the document" in note for note in result.notes)


def test_a_row_for_a_file_that_is_not_there_is_dropped(tmp_path: Path) -> None:
    heads = read_heads(_corpus(tmp_path))
    phantom = json.dumps({"documents": [{"filename": "nowhere.pdf", "title": "Phantom"}]})

    result = parse_reply(phantom, heads=heads)

    assert result.entries == []
    assert [name for name, _ in result.dropped] == ["nowhere.pdf"]


def test_every_row_resolves_to_a_real_path(tmp_path: Path) -> None:
    folder = _corpus(tmp_path)
    result = parse_reply(_GOOD_REPLY, heads=read_heads(folder))

    for entry in result.entries:
        assert entry.path.exists(), entry.path
        assert entry.path.is_absolute()


def test_a_non_json_reply_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DraftError, match="JSON"):
        parse_reply("sorry", heads=read_heads(_corpus(tmp_path)))


def test_source_buckets_are_shared_not_one_per_document(tmp_path: Path) -> None:
    heads = read_heads(_corpus(tmp_path))
    result = parse_reply(_GOOD_REPLY, heads=heads)

    assert set(result.source_buckets) == {"agency_reports", "extension_guides"}
    assert all(entry.source in result.source_buckets for entry in result.entries)


def test_the_rendered_manifest_reloads_through_the_real_loader(tmp_path: Path) -> None:
    from sci_rag.ingest.manifest import load_manifest

    folder = _corpus(tmp_path)
    result = parse_reply(_GOOD_REPLY, heads=read_heads(folder))
    manifest = tmp_path / "corpus.jsonl"
    manifest.write_text(render_jsonl(result.entries, manifest_path=manifest), encoding="utf-8")

    entries = load_manifest(manifest)
    assert {e.path.name for e in entries} == {"colusa-2023.md", "almond-guide.md"}
    assert all(e.license_class == "unknown" for e in entries)


def test_the_rights_decision_is_counted_and_surfaced(tmp_path: Path) -> None:
    result = parse_reply(_GOOD_REPLY, heads=read_heads(_corpus(tmp_path)))

    assert isinstance(result, DraftedManifest)
    assert result.needs_rights_decision == 2


async def test_drafting_batches_the_documents(tmp_path: Path) -> None:
    heads = read_heads(_corpus(tmp_path))
    llm = MockLLM(responses=[_GOOD_REPLY, _GOOD_REPLY])

    result = await draft_manifest(DOMAIN_DIR, heads=heads, llm=llm, batch_size=1)

    assert len(llm.calls) == 2, "one call per batch"
    assert {entry.path.name for entry in result.entries} == {
        "colusa-2023.md",
        "almond-guide.md",
    }


async def test_a_supplied_reply_is_used_instead_of_a_call(tmp_path: Path) -> None:
    heads = read_heads(_corpus(tmp_path))
    llm = MockLLM(responses=["should not be used"])

    result = await draft_manifest(DOMAIN_DIR, heads=heads, llm=llm, raw_reply=_GOOD_REPLY)

    assert llm.calls == []
    assert len(result.entries) == 2


def test_a_head_is_bounded_so_a_long_report_cannot_swamp_the_prompt(tmp_path: Path) -> None:
    folder = tmp_path / "raw"
    folder.mkdir()
    (folder / "long.md").write_text("# Long\n\n" + ("word " * 40000), encoding="utf-8")

    (head,) = read_heads(folder)

    assert isinstance(head, DocumentHead)
    assert len(head.text) <= 6000


def test_the_prompt_template_ships_with_the_domain() -> None:
    assert (DOMAIN_DIR / "prompts" / "manifest_metadata.md").exists()
