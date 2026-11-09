"""Parse MIME bodies locally; each mailbox message has a stable member key."""

from __future__ import annotations

import hashlib
import mailbox
import re
from collections import Counter
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

from sci_rag.ingest.errors import ParserError
from sci_rag.ingest.parsers import Block, ParsedDocument


def _message(data: bytes, *, parser: str, member: str) -> ParsedDocument:
    msg = BytesParser(policy=policy.default).parsebytes(data)
    if not isinstance(msg, EmailMessage) or not any(
        msg.get(h) for h in ("From", "To", "Subject", "Date", "Message-ID")
    ):
        raise ParserError("invalid_mail", parser)
    if msg.get_content_type() in {"application/pkcs7-mime", "application/x-pkcs7-mime"}:
        raise ParserError("encrypted", parser)
    part = msg.get_body(preferencelist=("plain", "html"))
    blocks = [
        Block(
            kind="text",
            text="\n".join(
                f"{name}: {msg[name]}"
                for name in ("Subject", "From", "To", "Cc", "Date", "Message-ID")
                if msg.get(name)
            ),
        )
    ]
    if part is not None:
        try:
            body = part.get_content()
        except (LookupError, UnicodeError) as exc:
            raise ParserError("mail_decode_failed", parser) from exc
        if not isinstance(body, str):
            raise ParserError("mail_decode_failed", parser)
        if part.get_content_type() == "text/html":
            from sci_rag.ingest.html_parser import parse_html

            blocks.extend(parse_html(body, fallback_title="Mail body").blocks or [])
        elif body.strip():
            blocks.append(Block(kind="text", text=body.strip()))
    elif not msg.is_multipart() and msg.get_content_maintype() != "text":
        raise ParserError("mail_body_unsupported", parser)
    metadata = {
        "parser": parser,
        "source_member": member,
        "mail_headers": {
            h.lower(): str(msg[h]) for h in ("From", "To", "Cc", "Date", "Message-ID") if msg.get(h)
        },
        "attachments_skipped": sum(
            1 for p in msg.walk() if p.get_content_disposition() == "attachment"
        ),
        "mail_defects": [type(d).__name__ for d in msg.defects],
    }
    try:
        when = parsedate_to_datetime(str(msg["Date"])) if msg.get("Date") else None
        if when is not None:
            metadata.update(
                doc_date=when.date().isoformat(),
                doc_date_source="email_date_header",
                email_datetime=when.isoformat(),
            )
    except (ValueError, TypeError, OverflowError):
        metadata["date_invalid"] = True
    return ParsedDocument(
        title=str(msg.get("Subject") or "Untitled message"), blocks=blocks, metadata=metadata
    )


def parse_mail(path: Path) -> list[ParsedDocument]:
    if path.suffix.lower() == ".eml":
        return [_message(path.read_bytes(), parser="eml", member="")]
    with path.open("rb") as f:
        prefix = f.read(5)
    if not prefix:
        return []
    if prefix != b"From ":
        raise ParserError("invalid_mbox", "mbox")
    box = mailbox.mbox(path, create=False)
    documents = []
    seen_ids: set[str] = set()
    no_id_counts: Counter[str] = Counter()
    try:
        for key in box.iterkeys():
            data = box.get_bytes(key, from_=False)
            msg = BytesParser(policy=policy.default).parsebytes(data)
            identity = str(msg.get("Message-ID", "")).strip()
            if re.fullmatch(r"<[^<>\s@]+@[^<>\s@]+>", identity):
                if identity in seen_ids:
                    raise ParserError("duplicate_message_id", "mbox")
                seen_ids.add(identity)
                member = "message-id:" + identity
            else:
                digest = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
                no_id_counts[digest] += 1
                member = f"content:{digest}:{no_id_counts[digest]}"
            documents.append(_message(data, parser="mbox", member=member))
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError("invalid_mbox", "mbox") from exc
    finally:
        box.close()
    return documents
