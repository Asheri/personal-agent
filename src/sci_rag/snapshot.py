"""Named corpus snapshots: give a fingerprint a name you can cite.

The eval reports already stamp a corpus fingerprint (counts, embedding
versions) on every run. A snapshot goes further: it records the full
per-document content-hash list under a NAME, plus a single
``corpus_digest`` (SHA-256 over the sorted content hashes) that makes
"is this the same corpus?" a one-line comparison. Eval runs can then
reference the snapshot name (``sci-rag eval retrieval --snapshot v0.2``)
and a reader can verify, later and elsewhere, exactly what was measured.

Snapshots are small JSON files under ``data/snapshots/`` and are safe to
commit next to eval evidence. They record the corpus, they do not back
it up: the backup/restore runbook lives in ``docs/operations.md``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document, KgCommunity, KgEntity, KgRelationship
from sci_rag.evals.report import git_commit

DEFAULT_BASE_DIR = Path("data/snapshots")


@dataclass
class SnapshotInfo:
    name: str
    path: Path


def _default_name() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


async def write_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str | None = None,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> SnapshotInfo:
    """Write ``<base_dir>/<name>.json``; refuses to overwrite an existing name."""
    name = name or _default_name()
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{name}.json"
    if path.exists():
        raise FileExistsError(
            f"snapshot {name!r} already exists at {path}; snapshots are immutable, pick a new name"
        )

    async with session_factory() as session:
        counts: dict[str, int] = {}
        for label, model in (
            ("documents", Document),
            ("chunks", Chunk),
            ("entities", KgEntity),
            ("relationships", KgRelationship),
            ("communities", KgCommunity),
        ):
            counts[label] = (await session.scalar(select(func.count(model.id)))) or 0
        rows = (
            await session.execute(
                select(Document.id, Document.title, Document.content_hash).order_by(
                    Document.content_hash
                )
            )
        ).all()
        versions = sorted(
            v
            for v in (await session.execute(select(Chunk.embedding_version).distinct())).scalars()
            if v
        )

    digest = hashlib.sha256("\n".join(row.content_hash for row in rows).encode()).hexdigest()
    payload: dict[str, Any] = {
        "name": name,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "counts": counts,
        "embedding_versions": versions,
        "corpus_digest": digest,
        "documents": [
            {"id": row.id, "title": row.title, "content_hash": row.content_hash} for row in rows
        ],
    }
    # Trailing newline because these files get committed, and this project
    # runs end-of-file-fixer over the whole tree in CI. Without it the first
    # commit of any fresh snapshot fails a hook that then rewrites it.
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return SnapshotInfo(name=name, path=path)


def list_snapshots(base_dir: Path = DEFAULT_BASE_DIR) -> list[SnapshotInfo]:
    if not base_dir.is_dir():
        return []
    return [SnapshotInfo(name=path.stem, path=path) for path in sorted(base_dir.glob("*.json"))]


def load_snapshot(name: str, *, base_dir: Path = DEFAULT_BASE_DIR) -> dict[str, Any]:
    path = base_dir / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no snapshot named {name!r} under {base_dir} "
            f"(available: {', '.join(s.name for s in list_snapshots(base_dir)) or 'none'})"
        )
    return json.loads(path.read_text(encoding="utf-8"))
