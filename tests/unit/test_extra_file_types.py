"""Format acceptance checks preserve content and expose omissions."""

import mailbox
from email.message import EmailMessage

import pytest

from sci_rag.ingest.chunker import chunk_document
from sci_rag.ingest.parsers import parse_file


def test_code_is_read_without_execution_and_body_stays_searchable(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(
        '"""Research helper."""\nraise RuntimeError("must never execute")\ndef reconcile_items(value: int) -> str:\n    return "BODY_ONLY_TOKEN_947"\n',
        encoding="utf-8",
    )
    parsed = parse_file(path)
    assert parsed.metadata["parser"] == "code"
    chunks = chunk_document(parsed)
    assert any("BODY_ONLY_TOKEN_947" in c.content for c in chunks)
    assert "reconcile_items" in parsed.metadata["symbols"][0]


def test_csv_preserves_quoted_fields_and_zero_values(tmp_path):
    path = tmp_path / "records.csv"
    path.write_text('项目,值,备注\n星河,0,"a|b\\c"\n海岚,12,"多行\n说明"\n', encoding="utf-8-sig")
    parsed = parse_file(path)
    tables = [b.text for b in parsed.blocks if b.kind == "table"]
    assert len(tables) == 1 and "项目" in tables[0] and "0" in tables[0]
    assert r"a\|b\\c" in tables[0] and "多行 说明" in tables[0]


def test_xlsx_uses_cached_formulas_and_reports_row_cap(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "records.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "实验"
    sheet.append(["项目", "数值", "公式"])
    sheet.append(["星河", 0, "=1+2"])
    for i in range(503):
        sheet.append([f"行{i}", i, None])
    book.save(path)
    book.close()
    parsed = parse_file(path)
    assert parsed.metadata["truncated"]["rows"] == 5
    assert parsed.metadata["formulas_unevaluated"] == ["实验!C2"]
    assert "=1+2" not in "\n".join(b.text for b in parsed.blocks)
    assert any(c.is_table and "项目" in c.content for c in chunk_document(parsed))


def message(subject, identity=None, body="项目实验记录包含明确的文件来源与负责人信息。"):
    msg = EmailMessage()
    msg["From"] = "sender@example.invalid"
    msg["To"] = "reader@example.invalid"
    msg["Subject"] = subject
    msg["Date"] = "Sun, 25 Oct 2026 09:00:00 +0800"
    if identity:
        msg["Message-ID"] = f"<{identity}@example.invalid>"
    msg.set_content(body)
    return msg


def test_mailbox_member_keys_survive_deletion_and_reordering(tmp_path):
    from sci_rag.ingest.parsers import parse_file_many

    path = tmp_path / "messages.mbox"
    items = [message("first", "one"), message("without id"), message("last", "three")]
    box = mailbox.mbox(path)
    for msg in items:
        box.add(msg)
    box.flush()
    box.close()
    before = parse_file_many(path)
    assert len(before) == 3 and len({d.metadata["source_member"] for d in before}) == 3
    path.unlink()
    box = mailbox.mbox(path)
    for msg in reversed(items[1:]):
        box.add(msg)
    box.flush()
    box.close()
    after = parse_file_many(path)
    assert {d.title: d.metadata["source_member"] for d in after} == {
        d.title: d.metadata["source_member"] for d in before if d.title != "first"
    }
    assert all(d.metadata["doc_date"] == "2026-10-25" for d in after)


def test_eml_prefers_plain_body_and_does_not_read_attachments(tmp_path):
    path = tmp_path / "message.eml"
    msg = message("邮件标题", "mail")
    msg.add_alternative("<html><body>HTML_DUPLICATE</body></html>", subtype="html")
    msg.add_attachment(
        b"ATTACHMENT_SECRET", maintype="application", subtype="octet-stream", filename="private.txt"
    )
    path.write_bytes(msg.as_bytes())
    parsed = parse_file(path)
    text = "\n".join(b.text for b in parsed.blocks)
    assert "文件来源" in text and "HTML_DUPLICATE" not in text and "ATTACHMENT_SECRET" not in text
    assert parsed.metadata["source_member"] == "" and parsed.metadata["attachments_skipped"] == 1


@pytest.mark.parametrize(
    "suffix,body",
    [
        (".json", '{"project":"星河","value":0}'),
        (".jsonl", '{"id":1}\n{"id":2}\n'),
        (".yaml", "project: 星河\nvalue: 0\n"),
    ],
)
def test_structured_text_keeps_source_values(tmp_path, suffix, body):
    path = tmp_path / ("data" + suffix)
    path.write_text(body, encoding="utf-8")
    parsed = parse_file(path)
    assert body.strip() in "\n".join(b.text for b in parsed.blocks)


def test_text_encodings_and_invalid_data_are_explicit(tmp_path):
    from sci_rag.ingest.errors import ParserError

    path = tmp_path / "data.json"
    path.write_bytes('{"项目":"星河"}'.encode("utf-16"))
    assert parse_file(path).metadata["encoding"] == "utf-16"
    path.write_bytes('{"项目":"星河"}'.encode("gb18030"))
    assert parse_file(path).metadata["encoding"] == "gb18030"
    path.write_text('{"broken":}', encoding="utf-8")
    with pytest.raises(ParserError, match="invalid_structured_text"):
        parse_file(path)
    yaml_path = path.with_suffix(".yaml")
    yaml_path.write_text('!!python/object/apply:os.system ["must never execute"]', encoding="utf-8")
    with pytest.raises(ParserError, match="invalid_structured_text"):
        parse_file(yaml_path)


def test_encrypted_office_is_not_read_as_an_empty_success(tmp_path):
    from sci_rag.ingest.errors import ParserError

    path = tmp_path / "protected.xlsx"
    path.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"controlled")
    with pytest.raises(ParserError, match="encrypted"):
        parse_file(path)
