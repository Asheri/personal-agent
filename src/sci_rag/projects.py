"""Explicit project ownership and bounded, evidence-checked personal metadata."""

from __future__ import annotations

import fnmatch
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db.models import Chunk, Document, KgEntity, Project
from sci_rag.domain import DomainProfile
from sci_rag.licensing import EXTERNAL_SAFE_CLASSES
from sci_rag.llm import LLMClient
from sci_rag.versions import lock_document_writes

HEAD_CHARS = 4000


@dataclass(frozen=True)
class ProjectRule:
    project: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    priority: int = 0

    def matches(self, path: str) -> bool:
        normalized = os.path.normcase(path).replace("\\", "/")

        def matches(pattern: str) -> bool:
            return fnmatch.fnmatchcase(normalized, os.path.normcase(pattern).replace("\\", "/"))

        return any(matches(p) for p in self.include) and not any(matches(p) for p in self.exclude)


def load_project_rules(path: Path) -> list[ProjectRule]:
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Project rules must be an ordered list")
    rules = []
    for row in payload:
        if not isinstance(row, dict) or set(row) - {"project", "include", "exclude", "priority"}:
            raise ValueError("Invalid project rule fields")
        project, include, exclude = row.get("project"), row.get("include"), row.get("exclude", [])
        priority = row.get("priority", 0)
        if (
            not isinstance(project, str)
            or not project.strip()
            or not isinstance(include, list)
            or not include
            or not all(isinstance(p, str) and p for p in include)
            or not isinstance(exclude, list)
            or not all(isinstance(p, str) and p for p in exclude)
            or type(priority) is not int
        ):
            raise ValueError("Rules require a project, nonempty glob list, and integer priority")
        rules.append(ProjectRule(project, tuple(include), tuple(exclude), priority))
    return sorted(rules, key=lambda r: -r.priority)


async def _project(session: AsyncSession, reference: str) -> Project:
    row = await session.scalar(select(Project).where(Project.id == reference))
    if row is None:
        row = await session.scalar(select(Project).where(Project.slug == reference))
    if row is None:
        row = await session.scalar(
            select(Project).where(func.lower(Project.name) == reference.lower())
        )
    if row is None:
        raise ValueError("project_not_found")
    return row


async def create_project(factory: async_sessionmaker[AsyncSession], name: str) -> Project:
    name = " ".join(name.split())
    if not name or len(name) > 200:
        raise ValueError("Project name must contain 1 to 200 characters")
    async with factory() as session:
        await lock_document_writes(session)
        found = await session.scalar(
            select(Project).where(func.lower(Project.name) == name.lower())
        )
        if found is not None:
            return found
        base = re.sub(r"[^\w]+", "-", name.lower()).strip("-_") or "project"
        slug, suffix = base, 1
        while await session.scalar(select(Project.id).where(Project.slug == slug)):
            suffix += 1
            slug = f"{base}-{suffix}"
        row = Project(name=name, slug=slug)
        session.add(row)
        await session.commit()
        return row


async def list_projects(factory: async_sessionmaker[AsyncSession]) -> list[tuple[Project, int]]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(Project, func.count(Document.id))
                .outerjoin(
                    Document,
                    (Document.project_id == Project.id) & Document.is_current.is_(True),
                )
                .group_by(Project.id)
                .order_by(Project.slug)
            )
        ).all()
        return [(project, count) for project, count in rows]


async def assign_project(
    factory: async_sessionmaker[AsyncSession], document_id: str, reference: str
) -> None:
    async with factory() as session:
        await lock_document_writes(session)
        document = await session.get(Document, document_id)
        if document is None or not document.is_current:
            raise ValueError("current_document_not_found")
        project = await _project(session, reference)
        document.project_id, document.project_source = project.id, "manual"
        document.extra = {**document.extra, "project_confidence": 1.0, "project_evidence": "manual"}
        await session.commit()


def normalize_tags(values: Any, *, people: list[str] | None = None) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError("Tags must be a string list")
    result = []
    for value in values:
        tag = " ".join(value.lower().split())
        if not tag or len(tag) > 64 or not all(c.isalnum() or c.isspace() for c in tag):
            continue
        if any(p.casefold() in tag.casefold() for p in people or [] if len(p.strip()) >= 2):
            continue
        if tag not in result:
            result.append(tag)
    return result[:8]


async def set_manual_tags(
    factory: async_sessionmaker[AsyncSession], document_id: str, tags: list[str]
) -> None:
    if not all(isinstance(tag, str) and 0 < len(tag.strip()) <= 64 for tag in tags):
        raise ValueError("Manual tags must contain 1 to 64 characters")
    normalized = list(dict.fromkeys(tag.strip() for tag in tags))
    async with factory() as session:
        await lock_document_writes(session)
        document = await session.get(Document, document_id)
        if document is None or not document.is_current:
            raise ValueError("current_document_not_found")
        document.tags = normalized
        await session.commit()


@dataclass
class MetadataStats:
    documents_processed: int = 0
    manual_kept: int = 0
    rules_assigned: int = 0
    inferred_assigned: int = 0
    inference_failed: int = 0
    tags_written: int = 0
    tags_failed: int = 0
    outbound_skipped: int = 0


async def check_project_rules(
    factory: async_sessionmaker[AsyncSession], rules: list[ProjectRule]
) -> list[str]:
    async with factory() as session:
        resolved = [(rule, (await _project(session, rule.project)).id) for rule in rules]
        documents = (
            await session.scalars(select(Document).where(Document.is_current.is_(True)))
        ).all()
        return [
            d.id
            for d in documents
            if len(
                {
                    project_id
                    for rule, project_id in resolved
                    if rule.matches(d.extra.get("path", ""))
                }
            )
            > 1
        ]


def _inference(
    payload: Any, projects: list[Project], head: str
) -> tuple[Project, float, str] | None:
    if not isinstance(payload, dict):
        raise ValueError("Invalid project response")
    name, confidence, evidence = (
        payload.get("project"),
        payload.get("confidence"),
        payload.get("evidence"),
    )
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ValueError("Invalid confidence")
    if name is None or confidence < 0.5:
        return None
    candidates = [p for p in projects if name == p.name or name == p.id]
    if not candidates or not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("Unknown project or missing evidence")
    if " ".join(evidence.casefold().split()) not in " ".join(head.casefold().split()):
        raise ValueError("Project evidence is absent from source")
    return candidates[0], float(confidence), evidence[:1000]


async def classify_documents(
    *,
    factory: async_sessionmaker[AsyncSession],
    domain: DomainProfile,
    llm: LLMClient | None = None,
    rules: list[ProjectRule] | None = None,
    infer: bool = True,
    auto_tags: bool = True,
) -> MetadataStats:
    """Keep stronger ownership, use quoted evidence, and never infer rights."""
    stats = MetadataStats()
    rules = (
        rules if rules is not None else load_project_rules(domain.directory / "project_rules.yaml")
    )
    async with factory() as session:
        ids = list(
            (
                await session.scalars(
                    select(Document.id).where(Document.is_current.is_(True)).order_by(Document.id)
                )
            ).all()
        )
    for document_id in ids:
        async with factory() as session:
            await lock_document_writes(session)
            document = await session.get(Document, document_id)
            if document is None or not document.is_current:
                continue
            projects = list((await session.scalars(select(Project).order_by(Project.slug))).all())
            resolved = [(rule, await _project(session, rule.project)) for rule in rules]
            chunks = list(
                (
                    await session.scalars(
                        select(Chunk)
                        .where(Chunk.document_id == document.id)
                        .order_by(Chunk.chunk_index)
                    )
                ).all()
            )
            head = "\n\n".join(c.content for c in chunks)[:HEAD_CHARS]
            match = next(
                (p for rule, p in resolved if rule.matches(document.extra.get("path", ""))), None
            )
            stats.documents_processed += 1
            if document.project_source == "manual":
                stats.manual_kept += 1
            elif match is not None:
                document.project_id, document.project_source = match.id, "rule"
                document.extra = {
                    **document.extra,
                    "project_confidence": 1.0,
                    "project_evidence": "directory_rule",
                }
                stats.rules_assigned += 1
            needs_inference = (
                infer and projects and document.project_source not in {"manual", "rule"}
            )
            if llm is None or (not needs_inference and not auto_tags):
                await session.commit()
                continue
            if document.license_class not in EXTERNAL_SAFE_CLASSES:
                stats.outbound_skipped += 1
                await session.commit()
                continue
            slots = {
                "HEAD_CHARS": str(HEAD_CHARS),
                "FILE_NAME": Path(document.extra.get("path", document.title)).name,
                "HEAD": head,
            }
            if needs_inference:
                try:
                    payload = await llm.generate_json(
                        domain.render_prompt(
                            "project_inference",
                            **slots,
                            PROJECT_LIST=json.dumps(
                                [{"id": p.id, "name": p.name} for p in projects], ensure_ascii=False
                            ),
                        ),
                        max_tokens=512,
                    )
                    decision = _inference(payload, projects, head)
                    if decision:
                        project, confidence, evidence = decision
                        document.project_id, document.project_source = project.id, "inferred"
                        document.extra = {
                            **document.extra,
                            "project_confidence": confidence,
                            "project_evidence": evidence,
                        }
                        stats.inferred_assigned += 1
                except Exception:
                    stats.inference_failed += 1
            if auto_tags:
                try:
                    people = list(
                        (
                            await session.scalars(
                                select(KgEntity.name).where(
                                    KgEntity.entity_type == "Person",
                                    KgEntity.document_ids.contains([document.id]),
                                )
                            )
                        ).all()
                    )
                    payload = await llm.generate_json(
                        domain.render_prompt("tag_extraction", **slots),
                        max_tokens=256,
                    )
                    if not isinstance(payload, dict) or "tags" not in payload:
                        raise ValueError("Invalid tag response")
                    document.auto_tags = normalize_tags(
                        payload["tags"], people=[*people, *document.authors]
                    )
                    stats.tags_written += 1
                except Exception:
                    stats.tags_failed += 1
            await session.commit()
    return stats
