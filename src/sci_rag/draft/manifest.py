"""Drafting a corpus manifest, without letting a model decide your rights.

`sci-rag campaign build` already writes a manifest for DOI-addressable
literature, where rights come from Unpaywall and Crossref rather than from
anybody's judgement. Local PDFs get none of that: `discover_folder()` finds the
files and defaults every other field, so the title, authors, year, and source
bucket are a typing job.

Most of that a model can read off a title page, and a human can correct.
``license_class`` cannot. It is the input to a scoping boundary that decides
what a public endpoint may quote, so this module never lets a model set it.
Every drafted row is written ``unknown``, which is exactly what the fail-closed
default is for, and a license sentence the model found is kept as evidence for
the human making the call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from sci_rag.draft import DraftError, complete, parse_json_object
from sci_rag.draft import render_prompt as _render_template
from sci_rag.ingest.manifest import CorpusEntry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sci_rag.llm import LLMClient

PROMPT_NAME = "manifest_metadata"

#: Enough of a document to carry its title page and front matter, which is
#: where a license statement lives, without a 200-page report crowding out the
#: other 59 documents in the batch.
HEAD_CHARS = 6000

#: Documents per model call. Small enough that one reply stays parseable,
#: large enough that source buckets are chosen across a real sample.
BATCH_SIZE = 12

#: Written above a drafted manifest. ``load_manifest`` skips ``#`` lines.
RIGHTS_HEADER = """\
# Model-drafted corpus manifest, awaiting a rights decision.
#
# Every row says license_class "unknown", and that was not read off the
# document: this kit never lets a model decide redistribution rights. Where a
# license sentence was found in the text it is quoted in license_source as
# evidence only. Read it, decide the class yourself, and edit it in. Until you
# do, these documents are excluded from scoped retrieval. This keeps undecided
# rights out of results. See "Scope precedes ranking" in docs/methodology.md.
"""

#: Fields a model may fill. `license_class` is deliberately absent.
_MODEL_FIELDS = ("title", "authors", "year", "doi", "journal", "url", "source")


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


@dataclass(frozen=True)
class DocumentHead:
    """The front of one document, as the model will see it."""

    filename: str
    path: Path
    title: str
    text: str


@dataclass
class DraftedManifest:
    entries: list[CorpusEntry] = field(default_factory=list)
    #: ``(filename, why it was dropped)``. Printed, never silently binned.
    dropped: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    source_buckets: list[str] = field(default_factory=list)

    @property
    def needs_rights_decision(self) -> int:
        """How many rows a human still has to classify. Today: all of them."""
        return sum(1 for entry in self.entries if entry.license_class == "unknown")


def read_heads(folder: Path, *, max_chars: int = HEAD_CHARS) -> list[DocumentHead]:
    """The opening text of every supported document under ``folder``.

    Goes through :func:`sci_rag.ingest.manifest.discover_folder` and the
    existing parsers, so the text the model reads is the text ingestion would
    have produced, and a file the kit cannot ingest never reaches the prompt.
    """
    from sci_rag.ingest.manifest import discover_folder
    from sci_rag.ingest.parsers import parse_file

    if not folder.exists():
        raise DraftError(f"The folder {folder} does not exist.")
    discovered = discover_folder(folder)
    if not discovered:
        raise DraftError(f"Found no supported documents under {folder}.")

    heads: list[DocumentHead] = []
    for entry in discovered:
        try:
            parsed = parse_file(entry.path)
        except Exception as exc:
            raise DraftError(f"Could not read {entry.path.name}: {exc}") from exc
        body = (
            "\n\n".join(block.text for block in parsed.blocks)
            if parsed.blocks is not None
            else (parsed.raw_text or "")
        )
        heads.append(
            DocumentHead(
                filename=entry.path.name,
                path=entry.path,
                title=parsed.title,
                text=body[:max_chars].strip(),
            )
        )
    return heads


def _document_block(head: DocumentHead) -> str:
    """One document as the model sees it: filename, parsed title, opening text.

    The parsed title is shown because the markdown parser consumes a leading H1
    into ``ParsedDocument.title``, and PDF metadata never appears in the body at
    all. Without this line the model is asked to read a document title that was
    removed before it ever saw the document.
    """
    body = head.text or "(no extractable text)"
    return f"--- {head.filename} ---\nTitle as parsed from the file: {head.title}\n\n{body}"


def render_prompt(domain_dir: Path, *, heads: list[DocumentHead], source_buckets: list[str]) -> str:
    """One prompt for the whole batch, identical in both lanes.

    Batched rather than one call per document so the model chooses source
    buckets across a real sample instead of inventing one per file, and so the
    copy-paste lane is one prompt and one reply rather than N of each.
    """
    documents = "\n\n".join(_document_block(head) for head in heads)
    buckets = (
        "\n".join(f"- {bucket}" for bucket in source_buckets)
        if source_buckets
        else "(none chosen yet: propose them)"
    )
    return _render_template(domain_dir, PROMPT_NAME, SOURCE_BUCKETS=buckets, DOCUMENTS=documents)


def parse_reply(raw: str, *, heads: list[DocumentHead]) -> DraftedManifest:
    """Validate an untrusted reply into manifest rows, failing closed on rights."""
    payload = parse_json_object(raw, expecting="documents")
    rows = payload.get("documents")
    if not isinstance(rows, list) or not rows:
        raise DraftError(
            'The reply carried no "documents" list. Expected '
            '{"documents": [{"filename": ..., "title": ...}, ...]}.'
        )

    by_name = {head.filename: head for head in heads}
    result = DraftedManifest()
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise DraftError(f"Document {index} is not a JSON object.")
        filename = str(row.get("filename") or "").strip()
        head = by_name.get(filename)
        if head is None:
            result.dropped.append(
                (filename or f"row {index}", "no such file was in the folder that was read.")
            )
            continue
        if filename in seen:
            result.dropped.append((filename, "the reply listed this file twice."))
            continue
        seen.add(filename)

        fields: dict[str, Any] = {
            key: row[key] for key in _MODEL_FIELDS if row.get(key) not in (None, "", [])
        }
        # The parser's title is the file's own H1 or PDF metadata, so falling
        # back to it is reading the document, not guessing about it.
        fields.setdefault("title", head.title)
        if "license_class" in row:
            result.notes.append(
                f"{filename}: the model proposed license_class "
                f"{str(row['license_class'])!r}. Ignored; rights are yours to decide."
            )
        try:
            # license_class is set after the model's fields, not merged with
            # them, so no reply shape can reach it.
            entry = CorpusEntry(path=head.path, **fields)
        except ValidationError as exc:
            result.dropped.append((filename, f"the row did not validate: {exc}"))
            continue
        entry.license_class = "unknown"

        statement = str(row.get("license_statement") or "").strip()
        if statement:
            if _normalize(statement) in _normalize(head.text):
                entry.license_source = statement
            else:
                result.notes.append(
                    f"{filename}: the quoted license statement is not in the document text, "
                    "so it was dropped rather than recorded as evidence."
                )
        result.entries.append(entry)

    declared = payload.get("source_buckets")
    buckets = [str(b) for b in declared if str(b).strip()] if isinstance(declared, list) else []
    for entry in result.entries:
        if entry.source not in buckets:
            buckets.append(entry.source)
    result.source_buckets = buckets
    return result


async def draft_manifest(
    domain_dir: Path,
    *,
    heads: list[DocumentHead],
    llm: LLMClient | None = None,
    settings: Any = None,
    raw_reply: str | None = None,
    batch_size: int = BATCH_SIZE,
) -> DraftedManifest:
    """Read metadata off every document, in batches, and fail closed on rights.

    Later batches are shown the buckets earlier ones chose, so a sixty-document
    folder converges on a handful of shared sources instead of sixty.
    """
    if raw_reply is not None:
        return parse_reply(raw_reply, heads=heads)

    merged = DraftedManifest()
    for start in range(0, len(heads), max(1, batch_size)):
        batch = heads[start : start + max(1, batch_size)]
        prompt = render_prompt(domain_dir, heads=batch, source_buckets=merged.source_buckets)
        drafted = parse_reply(await complete(prompt, llm=llm, settings=settings), heads=batch)
        merged.entries.extend(drafted.entries)
        merged.dropped.extend(drafted.dropped)
        merged.notes.extend(drafted.notes)
        merged.source_buckets.extend(
            bucket for bucket in drafted.source_buckets if bucket not in merged.source_buckets
        )
    return merged


def render_jsonl(entries: list[CorpusEntry], *, manifest_path: Path) -> str:
    """The manifest a drafting run proposes, header and all.

    Paths are written relative to the manifest when they sit under it, matching
    the shipped demo manifest and keeping the file portable between checkouts.
    """
    base = manifest_path.parent.resolve()
    lines = [RIGHTS_HEADER.rstrip("\n")]
    for entry in entries:
        row = entry.model_dump()
        resolved = entry.path.resolve()
        row["path"] = str(resolved.relative_to(base) if resolved.is_relative_to(base) else resolved)
        lines.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(lines) + "\n"


__all__ = [
    "BATCH_SIZE",
    "HEAD_CHARS",
    "PROMPT_NAME",
    "RIGHTS_HEADER",
    "DocumentHead",
    "DraftedManifest",
    "draft_manifest",
    "parse_reply",
    "read_heads",
    "render_jsonl",
    "render_prompt",
]
