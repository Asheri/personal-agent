"""On-demand source reconciliation with conservative, identity-scoped deletion."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.corpus import delete_documents_in_session
from sci_rag.db.models import Document
from sci_rag.embed.provider import EmbeddingProvider
from sci_rag.ingest.fingerprint import PlaceholderFileError, fingerprint, ingest_signature
from sci_rag.ingest.ingester import PendingHostIngest, PendingIngest, ingest_entries
from sci_rag.ingest.manifest import CorpusEntry
from sci_rag.ingest.suffixes import parser_for_suffix
from sci_rag.versions import canonical_source_path, lock_document_writes

log = structlog.get_logger(__name__)
STATUSES = (
    "added",
    "unchanged",
    "verify",
    "metadata_only",
    "updated",
    "removed",
    "out_of_scope",
    "no_path_recorded",
    "failed",
    "placeholder_skipped",
)
_LOCK = 1346587969


class ReconcileBusyError(RuntimeError):
    """Another reconcile already owns this database."""


@dataclass
class ReconcileOutcome:
    path: str
    status: str
    detail: str = ""
    document_id: str | None = None
    chunk_count: int = 0
    document_count: int = 0
    parser: str = ""


@dataclass
class ReconcilePlan:
    root: Path
    root_identity: tuple[int, int]
    source_outcomes: list[ReconcileOutcome] = field(default_factory=list)
    pending: list[tuple[PendingIngest | PendingHostIngest, ReconcileOutcome]] = field(
        default_factory=list
    )
    database_outcomes: list[ReconcileOutcome] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    database_rows_seen: int = 0


@dataclass
class ReconcileReport:
    source_outcomes: list[ReconcileOutcome] = field(default_factory=list)
    database_outcomes: list[ReconcileOutcome] = field(default_factory=list)
    database_rows_seen: int = 0
    graph_changed: bool = False

    @property
    def outcomes(self) -> list[ReconcileOutcome]:
        return self.source_outcomes + self.database_outcomes

    @property
    def failed(self) -> int:
        return sum(o.status == "failed" for o in self.outcomes)

    @property
    def ingested(self) -> int:
        return sum(o.status in {"added", "updated"} for o in self.source_outcomes)

    @property
    def skipped(self) -> int:
        return sum(
            o.status in {"unchanged", "metadata_only", "placeholder_skipped"}
            for o in self.source_outcomes
        )

    def counts(self, *, database: bool = False) -> dict[str, int]:
        rows = self.database_outcomes if database else self.source_outcomes
        counts = Counter(o.status for o in rows)
        return {status: counts[status] for status in STATUSES}

    def parser_counts(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for row in self.source_outcomes:
            parser = row.parser or parser_for_suffix(Path(row.path).suffix)
            counts = result.setdefault(parser, {"ok": 0, "failed": 0, "skipped": 0})
            key = (
                "failed"
                if row.status == "failed"
                else "ok"
                if row.status in {"added", "updated", "metadata_only"}
                else "skipped"
            )
            counts[key] += 1
        return result


def recorded_path(document: Document) -> Path | None:
    return source_path_for(document.extra, document.source_ref)


def source_path_for(extra: dict[str, Any], source_ref: str | None) -> Path | None:
    """Accept a recorded absolute path; never guess a path from a title or URL."""
    raw = extra.get("path") or source_ref
    if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
        return None
    try:
        return Path(canonical_source_path(Path(raw)))
    except (OSError, ValueError):
        return None


def _in_scope(path: Path, root: Path) -> bool:
    return path != root and path.is_relative_to(root)


def _missing(path: Path) -> bool:
    try:
        path.stat()
    except FileNotFoundError:
        return True
    return False


def plan_reconcile(
    entries: list[CorpusEntry],
    documents: list[Document],
    *,
    root: Path,
    target_tokens: int = 800,
    overlap_tokens: int = 150,
    prefer_docling: bool = True,
) -> ReconcilePlan:
    """Plan using stat only. Parsing and all writes remain in the ingester."""
    root = Path(canonical_source_path(root))
    if not root.is_dir():
        raise ValueError("reconcile_root_not_directory")
    root_stat = root.stat()
    plan = ReconcilePlan(
        root=root,
        root_identity=(root_stat.st_dev, root_stat.st_ino),
        database_rows_seen=len(documents),
    )
    paths = [canonical_source_path(entry.path) for entry in entries]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate_manifest_path")
    source_paths = set(paths)
    by_path: dict[str, list[Document]] = defaultdict(list)
    for stored_document in documents:
        stored_path = recorded_path(stored_document)
        if stored_path is None:
            plan.database_outcomes.append(
                ReconcileOutcome(
                    "", "no_path_recorded", document_id=stored_document.id, document_count=1
                )
            )
        else:
            by_path[str(stored_path)].append(stored_document)
    for entry, path in zip(entries, paths, strict=True):
        outcome = ReconcileOutcome(path, "verify", parser=parser_for_suffix(entry.path.suffix))
        plan.source_outcomes.append(outcome)
        current = [d for d in by_path.get(path, []) if d.is_current]
        # parse_file currently yields one document. Do not flatten future mail members.
        if entry.path.suffix.lower() != ".mbox" and (
            len(current) > 1 or any(d.extra.get("source_member", "") for d in current)
        ):
            outcome.status, outcome.detail = "failed", "multi_member_source_requires_parser"
            continue
        try:
            observed = fingerprint(entry.path)
        except PlaceholderFileError:
            outcome.status, outcome.detail = "placeholder_skipped", "source_placeholder"
            continue
        except OSError as exc:
            outcome.status, outcome.detail = "failed", f"source_stat:{type(exc).__name__}"
            continue
        document: Document | None = current[0] if current else None
        if document is not None:
            outcome.parser = document.extra.get("parser", outcome.parser)
        signature = ingest_signature(
            entry,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            prefer_docling=prefer_docling,
        )
        if entry.path.suffix.lower() == ".mbox":
            if current and all(
                d.extra.get("source_fingerprint") == observed.as_dict()
                and d.extra.get("ingest_signature") == signature
                for d in current
            ):
                outcome.status, outcome.document_count = "unchanged", len(current)
                continue
            outcome.status = "verify" if current else "added"
            plan.pending.append(
                (
                    PendingHostIngest(
                        entry, observed, {d.identity_key: (d.id, d.version_seq) for d in current}
                    ),
                    outcome,
                )
            )
            continue
        if (
            document is not None
            and document.extra.get("source_fingerprint") == observed.as_dict()
            and document.extra.get("ingest_signature") == signature
        ):
            outcome.status, outcome.document_id = "unchanged", document.id
            continue
        outcome.status = "verify" if document is not None else "added"
        pending = PendingIngest(
            entry,
            document.id if document else None,
            document.version_seq + 1 if document else 1,
            observed,
        )
        plan.pending.append((pending, outcome))
    for path_str, chain in by_path.items():
        host_path = Path(path_str)
        identities: dict[str, list[Document]] = defaultdict(list)
        for document in chain:
            identities[document.identity_key].append(document)
        for identity, versions in identities.items():
            head = max(versions, key=lambda d: (d.is_current, d.version_seq))
            if not _in_scope(host_path, root):
                plan.database_outcomes.append(
                    ReconcileOutcome(
                        path_str, "out_of_scope", document_id=head.id, document_count=len(versions)
                    )
                )
            elif path_str not in source_paths:
                try:
                    if _missing(host_path):
                        plan.missing.append((path_str, identity))
                except OSError as exc:
                    plan.database_outcomes.append(
                        ReconcileOutcome(
                            path_str,
                            "failed",
                            f"source_stat:{type(exc).__name__}",
                            document_id=head.id,
                        )
                    )
    return plan


@asynccontextmanager
async def _single_reconcile(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    # A dedicated session pins the physical connection until explicit unlock.
    async with factory() as guard:
        acquired = await guard.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK})
        if not acquired:
            raise ReconcileBusyError("reconcile_already_running")
        try:
            yield
        finally:
            try:
                await guard.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK})
            except BaseException:
                await guard.invalidate()
                raise


async def _remove_missing(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    root_identity: tuple[int, int],
    path_str: str,
    identity: str,
) -> ReconcileOutcome:
    path = Path(path_str)
    async with factory() as session:
        await lock_document_writes(session)
        if not root.is_dir() or not _in_scope(path, root):
            raise ValueError("deletion_scope_unavailable")
        root_stat = root.stat()
        if (root_stat.st_dev, root_stat.st_ino) != root_identity:
            raise ValueError("deletion_root_changed")
        if not _missing(path):
            raise ValueError("source_reappeared")
        chain = list(
            (await session.scalars(select(Document).where(Document.identity_key == identity))).all()
        )
        if not chain or any(recorded_path(d) != path for d in chain):
            raise ValueError("deletion_identity_changed")
        head = max(chain, key=lambda d: (d.is_current, d.version_seq))
        outcome = await delete_documents_in_session(session, [d.id for d in chain])
        await session.commit()
        return ReconcileOutcome(
            path_str, "removed", document_id=head.id, document_count=outcome.documents_deleted
        )


@asynccontextmanager
async def _reconcile_guard(
    factory: async_sessionmaker[AsyncSession], locked: bool
) -> AsyncIterator[None]:
    if locked:
        yield
    else:
        async with _single_reconcile(factory):
            yield


async def reconcile_entries(
    entries: list[CorpusEntry],
    *,
    root: Path,
    session_factory: async_sessionmaker[AsyncSession],
    embedder: EmbeddingProvider,
    target_tokens: int = 800,
    overlap_tokens: int = 150,
    prefer_docling: bool = True,
    _locked: bool = False,
) -> ReconcileReport:
    # Only the refresh orchestrator sets _locked while owning _single_reconcile.
    async with _reconcile_guard(session_factory, _locked):
        async with session_factory() as session:
            documents = list((await session.scalars(select(Document))).all())
        plan = plan_reconcile(
            entries,
            documents,
            root=root,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            prefer_docling=prefer_docling,
        )
        report = ReconcileReport(
            plan.source_outcomes, plan.database_outcomes, plan.database_rows_seen
        )
        for pending, row in plan.pending:
            ingested = await ingest_entries(
                [pending],
                embedder=embedder,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
                prefer_docling=prefer_docling,
                session_factory=session_factory,
            )
            result = ingested.outcomes[0]
            row.detail, row.document_id, row.chunk_count = (
                result.detail,
                result.document_id,
                result.chunk_count,
            )
            row.parser = result.parser or row.parser
            row.document_count = result.document_count
            if result.status == "failed":
                row.status = "failed"
            elif result.status == "skipped_duplicate":
                row.status = "metadata_only"
            else:
                row.status = (
                    "updated"
                    if (
                        pending.members
                        if isinstance(pending, PendingHostIngest)
                        else pending.predecessor_id
                    )
                    else "added"
                )
            report.graph_changed |= result.graph_changed
        for path, identity in plan.missing:
            if report.failed:
                row = ReconcileOutcome(path, "failed", "deletion_deferred_after_source_failure")
            else:
                try:
                    row = await _remove_missing(
                        session_factory, plan.root, plan.root_identity, path, identity
                    )
                    report.graph_changed = True
                except Exception as exc:
                    row = ReconcileOutcome(path, "failed", f"deletion_failed:{type(exc).__name__}")
            report.database_outcomes.append(row)
        log.info(
            "reconcile_complete",
            source_files=len(report.source_outcomes),
            ingested=report.ingested,
            failed=report.failed,
            removed=sum(o.status == "removed" for o in report.database_outcomes),
        )
        return report
