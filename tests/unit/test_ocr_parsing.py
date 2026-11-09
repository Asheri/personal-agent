"""OCR routing fails visibly and preserves page provenance."""

from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from sci_rag.ingest.errors import ParserError, PlaceholderFileError
from sci_rag.ingest.parsers import parse_file


class FakeOcr:
    name = "fake"

    def text_from_image(self, path):
        assert path.is_file()
        return "受控图像中的项目记录和负责人陈林。", 0.91


def image_file(tmp_path, suffix=".png"):
    path = tmp_path / ("image" + suffix)
    with Image.new("RGB", (300, 100), "white") as image:
        image.save(path)
    return path


def test_fake_ocr_metadata_and_visible_missing_engine(tmp_path, monkeypatch):
    path = image_file(tmp_path)
    parsed = parse_file(path, ocr_engine=FakeOcr())
    assert parsed.metadata["ocr"] == {"engine": "fake", "pages": 1, "confidence": [0.91]}
    assert parsed.page_count == 1 and "负责人" in parsed.blocks[-1].text
    monkeypatch.setattr("sci_rag.ingest.ocr.shutil.which", lambda _: None)
    monkeypatch.setattr(
        "sci_rag.config.get_settings",
        lambda: SimpleNamespace(
            ocr_tesseract_cmd=None, ocr_tessdata_dir=None, ocr_languages="chi_sim+eng"
        ),
    )
    with pytest.raises(ParserError, match="ocr_unavailable"):
        parse_file(path)


@pytest.mark.parametrize("prefer_docling", [False, True])
def test_scanned_and_mixed_pdf_keep_native_text_and_real_page_numbers(
    tmp_path, monkeypatch, prefer_docling
):
    path = image_file(tmp_path)
    scan = tmp_path / "scan.pdf"
    with Image.open(path) as image:
        image.save(scan, "PDF")
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=100)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 10 Tf 10 50 Td (Native source evidence KEEP_NATIVE_TOKEN has enough characters to stay native.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_page(PdfReader(scan).pages[0])
    mixed = tmp_path / "mixed.pdf"
    writer.write(mixed)
    if prefer_docling:
        from sci_rag.ingest.parsers import ParsedDocument

        monkeypatch.setattr("sci_rag.ingest.parsers.docling_available", lambda: True)
        monkeypatch.setattr(
            "sci_rag.ingest.parsers._parse_pdf_docling",
            lambda _: ParsedDocument(
                title="Rich native", raw_text="Native-only output " * 40, page_count=2
            ),
        )
    parsed = parse_file(mixed, prefer_docling=prefer_docling, ocr_engine=FakeOcr())
    assert (
        parsed.page_count == 2
        and "KEEP_NATIVE_TOKEN" in parsed.raw_text
        and "负责人" in parsed.raw_text
    )
    assert parsed.metadata["parser"] == "ocr_scan"
    assert parsed.metadata["ocr"]["results"] == [{"page": 2, "confidence": 0.91}]


def test_empty_ocr_is_not_an_ingested_success(tmp_path):
    class Empty(FakeOcr):
        def text_from_image(self, path):
            return "", None

    with pytest.raises(ParserError, match="ocr_no_text"):
        parse_file(image_file(tmp_path), ocr_engine=Empty())


def test_placeholder_check_happens_before_read(tmp_path, monkeypatch):
    path = image_file(tmp_path)
    monkeypatch.setattr("sci_rag.ingest.errors.check_source", lambda _: None)
    # Public parser owns the same exception as the stat-only reconcile probe.
    monkeypatch.setattr(
        "sci_rag.ingest.parsers.check_source",
        lambda _: (_ for _ in ()).throw(PlaceholderFileError("source_placeholder")),
    )
    with pytest.raises(PlaceholderFileError):
        parse_file(path, ocr_engine=FakeOcr())


def test_tesseract_tsv_does_not_require_runtime_config_files(tmp_path, monkeypatch):
    from sci_rag.ingest.ocr import TesseractOcrEngine

    monkeypatch.setattr(
        "sci_rag.config.get_settings",
        lambda: SimpleNamespace(
            ocr_tesseract_cmd="tesseract", ocr_tessdata_dir=tmp_path, ocr_languages="chi_sim+eng"
        ),
    )

    def native_run(command, **kwargs):
        assert command[-2:] == ["-c", "tessedit_create_tsv=1"]
        return SimpleNamespace(
            returncode=0,
            stdout=b"page_num\tblock_num\tpar_num\tline_num\tconf\ttext\n1\t1\t1\t1\t90\tfixture\n",
        )

    monkeypatch.setattr("sci_rag.ingest.ocr.subprocess.run", native_run)
    assert TesseractOcrEngine().text_from_image(image_file(tmp_path)) == ("fixture", 0.9)
