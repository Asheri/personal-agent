from __future__ import annotations

from pathlib import Path

from sci_rag.campaigns.discovery import CandidateWork
from sci_rag.campaigns.manifest import ManifestItem, write_campaign_manifest
from sci_rag.campaigns.resolve import OaResolution
from sci_rag.ingest import load_manifest
from sci_rag.licensing import LICENSE_CLASSES


def _resolution(doi: str, license_class: str, license_string: str | None) -> OaResolution:
    return OaResolution(
        doi=doi,
        is_oa=True,
        oa_status="green",
        license_string=license_string,
        license_class=license_class,
        pdf_url=f"https://repository.example.org/{doi}.pdf",
        landing_page_url=f"https://repository.example.org/{doi}",
    )


def test_campaign_manifest_round_trips_through_ingest_reader(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    first_pdf = pdf_dir / "first.pdf"
    second_pdf = pdf_dir / "second.pdf"
    first_pdf.write_bytes(b"%PDF-first")
    second_pdf.write_bytes(b"%PDF-second")
    items = [
        ManifestItem(
            work=CandidateWork(
                doi="10.7717/peerj.4375",
                title="The state of OA",
                year=2018,
                authors=["Heather Piwowar", "Jason Priem"],
                journal="PeerJ",
                source="openalex",
            ),
            resolution=_resolution("10.7717/peerj.4375", "open_commercial", "cc-by"),
            pdf_path=first_pdf,
        ),
        ManifestItem(
            work=CandidateWork(
                doi="10.1038/s41586-020-2649-2",
                title="Array programming with NumPy",
                year=2020,
                source="openalex",
            ),
            resolution=_resolution("10.1038/s41586-020-2649-2", "unknown", None),
            pdf_path=second_pdf,
        ),
    ]
    manifest_path = tmp_path / "corpus.jsonl"

    write_campaign_manifest(manifest_path, items, source="campaign:test")
    entries = load_manifest(manifest_path)

    assert [entry.path for entry in entries] == [first_pdf.resolve(), second_pdf.resolve()]
    assert [entry.license_class for entry in entries] == ["open_commercial", "unknown"]
    assert all(entry.license_class in LICENSE_CLASSES for entry in entries)
    assert entries[0].license_source == "unpaywall:cc-by"
    assert entries[1].license_source == "unpaywall:unknown"
    assert entries[0].doi == "10.7717/peerj.4375"
    assert entries[0].journal == "PeerJ"
