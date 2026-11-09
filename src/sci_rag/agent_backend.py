"""Local CLI adapter keeps source bodies out of GenericAgent memory injection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from sci_rag.db import Document, get_session_factory
from sci_rag.licensing import EXTERNAL_SAFE_CLASSES
from sci_rag.versions import canonical_source_path

# `subprocess.CREATE_NO_WINDOW` exists on Windows only. `getattr` keeps the
# module importable, and type-checkable, on macOS and Linux.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


async def agent_operation(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    from sci_rag.memory_state import maintain_lifecycle
    from sci_rag.refresh import refresh_corpus
    from sci_rag.server.service import RagService

    filters: dict[str, Any] = {"license_classes": list(EXTERNAL_SAFE_CLASSES)}
    if payload.get("project_id"):
        filters["projects"] = [payload["project_id"]]
    factory = get_session_factory()
    if operation == "refresh":
        configured = os.environ.get("PCMEM_CORPUS_ROOT")
        if not configured:
            return dict(status="disabled", error_code="corpus_root_not_configured")
        root = Path(configured).resolve()
        path = payload.get("path")
        if path and not Path(path).resolve().is_relative_to(root):
            return dict(status="disabled", error_code="write_out_of_scope")
        manifest = os.environ.get("PCMEM_CORPUS_MANIFEST")
        return await refresh_corpus(
            root=root,
            channel="scheduler" if payload.get("scene") == "scheduled" else "hooks",
            manifest=Path(manifest) if manifest else None,
        )
    if operation == "maintain_memory":
        result_state = await maintain_lifecycle(factory)
        async with factory() as session:
            allowed = set(
                (
                    await session.scalars(
                        select(Document.id).where(
                            Document.id.in_(result_state["hot_document_ids"]),
                            Document.license_class.in_(EXTERNAL_SAFE_CLASSES),
                            Document.is_current.is_(True),
                        )
                    )
                ).all()
            )
        result_state["hot_document_ids"] = [
            key for key in result_state["hot_document_ids"] if key in allowed
        ]
        return result_state
    if operation == "complete_task":
        return {"status": "success"}
    service = RagService()
    if operation == "list_projects":
        return await service.list_projects(filters=filters)
    if operation == "browse_corpus":
        documents = await service.browse_corpus(filters=filters, page_size=5)
        overview = await service.topic_overview(filters=filters)
        documents["topic_ids"] = [row["id"] for row in overview["named_topics"]]
        return documents
    if operation == "search_corpus":
        result = await service.retrieve(
            str(payload.get("query") or ""),
            top_k=5,
            profile="interactive",
            license_classes=list(EXTERNAL_SAFE_CLASSES),
            projects=filters.get("projects"),
        )
        return {
            "results": [
                dict(document_id=item.document_id) for item in result.items if item.document_id
            ]
        }
    if operation == "get_document_versions":
        if not payload.get("path"):
            return {"versions": []}
        async with factory() as session:
            row = await session.scalar(
                select(Document)
                .where(
                    Document.extra["path"].astext == canonical_source_path(Path(payload["path"])),
                    Document.is_current.is_(True),
                    Document.license_class.in_(EXTERNAL_SAFE_CLASSES),
                )
                .order_by(Document.id)
                .limit(1)
            )
        if row is None:
            return {"versions": []}
        versions_result = await service.get_document_versions(
            row.id, scope=service.scope_from(**filters)
        )
        return {
            "versions": [
                dict(
                    document_id=version["document_id"],
                    is_current=version["is_current"],
                    freshness=version["freshness"],
                )
                for version in versions_result["versions"]
            ]
        }
    raise ValueError("unknown_agent_operation")


class CliAgentClient:
    def __init__(self, root: Path, python: str | None = None) -> None:
        self.root = root.resolve()
        self.python = python or sys.executable

    def __call__(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        directory = self.root / ".context/agent-tmp"
        directory.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "PYTHONPATH": str(self.root / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "TEMP": str(directory),
            "TMP": str(directory),
        }
        result = subprocess.run(
            [
                self.python,
                "-c",
                "from sci_rag.cli.main import app; app()",
                "agent",
                "call",
                operation,
            ],
            input=json.dumps(payload),
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            creationflags=_NO_WINDOW,
        )
        for line in reversed(result.stdout.splitlines()):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                return (
                    data
                    if result.returncode == 0
                    else {**data, "status": "failed", "exit_code": result.returncode}
                )
        return dict(
            status="failed", exit_code=result.returncode or 1, error_code="agent_backend_failed"
        )
