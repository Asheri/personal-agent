"""Representative passages from whatever the project already has.

A drafting prompt is only worth pasting into an assistant if it carries real
text from the user's own documents, so every drafter that needs grounding
gets its passages here. Two sources, one shape:

* **The ingested corpus.** Preferred once ``sci-rag ingest`` has run: the
  chunker has already segmented the documents, and each chunk knows its
  document title.
* **``data/raw/`` directly**, through the existing parsers. This is what
  makes the drafters usable before ``make setup``, on a laptop with no
  database, which is the state a new user is actually in.

Sampling is deterministic in both. Lane B renders a prompt for the user to
paste elsewhere and then reads the reply back; if the same folder produced a
different prompt on the second run, the two halves of that lane would not be
talking about the same passages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sci_rag.draft import DraftError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

#: Below this, a passage is a fragment rather than something to ask about.
_MIN_PASSAGE_CHARS = 80
#: Above this, a passage crowds the prompt without adding evidence.
_MAX_PASSAGE_CHARS = 1200


@dataclass(frozen=True)
class Passage:
    """One excerpt, labelled with the document it came from.

    The title is not decoration: seed-question verification checks that a
    quoted phrase lives in a document the question actually names, and that
    check needs to know which document each passage belongs to.
    """

    document_title: str
    text: str


@dataclass(frozen=True)
class PassageSample:
    passages: tuple[Passage, ...]
    #: "corpus" or "files". Recorded in the run summary, because which one
    #: ran changes what the draft could possibly have seen.
    origin: str
    document_count: int

    def describe(self) -> str:
        source = "the ingested corpus" if self.origin == "corpus" else "files on disk"
        return (
            f"{len(self.passages)} passages from {self.document_count} documents, "
            f"sampled from {source}"
        )


def format_passages(passages: tuple[Passage, ...] | list[Passage]) -> str:
    """Number the passages and label each with its document, for a prompt."""
    return "\n\n".join(
        f"[{index}] {passage.document_title}\n{passage.text}"
        for index, passage in enumerate(passages, start=1)
    )


def _spread(items: list[str], take: int) -> list[str]:
    """Take ``take`` items spread evenly across ``items``, order preserved.

    Evenly rather than from the front: the front of a document is its title
    page and abstract, and a question drafted only from abstracts never
    reaches the tables where the numbers live.
    """
    if take <= 0 or not items:
        return []
    if len(items) <= take:
        return list(items)
    step = len(items) / take
    return [items[min(len(items) - 1, int(index * step))] for index in range(take)]


def _passage_candidates(text: str) -> list[str]:
    """Split document text into passage-sized pieces worth quoting."""
    candidates: list[str] = []
    for block in text.split("\n\n"):
        cleaned = " ".join(block.split())
        if len(cleaned) < _MIN_PASSAGE_CHARS:
            continue
        candidates.append(cleaned[:_MAX_PASSAGE_CHARS])
    return candidates


def sample_files(folder: Path, *, limit: int = 12, per_document: int = 3) -> PassageSample:
    """Read passages straight from a folder of documents.

    Uses :func:`sci_rag.ingest.parsers.parse_file`, so a PDF goes through the
    same route ingestion would take and the passages the model sees are the
    passages the corpus would hold.
    """
    from sci_rag.ingest.parsers import SUPPORTED_SUFFIXES, parse_file

    if not folder.exists():
        raise DraftError(
            f"The folder {folder} does not exist. Put documents there, or point "
            "--folder at where they are."
        )
    paths = sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not paths:
        raise DraftError(
            f"Found no supported documents under {folder} "
            f"(looking for {', '.join(sorted(SUPPORTED_SUFFIXES))})."
        )

    per_document = max(1, per_document)
    by_document: list[tuple[str, list[str]]] = []
    for path in paths:
        try:
            parsed = parse_file(path)
        except Exception as exc:  # a corrupt file is one document, not a dead run
            raise DraftError(f"Could not read {path.name}: {exc}") from exc
        text = (
            "\n\n".join(block.text for block in parsed.blocks)
            if parsed.blocks is not None
            else (parsed.raw_text or "")
        )
        candidates = _passage_candidates(text)
        if candidates:
            by_document.append((parsed.title, candidates))

    if not by_document:
        raise DraftError(
            f"Found no supported documents with readable text under {folder}. "
            "Scanned PDFs need OCR before the kit can quote them."
        )
    return _interleave(by_document, limit=limit, per_document=per_document, origin="files")


async def sample_corpus(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = 12,
    per_document: int = 3,
) -> PassageSample:
    """Read passages from the chunks already in the database."""
    from sqlalchemy import select

    from sci_rag.db.models import Chunk, Document

    per_document = max(1, per_document)
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Document.title, Chunk.content)
                .join(Chunk, Chunk.document_id == Document.id)
                # Ordered by title, not by id: ids are random, and a prompt
                # that changes between two runs breaks the copy-paste lane.
                .order_by(Document.title, Chunk.chunk_index)
            )
        ).all()

    if not rows:
        raise DraftError(
            "There are no ingested chunks to sample. Run `sci-rag ingest` first, "
            "or pass --folder to draft from files on disk instead."
        )

    by_document: list[tuple[str, list[str]]] = []
    for title, content in rows:
        cleaned = " ".join((content or "").split())[:_MAX_PASSAGE_CHARS]
        if len(cleaned) < _MIN_PASSAGE_CHARS:
            continue
        if by_document and by_document[-1][0] == title:
            by_document[-1][1].append(cleaned)
        else:
            by_document.append((title, [cleaned]))

    if not by_document:
        raise DraftError(
            "Every ingested chunk is too short to quote. Check the ingestion run "
            "with `sci-rag stats`."
        )
    return _interleave(by_document, limit=limit, per_document=per_document, origin="corpus")


def _interleave(
    by_document: list[tuple[str, list[str]]],
    *,
    limit: int,
    per_document: int,
    origin: str,
) -> PassageSample:
    """One passage per document, round by round, until the budget runs out.

    Round-robin rather than document-by-document so a truncated sample still
    covers the whole collection. A 200-page report and a two-page note are
    equally likely to be represented, which is what keeps drafted questions
    from all being about the longest document.
    """
    taken = [_spread(candidates, per_document) for _, candidates in by_document]
    passages: list[Passage] = []
    for round_index in range(per_document):
        for (title, _), picks in zip(by_document, taken, strict=True):
            if round_index < len(picks) and len(passages) < limit:
                passages.append(Passage(document_title=title, text=picks[round_index]))
    return PassageSample(
        passages=tuple(passages),
        origin=origin,
        document_count=len({p.document_title for p in passages}),
    )


__all__ = [
    "Passage",
    "PassageSample",
    "format_passages",
    "sample_corpus",
    "sample_files",
]
