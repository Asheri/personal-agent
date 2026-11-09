"""Pointer-only Agent routes and patches derived from confirmed successful work."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCENES = {"task_start", "retrieval", "file_write", "task_end", "scheduled"}
ALLOWED = {
    "browse_corpus",
    "list_projects",
    "search_corpus",
    "get_document_versions",
    "refresh",
    "complete_task",
    "maintain_memory",
}


class MemoryRouter:
    def __init__(
        self, *, memory_dir: Path, invoke: Callable[[str, dict[str, Any]], dict[str, Any]]
    ) -> None:
        self.directory = memory_dir
        self.invoke = invoke
        self.performed: dict[str, set[str]] = {}
        self.categories: dict[str, str] = {}
        self.failed_tasks: set[str] = set()

    def _append(self, name: str, text: str) -> None:
        target = self.directory / name
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        self._patch(name, old + text)

    def _patch(self, name: str, new: str) -> None:
        target = self.directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        if new == old:
            return
        if name == "global_mem_insight.txt" and len(new.splitlines()) > 30:
            raise ValueError("memory_index_line_limit")
        patch = "".join(
            difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), fromfile=name, tofile=name
            )
        )
        patches = self.directory / "patches"
        patches.mkdir(exist_ok=True)
        key = hashlib.sha256((name + new).encode()).hexdigest()
        (patches / (key + ".patch")).write_text(patch, encoding="utf-8")
        if new.startswith(old):
            with target.open("a", encoding="utf-8") as stream:
                stream.write(new[len(old) :])
        else:
            # Apply only the managed hot-pointer block; retain all other lines.
            with target.open("r+", encoding="utf-8") as stream:
                stream.seek(0)
                stream.write(new)
                stream.truncate()

    def _hot_index(self, ids: list[str]) -> None:
        target = self.directory / "global_mem_insight.txt"
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        base = re.sub(r"(?ms)^<!-- PCMEM HOT START -->\n.*?^<!-- PCMEM HOT END -->\n?", "", old)
        capacity = max(0, 30 - len(base.splitlines()) - 2)
        pointers = [
            key for key in ids if isinstance(key, str) and re.fullmatch("[a-f0-9]{32}", key)
        ][:capacity]
        if not pointers:
            return
        block = (
            "<!-- PCMEM HOT START -->\n"
            + "".join("doc_id=" + key + "\n" for key in pointers)
            + "<!-- PCMEM HOT END -->\n"
        )
        self._patch(
            "global_mem_insight.txt",
            base + ("" if not base or base.endswith("\n") else "\n") + block,
        )

    def sop(self, category: str) -> Path:
        if category not in SCENES:
            raise ValueError("unknown_memory_category")
        return self.directory / ("pcmem_" + category + "_sop.md")

    def _confirmed(self, task_id: str) -> bool:
        operations = self.performed.get(task_id, set())
        category = self.categories.get(task_id, "retrieval")
        if not operations or not operations <= ALLOWED or task_id in self.failed_tasks:
            return False
        key = hashlib.sha256(task_id.encode()).hexdigest()
        target = self.directory / "task_receipts.jsonl"
        receipts = (
            [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line]
            if target.exists()
            else []
        )
        if any(row["task_key"] == key for row in receipts):
            return False
        self.directory.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(dict(task_key=key, category=category, operations=sorted(operations)))
                + "\n"
            )
        if (
            sum(row["category"] == category for row in receipts) + 1 >= 3
            and not self.sop(category).exists()
        ):
            recipes = {
                "retrieval": 'sci-rag retrieve "<question>" --profile deep',
                "task_start": "sci-rag browse projects",
                "file_write": 'sci-rag refresh run "<corpus-root>" --channel hooks',
                "scheduled": 'sci-rag refresh run "<corpus-root>" --channel scheduler',
            }
            recipe = recipes.get(category, "sci-rag doctor")
            self._append(
                self.sop(category).name,
                f"# Verified {category} procedure\n\nReused after three confirmed successful tasks.\nRun `{recipe}`. Inspect returned status and document ids.\nRead related versions when needed. Keep only source pointers in memory.\nNever infer successful execution or copy private source text.\n",
            )
            index = self.directory / "global_mem_insight.txt"
            existing = index.read_text(encoding="utf-8") if index.exists() else ""
            if len(existing.splitlines()) >= 30:
                block = re.search(
                    r"(?ms)^<!-- PCMEM HOT START -->\n.*?^<!-- PCMEM HOT END -->\n?", existing
                )
                matches = (
                    list(
                        re.finditer(
                            r"(?m)^doc_id=[a-f0-9]{32}\n", existing[block.start() : block.end()]
                        )
                    )
                    if block
                    else []
                )
                if matches:
                    match = matches[-1]
                    assert block is not None
                    existing = (
                        existing[: block.start() + match.start()]
                        + existing[block.start() + match.end() :]
                    )
                    self._patch("global_mem_insight.txt", existing)
            if len(existing.splitlines()) < 30:
                self._append("global_mem_insight.txt", f"L3: {self.sop(category).name}\n")
            self._append(
                "global_mem.txt", f"- Verified reusable procedure: {self.sop(category).name}\n"
            )
        return True

    def route(
        self,
        scene: str,
        *,
        query: str = "",
        project_id: str | None = None,
        path: str | None = None,
        task_id: str = "current",
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if scene not in SCENES:
            raise ValueError("unknown_memory_scene")
        self.directory.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "query": query,
            "project_id": project_id,
            "path": path,
            "scene": scene,
        }
        plans = {
            "task_start": ["list_projects", "browse_corpus"],
            "retrieval": ["search_corpus"],
            "file_write": ["refresh", "get_document_versions"],
            "task_end": ["complete_task"],
            "scheduled": ["refresh", "maintain_memory"],
        }
        successful = []
        failed = []
        ids = set()
        project_ids = set()
        topic_ids: set[str] = set()
        for operation in plans[scene]:
            try:
                result = self.invoke(operation, payload)
                ok = (
                    result.get("status") not in {"failed", "error", "disabled", "busy"}
                    and result.get("exit_code", 0) == 0
                )
            except Exception:
                result = {}
                ok = False
            if ok:
                for row in result.get("projects", []):
                    if (
                        isinstance(row, dict)
                        and isinstance(key := row.get("id"), str)
                        and re.fullmatch("[a-f0-9]{32}", key)
                    ):
                        project_ids.add(key)
                topic_ids.update(
                    key
                    for key in result.get("topic_ids", [])
                    if isinstance(key, str) and re.fullmatch("[a-f0-9]{32}", key)
                )
                if operation == "maintain_memory":
                    self._hot_index(result.get("hot_document_ids", []))
                successful.append(operation)
                if operation != "complete_task":
                    self.performed.setdefault(task_id, set()).add(operation)
                lists = [
                    value
                    for name in ("results", "documents")
                    if isinstance(value := result.get(name), list)
                ]
                for row in [row for values in lists for row in values if isinstance(row, dict)]:
                    key = row.get("document_id") or row.get("id")
                    if isinstance(key, str) and re.fullmatch("[a-f0-9]{32}", key):
                        ids.add(key)
            else:
                failed.append(operation)
                self.failed_tasks.add(task_id)
            with (self.directory / "router_events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        dict(scene=scene, operation=operation, status="success" if ok else "failed")
                    )
                    + "\n"
                )
        if scene != "task_end" and successful:
            self.categories[task_id] = scene
        recorded = (
            self._confirmed(task_id) if scene == "task_end" and confirmed and successful else False
        )
        return dict(
            scene=scene,
            status="success" if not failed else "failed",
            operations=successful,
            failed_operations=failed,
            document_ids=sorted(ids),
            project_ids=sorted(project_ids),
            topic_ids=sorted(topic_ids),
            memory_recorded=recorded,
            sop=self.sop(self.categories.get(task_id, "retrieval")).name
            if self.sop(self.categories.get(task_id, "retrieval")).exists()
            else None,
        )
