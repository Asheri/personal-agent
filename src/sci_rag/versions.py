"""Local file identity and the single transaction writer for revision chains."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sci_rag.db.models import Document


def canonical_source_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def identity_key_for(path: Path, source_member: str = "") -> str:
    if not isinstance(source_member, str):
        raise ValueError("source_member must be a stable string")
    encoded = json.dumps([canonical_source_path(path), source_member], ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def lock_document_writes(session: AsyncSession) -> None:
    """Serialize revision writes, deletion, and aggregate rebuilds in this database."""
    await session.execute(text("SELECT pg_advisory_xact_lock(1346587968)"))


async def reconnect_deleted_versions(session: AsyncSession, deleting: set[str]) -> None:
    """Reconnect surviving revisions before the existing deletion path removes rows."""
    identities = select(Document.identity_key).where(Document.id.in_(deleting))
    rows = list(
        (
            await session.scalars(
                select(Document)
                .where(Document.identity_key.in_(identities))
                .order_by(Document.identity_key, Document.version_seq)
                .with_for_update()
            )
        ).all()
    )
    for row in rows:
        if row.id in deleting:
            row.version_of = None
            row.is_current = False
    await session.flush()
    groups: dict[str, list[Document]] = {}
    for row in rows:
        if row.id not in deleting:
            groups.setdefault(row.identity_key, []).append(row)
    for chain in groups.values():
        for index, row in enumerate(chain):
            row.version_of = chain[index - 1].id if index else None
            row.is_current = index == len(chain) - 1
    await session.flush()
