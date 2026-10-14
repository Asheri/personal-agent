import json
from pathlib import Path

import pytest

from sci_rag.ingest import discover_folder, load_manifest
from sci_rag.licensing import EXTERNAL_SAFE_CLASSES, normalize_license_class


def test_license_normalization_aliases() -> None:
    assert normalize_license_class("CC-BY") == "open_commercial"
    assert normalize_license_class("cc0") == "public"
    assert normalize_license_class("US gov") == "public"
    assert normalize_license_class("CC BY-NC") == "open_noncommercial"
    assert normalize_license_class("paywalled") == "restricted"


def test_unrecognized_values_fail_closed_to_unknown() -> None:
    assert normalize_license_class(None) == "unknown"
    assert normalize_license_class("MIT-ish") == "unknown"
    assert "unknown" not in EXTERNAL_SAFE_CLASSES


def test_manifest_roundtrip(tmp_path: Path) -> None:
    doc = tmp_path / "report.txt"
    doc.write_text("Rice straw yields were measured across three seasons in the valley.")
    manifest = tmp_path / "corpus.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "path": "report.txt",
                "title": "Rice Straw Report",
                "authors": ["Ag Dept"],
                "year": 2023,
                "license_class": "CC-BY",
                "source": "demo",
            }
        )
        + "\n# a comment line\n\n"
    )
    [entry] = load_manifest(manifest)
    assert entry.path == doc.resolve()
    assert entry.license_class == "open_commercial"
    assert entry.source == "demo"


def test_manifest_rejects_bad_json(tmp_path: Path) -> None:
    manifest = tmp_path / "corpus.jsonl"
    manifest.write_text("{not json}\n")
    with pytest.raises(ValueError, match="line 1"):
        load_manifest(manifest)


def test_discover_folder_finds_supported_files_only(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("text")
    (tmp_path / "b.md").write_text("# md")
    (tmp_path / "c.docx").write_text("nope")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "d.pdf").write_bytes(b"%PDF-1.4 fake")
    entries = discover_folder(tmp_path, source="demo")
    names = sorted(e.path.name for e in entries)
    assert names == ["a.txt", "b.md", "d.pdf"]
    assert all(e.source == "demo" for e in entries)
