"""One guarded refresh for scheduler, hook, polling, and explicit invocations."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.config import get_settings
from sci_rag.db import get_session_factory
from sci_rag.db.models import Chunk, Document, FileEvent, new_id
from sci_rag.embed import get_embedder
from sci_rag.embed.provider import EmbeddingProvider
from sci_rag.ingest import discover_folder, load_manifest
from sci_rag.licensing import EXTERNAL_SAFE_CLASSES
from sci_rag.reconcile import ReconcileBusyError, _single_reconcile, reconcile_entries
from sci_rag.versions import canonical_source_path


def _key(path: Path) -> str:
    return hashlib.sha256(canonical_source_path(path).encode()).hexdigest()


async def _knowledge(
    factory: async_sessionmaker[AsyncSession],
    embedder: EmbeddingProvider,
    *,
    update_graph: bool,
    changed: bool,
) -> dict[str, Any]:
    from sci_rag.domain import load_domain
    from sci_rag.projects import classify_documents
    from sci_rag.relate.mentions import build_mentions

    settings = get_settings()
    domain = load_domain(settings.domain_dir)
    mentions = await build_mentions(factory, apply=True)
    model_enabled = update_graph and not settings.is_offline()
    async with factory() as session:
        pending = await session.scalar(
            select(Chunk.id)
            .join(Document)
            .where(
                Document.is_current.is_(True),
                Document.license_class.in_(EXTERNAL_SAFE_CLASSES),
                Chunk.graph_extracted_at.is_(None),
            )
            .limit(1)
        )
    metadata_enabled = model_enabled and (changed or pending is not None)
    llm = None
    if model_enabled:
        from sci_rag.llm import get_llm

        llm = get_llm(settings, role="extraction")
    metadata = await classify_documents(
        factory=factory, domain=domain, llm=llm, infer=metadata_enabled, auto_tags=metadata_enabled
    )
    result: dict[str, Any] = dict(
        mentions=mentions,
        metadata=asdict(metadata),
        graph_status="disabled_by_option" if not update_graph else "disabled_no_generation",
    )
    if model_enabled:
        from sci_rag.graph import build_communities, extract_graph

        assert llm is not None

        extraction = await extract_graph(
            session_factory=factory, llm=llm, domain=domain, batch_size=1
        )
        result.update(
            graph_status="success" if not extraction.batches_failed else "failed",
            extraction=asdict(extraction),
        )
        if changed or extraction.chunks_processed:
            communities = await build_communities(
                session_factory=factory, llm=llm, embedder=embedder, domain=domain
            )
            result["communities"] = asdict(communities)
            if communities.llm_summary_failures:
                result["graph_status"] = "degraded_summary_fallback"
    return result


async def refresh_corpus(
    *,
    root: Path,
    channel: str = "manual",
    manifest: Path | None = None,
    embedder: EmbeddingProvider | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    prefer_docling: bool = True,
    update_graph: bool = True,
) -> dict[str, Any]:
    if channel not in {"manual", "scheduler", "hooks", "poll"}:
        raise ValueError("invalid_refresh_channel")
    factory = session_factory or get_session_factory()
    result: dict[str, Any] = dict(
        status="failed", exit_code=1, channel=channel, run_id=new_id(), counts={}, source_files=0
    )
    root_key = _key(root)
    started = time.perf_counter()
    try:
        async with _single_reconcile(factory):
            async with factory() as session:
                await session.execute(
                    update(FileEvent)
                    .where(
                        FileEvent.root_key == root_key,
                        FileEvent.kind == "run",
                        FileEvent.status == "running",
                    )
                    .values(status="interrupted", error_code="process_interrupted")
                )
                previous_status = await session.scalar(
                    select(FileEvent.status)
                    .where(FileEvent.root_key == root_key, FileEvent.kind == "run")
                    .order_by(FileEvent.created_at.desc(), FileEvent.id)
                    .limit(1)
                )
                event = FileEvent(
                    id=result["run_id"],
                    run_id=result["run_id"],
                    root_key=root_key,
                    channel=channel,
                    kind="run",
                    status="running",
                )
                session.add(event)
                await session.commit()
            try:
                if not root.is_dir() or (
                    manifest is not None and manifest.parent.resolve() != root.resolve()
                ):
                    raise ValueError("invalid_refresh_root")
                entries = load_manifest(manifest) if manifest else discover_folder(root)
                selected = embedder or get_embedder(get_settings())
                report = await reconcile_entries(
                    entries,
                    root=root,
                    session_factory=factory,
                    embedder=selected,
                    prefer_docling=prefer_docling,
                    _locked=True,
                )
                knowledge = await _knowledge(
                    factory,
                    selected,
                    update_graph=update_graph,
                    changed=report.graph_changed or previous_status in {"failed", "interrupted"},
                )
                from sci_rag.memory_state import maintain_lifecycle

                knowledge["memory"] = await maintain_lifecycle(factory)
                failed = (
                    bool(report.failed)
                    or knowledge["graph_status"] in {"failed", "degraded_summary_fallback"}
                    or bool(knowledge["metadata"].get("inference_failed", 0))
                    or bool(knowledge["metadata"].get("tags_failed", 0))
                )
                result.update(
                    status="failed" if failed else "success",
                    exit_code=1 if failed else 0,
                    counts=report.counts(),
                    database_counts=report.counts(database=True),
                    source_files=len(entries),
                    parsers=report.parser_counts(),
                    knowledge=knowledge,
                )
                async with factory() as session:
                    for row in report.outcomes:
                        code = (
                            row.detail
                            if row.status == "failed" and re.fullmatch(r"[a-z0-9_:.-]+", row.detail)
                            else "source_failed"
                            if row.status == "failed"
                            else None
                        )
                        session.add(
                            FileEvent(
                                run_id=result["run_id"],
                                root_key=root_key,
                                path_key=_key(Path(row.path)) if row.path else None,
                                channel=channel,
                                kind="source" if row in report.source_outcomes else "database",
                                status=row.status,
                                error_code=code,
                                counts=dict(documents=row.document_count, chunks=row.chunk_count),
                            )
                        )
                    await session.commit()
            except Exception as exc:
                result.update(
                    status="failed",
                    exit_code=1,
                    error_code=str(exc)
                    if isinstance(exc, ValueError) and str(exc) == "invalid_refresh_root"
                    else type(exc).__name__,
                )
            result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            async with factory() as session:
                run_event = await session.get(FileEvent, result["run_id"])
                assert run_event is not None
                run_event.status = result["status"]
                run_event.error_code = result.get("error_code") or (
                    "source_or_graph_failed" if result["exit_code"] else None
                )
                run_event.counts = {
                    "source_files": result["source_files"],
                    **result["counts"],
                    "elapsed_ms": result["elapsed_ms"],
                }
                await session.commit()
    except ReconcileBusyError:
        result.update(status="busy", exit_code=2, error_code="reconcile_already_running")
    return result


async def refresh_history(
    factory: async_sessionmaker[AsyncSession], *, limit: int = 20
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("invalid_event_limit")
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(FileEvent)
                    .where(FileEvent.kind == "run")
                    .order_by(FileEvent.created_at.desc(), FileEvent.id)
                    .limit(limit)
                )
            ).all()
        )
    return {
        "runs": [
            dict(
                run_id=row.run_id,
                channel=row.channel,
                status=row.status,
                error_code=row.error_code,
                counts=row.counts,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    }
