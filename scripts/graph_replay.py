"""Record or strictly replay graph extraction for the committed demo benchmark.

This is deliberately a benchmark script rather than a product setting. Refresh
accepts only an unstamped, graph-empty copy of the tracked public demo corpus.
Require validates every identity and rendered model call, then reuses the normal
extractor without constructing a provider client.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.db import (
    Chunk,
    Document,
    EntityResolutionAudit,
    KgCommunity,
    KgEntity,
    KgRelationship,
)
from sci_rag.domain import DomainProfile, load_domain
from sci_rag.evals.report import domain_digest, git_commit
from sci_rag.graph import ExtractionStats, extract_graph
from sci_rag.ingest import chunk_document, load_manifest, parse_file
from sci_rag.ingest.ingester import content_hash_for
from sci_rag.llm import LLMClient, get_llm, parse_json_loosely

SCHEMA_VERSION = 1
EXTRACTOR_CONTRACT_VERSION = 1
GENERATION_PARAMETERS: dict[str, object] = {
    "temperature": 0.0,
    "json_mode": True,
    "max_tokens": 8192,
}
ReplayMode = Literal["require", "refresh", "off"]


class GraphReplayError(RuntimeError):
    """The benchmark replay contract could not be proved safely."""


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GraphReplayError(f"replay value is not canonical JSON: {exc}") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _require_hex_digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GraphReplayError(f"artifact {field} must be a lowercase SHA-256 digest")
    return value


def _require_int(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GraphReplayError(f"artifact {field} must be an integer of at least {minimum}")
    return value


@dataclass(frozen=True)
class ReplayCall:
    """One ordered extraction call and the provider's untrusted raw completion."""

    order: int
    input_digest: str
    raw_completion: str

    def __post_init__(self) -> None:
        _require_int(self.order, "call order")
        _require_hex_digest(self.input_digest, "call input_digest")
        if not isinstance(self.raw_completion, str):
            raise GraphReplayError("artifact call raw_completion must be text")

    def to_dict(self) -> dict[str, object]:
        return {
            "order": self.order,
            "input_digest": self.input_digest,
            "raw_completion": self.raw_completion,
        }

    @classmethod
    def from_dict(cls, value: object) -> ReplayCall:
        if not isinstance(value, dict):
            raise GraphReplayError("artifact call must be an object")
        expected = {"order", "input_digest", "raw_completion"}
        if set(value) != expected:
            raise GraphReplayError(
                "artifact call fields must be exactly " + ", ".join(sorted(expected))
            )
        return cls(
            order=_require_int(value["order"], "call order"),
            input_digest=_require_hex_digest(value["input_digest"], "call input_digest"),
            raw_completion=cast(str, value["raw_completion"]),
        )


@dataclass(frozen=True)
class ReplayArtifact:
    """Versioned, content-addressed extraction evidence for the public demo."""

    schema_version: int
    extractor_contract_version: int
    created_at: str
    source_commit: str
    corpus_digest: str
    extraction_model: str
    domain_digest: str
    batch_size: int
    generation_parameters: Mapping[str, object]
    calls: Sequence[ReplayCall]
    successful_batches: int
    split_batches: int
    failed_batches: int
    entity_count: int
    relationship_count: int
    graph_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise GraphReplayError(
                f"unsupported replay schema version {self.schema_version}; expected {SCHEMA_VERSION}"
            )
        if self.extractor_contract_version != EXTRACTOR_CONTRACT_VERSION:
            raise GraphReplayError(
                "unsupported extractor contract version "
                f"{self.extractor_contract_version}; expected {EXTRACTOR_CONTRACT_VERSION}"
            )
        try:
            datetime.fromisoformat(self.created_at)
        except (TypeError, ValueError) as exc:
            raise GraphReplayError("artifact created_at must be an ISO-8601 timestamp") from exc
        if not self.source_commit:
            raise GraphReplayError("artifact source_commit must not be empty")
        _require_hex_digest(self.corpus_digest, "corpus_digest")
        _require_hex_digest(self.domain_digest, "domain_digest")
        _require_hex_digest(self.graph_digest, "graph_digest")
        if not self.extraction_model:
            raise GraphReplayError("artifact extraction_model must not be empty")
        _require_int(self.batch_size, "batch_size", minimum=1)
        for field, value in (
            ("successful_batches", self.successful_batches),
            ("split_batches", self.split_batches),
            ("failed_batches", self.failed_batches),
            ("entity_count", self.entity_count),
            ("relationship_count", self.relationship_count),
        ):
            _require_int(value, field)
        if not isinstance(self.generation_parameters, Mapping):
            raise GraphReplayError("artifact generation_parameters must be an object")
        _canonical_json(dict(self.generation_parameters))
        if any(call.order != index for index, call in enumerate(self.calls)):
            raise GraphReplayError("artifact call order must be contiguous from zero")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "extractor_contract_version": self.extractor_contract_version,
            "created_at": self.created_at,
            "source_commit": self.source_commit,
            "corpus_digest": self.corpus_digest,
            "extraction_model": self.extraction_model,
            "domain_digest": self.domain_digest,
            "batch_size": self.batch_size,
            "generation_parameters": dict(self.generation_parameters),
            "calls": [call.to_dict() for call in self.calls],
            "successful_batches": self.successful_batches,
            "split_batches": self.split_batches,
            "failed_batches": self.failed_batches,
            "entity_count": self.entity_count,
            "relationship_count": self.relationship_count,
            "graph_digest": self.graph_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> ReplayArtifact:
        if not isinstance(value, dict):
            raise GraphReplayError("replay artifact must be a JSON object")
        expected = {
            "schema_version",
            "extractor_contract_version",
            "created_at",
            "source_commit",
            "corpus_digest",
            "extraction_model",
            "domain_digest",
            "batch_size",
            "generation_parameters",
            "calls",
            "successful_batches",
            "split_batches",
            "failed_batches",
            "entity_count",
            "relationship_count",
            "graph_digest",
        }
        if set(value) != expected:
            missing = sorted(expected - set(value))
            unexpected = sorted(set(value) - expected)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unexpected:
                details.append("unexpected " + ", ".join(unexpected))
            raise GraphReplayError("artifact shape mismatch: " + "; ".join(details))
        calls = value["calls"]
        if not isinstance(calls, list):
            raise GraphReplayError("artifact calls must be a list")
        generation_parameters = value["generation_parameters"]
        if not isinstance(generation_parameters, dict):
            raise GraphReplayError("artifact generation_parameters must be an object")
        string_fields = (
            "created_at",
            "source_commit",
            "extraction_model",
        )
        if any(not isinstance(value[field], str) for field in string_fields):
            raise GraphReplayError("artifact text identity fields must be strings")
        return cls(
            schema_version=_require_int(value["schema_version"], "schema_version"),
            extractor_contract_version=_require_int(
                value["extractor_contract_version"], "extractor_contract_version"
            ),
            created_at=cast(str, value["created_at"]),
            source_commit=cast(str, value["source_commit"]),
            corpus_digest=_require_hex_digest(value["corpus_digest"], "corpus_digest"),
            extraction_model=cast(str, value["extraction_model"]),
            domain_digest=_require_hex_digest(value["domain_digest"], "domain_digest"),
            batch_size=_require_int(value["batch_size"], "batch_size", minimum=1),
            generation_parameters=cast(dict[str, object], generation_parameters),
            calls=[ReplayCall.from_dict(call) for call in calls],
            successful_batches=_require_int(value["successful_batches"], "successful_batches"),
            split_batches=_require_int(value["split_batches"], "split_batches"),
            failed_batches=_require_int(value["failed_batches"], "failed_batches"),
            entity_count=_require_int(value["entity_count"], "entity_count"),
            relationship_count=_require_int(value["relationship_count"], "relationship_count"),
            graph_digest=_require_hex_digest(value["graph_digest"], "graph_digest"),
        )


def artifact_sha256(artifact: ReplayArtifact) -> str:
    """Stable identity over the complete artifact without a self-reference."""
    return _sha256(artifact.to_dict())


def call_input_digest(
    *,
    order: int,
    prompt: str,
    system: str | None,
    temperature: float,
    json_mode: bool,
    max_tokens: int,
    generation_parameters: Mapping[str, object],
    extractor_contract_version: int,
) -> str:
    """Hash every input that can change one extraction completion."""
    return _sha256(
        {
            "order": order,
            "prompt": prompt,
            "system": system,
            "temperature": temperature,
            "json_mode": json_mode,
            "max_tokens": max_tokens,
            "generation_parameters": dict(generation_parameters),
            "extractor_contract_version": extractor_contract_version,
        }
    )


def write_candidate(artifact: ReplayArtifact, artifact_dir: Path) -> Path:
    """Atomically create one content-addressed candidate and never replace it."""
    digest = artifact_sha256(artifact)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    destination = artifact_dir / f"{digest}.json"
    body = json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=artifact_dir,
            prefix=f".{digest}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise GraphReplayError(f"replay candidate already exists at {destination}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def _load_artifact(path: Path) -> ReplayArtifact:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphReplayError(f"cannot load replay artifact {path}: {exc}") from exc
    artifact = ReplayArtifact.from_dict(raw)
    digest = artifact_sha256(artifact)
    if path.stem != digest:
        raise GraphReplayError(
            f"artifact filename digest mismatch: expected {digest}.json, got {path.name}"
        )
    return artifact


class ReplayLLM(LLMClient):
    """An extraction client that consumes every recorded call exactly once."""

    model = "benchmark-replay"

    def __init__(
        self,
        calls: Sequence[ReplayCall],
        *,
        extractor_contract_version: int,
        generation_parameters: Mapping[str, object],
    ) -> None:
        self._calls = tuple(calls)
        self._position = 0
        self._contract_version = extractor_contract_version
        self._generation_parameters = dict(generation_parameters)
        self._failure: GraphReplayError | None = None

    @property
    def consumed_call_count(self) -> int:
        return self._position

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        if self._position >= len(self._calls):
            error = GraphReplayError(f"missing recorded call at order {self._position}")
            self._failure = error
            raise error
        expected = self._calls[self._position]
        actual_digest = call_input_digest(
            order=self._position,
            prompt=prompt,
            system=system,
            temperature=temperature,
            json_mode=json_mode,
            max_tokens=max_tokens,
            generation_parameters=self._generation_parameters,
            extractor_contract_version=self._contract_version,
        )
        if actual_digest != expected.input_digest:
            error = GraphReplayError(
                f"replay call {self._position} input drift: expected "
                f"{expected.input_digest}, got {actual_digest}"
            )
            self._failure = error
            raise error
        self._position += 1
        return expected.raw_completion

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        return self._reject_stream()

    async def _reject_stream(self) -> AsyncIterator[str]:
        raise GraphReplayError("graph replay does not support streaming calls")
        yield ""  # pragma: no cover

    def assert_consumed(self) -> None:
        unused = len(self._calls) - self._position
        if self._failure is not None and unused:
            raise GraphReplayError(
                f"artifact has {unused} unused recorded call(s) after {self._failure}"
            ) from self._failure
        if self._failure is not None:
            raise self._failure
        if unused:
            raise GraphReplayError(f"artifact has {unused} unused recorded call(s)")


class RecordingLLM(LLMClient):
    """A provider wrapper that records raw completions and exact call inputs."""

    def __init__(
        self,
        delegate: LLMClient,
        *,
        extractor_contract_version: int,
        generation_parameters: Mapping[str, object],
    ) -> None:
        self._delegate = delegate
        self._contract_version = extractor_contract_version
        self._generation_parameters = dict(generation_parameters)
        self.calls: list[ReplayCall] = []
        self.model = delegate.model
        self.spec = delegate.spec

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        order = len(self.calls)
        digest = call_input_digest(
            order=order,
            prompt=prompt,
            system=system,
            temperature=temperature,
            json_mode=json_mode,
            max_tokens=max_tokens,
            generation_parameters=self._generation_parameters,
            extractor_contract_version=self._contract_version,
        )
        raw = await self._delegate.generate(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        self.calls.append(ReplayCall(order=order, input_digest=digest, raw_completion=raw))
        return raw

    async def generate_json(
        self, prompt: str, *, system: str | None = None, max_tokens: int = 4096
    ) -> Any:
        raw = await self.generate(
            prompt,
            system=system,
            temperature=0.0,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return parse_json_loosely(raw)

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        return self._reject_stream()

    async def _reject_stream(self) -> AsyncIterator[str]:
        raise GraphReplayError("graph recording does not support streaming calls")
        yield ""  # pragma: no cover


class _CountingLLM(LLMClient):
    """Count successful live calls for an off-mode receipt without retaining content."""

    def __init__(self, delegate: LLMClient) -> None:
        self._delegate = delegate
        self.call_count = 0
        self.model = delegate.model
        self.spec = delegate.spec

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        raw = await self._delegate.generate(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        self.call_count += 1
        return raw

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        return self._delegate.stream(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )


@dataclass(frozen=True)
class ReplayReceipt:
    mode: ReplayMode
    artifact_path: Path | None
    artifact_sha256: str | None
    extraction_model: str
    domain_digest: str
    corpus_digest: str
    snapshot: str | None
    replayed_calls: int
    extracted_calls: int
    split_count: int
    entity_count: int
    relationship_count: int
    graph_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "artifact_path": str(self.artifact_path) if self.artifact_path is not None else None,
            "artifact_sha256": self.artifact_sha256,
            "extraction_model": self.extraction_model,
            "domain_digest": self.domain_digest,
            "corpus_digest": self.corpus_digest,
            "snapshot": self.snapshot,
            "counts": {
                "entities": self.entity_count,
                "relationships": self.relationship_count,
            },
            "replayed_call_count": self.replayed_calls,
            "extracted_call_count": self.extracted_calls,
            "split_count": self.split_count,
            "graph_digest": self.graph_digest,
        }


@dataclass(frozen=True)
class _DocumentIdentity:
    content_hash: str
    title: str
    source: str
    license_class: str
    authors: tuple[str, ...]
    publication_year: int | None
    doi: str | None
    journal: str | None
    license_source: str | None
    page_count: int | None
    chunk_count: int


@dataclass(frozen=True)
class _CorpusState:
    digest: str
    document_hashes: tuple[str, ...]
    documents: tuple[_DocumentIdentity, ...]
    chunk_identities: tuple[tuple[str, int, str, int, str | None, bool], ...]
    document_count: int
    chunk_count: int
    non_demo_count: int
    non_public_count: int
    stamped_chunk_count: int
    entity_count: int
    relationship_count: int
    community_count: int
    resolution_audit_count: int


async def _corpus_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> _CorpusState:
    async with session_factory() as session:
        documents = (
            await session.execute(
                select(
                    Document.content_hash,
                    Document.title,
                    Document.source,
                    Document.license_class,
                    Document.authors,
                    Document.publication_year,
                    Document.doi,
                    Document.journal,
                    Document.license_source,
                    Document.page_count,
                    Document.chunk_count,
                ).order_by(Document.content_hash)
            )
        ).all()
        chunks = (
            await session.execute(
                select(
                    Document.content_hash,
                    Chunk.chunk_index,
                    Chunk.content,
                    Chunk.token_count,
                    Chunk.section_path,
                    Chunk.is_table,
                )
                .join(Document, Document.id == Chunk.document_id)
                .order_by(Document.content_hash, Chunk.chunk_index)
            )
        ).all()
        stamped = (
            await session.scalar(
                select(func.count(Chunk.id)).where(Chunk.graph_extracted_at.is_not(None))
            )
        ) or 0
        chunk_count = (await session.scalar(select(func.count(Chunk.id)))) or 0
        entity_count = (await session.scalar(select(func.count(KgEntity.id)))) or 0
        relationship_count = (await session.scalar(select(func.count(KgRelationship.id)))) or 0
        community_count = (await session.scalar(select(func.count(KgCommunity.id)))) or 0
        resolution_audit_count = (
            await session.scalar(select(func.count(EntityResolutionAudit.id)))
        ) or 0
    digest = hashlib.sha256(
        "\n".join(document.content_hash for document in documents).encode("utf-8")
    ).hexdigest()
    return _CorpusState(
        digest=digest,
        document_hashes=tuple(document.content_hash for document in documents),
        documents=tuple(
            _DocumentIdentity(
                content_hash=document.content_hash,
                title=document.title,
                source=document.source,
                license_class=document.license_class,
                authors=tuple(document.authors),
                publication_year=document.publication_year,
                doi=document.doi,
                journal=document.journal,
                license_source=document.license_source,
                page_count=document.page_count,
                chunk_count=document.chunk_count,
            )
            for document in documents
        ),
        chunk_identities=tuple(
            (
                chunk.content_hash,
                chunk.chunk_index,
                hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
                chunk.token_count,
                chunk.section_path,
                chunk.is_table,
            )
            for chunk in chunks
        ),
        document_count=len(documents),
        chunk_count=chunk_count,
        non_demo_count=sum(document.source != "demo_fixture" for document in documents),
        non_public_count=sum(document.license_class != "public" for document in documents),
        stamped_chunk_count=stamped,
        entity_count=entity_count,
        relationship_count=relationship_count,
        community_count=community_count,
        resolution_audit_count=resolution_audit_count,
    )


@dataclass(frozen=True)
class _TrackedDemoIdentity:
    document_hashes: tuple[str, ...]
    documents: tuple[_DocumentIdentity, ...]
    chunk_identities: tuple[tuple[str, int, str, int, str | None, bool], ...]


def _tracked_demo_identity(manifest_path: Path) -> _TrackedDemoIdentity:
    """Return the exact document and chunk identity produced by the demo sources."""
    try:
        entries = load_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        raise GraphReplayError(
            f"cannot validate tracked demo manifest: {type(exc).__name__}"
        ) from exc
    if not entries:
        raise GraphReplayError("tracked demo manifest contains no documents")

    hashes: list[str] = []
    documents: list[_DocumentIdentity] = []
    chunk_identities: list[tuple[str, int, str, int, str | None, bool]] = []
    for entry in entries:
        if entry.source != "demo_fixture" or entry.license_class != "public":
            raise GraphReplayError(
                "tracked demo manifest must contain only public demo_fixture documents"
            )
        try:
            parsed = parse_file(entry.path)
            drafts = chunk_document(parsed)
        except (OSError, ValueError) as exc:
            raise GraphReplayError(
                f"cannot validate a tracked demo document: {type(exc).__name__}"
            ) from exc
        if not drafts:
            raise GraphReplayError("tracked demo document produced no chunks")
        content_hash = content_hash_for(drafts)
        hashes.append(content_hash)
        documents.append(
            _DocumentIdentity(
                content_hash=content_hash,
                title=entry.title or parsed.title,
                source=entry.source,
                license_class=entry.license_class,
                authors=tuple(entry.authors),
                publication_year=entry.year,
                doi=entry.doi,
                journal=entry.journal,
                license_source=entry.license_source
                or ("manifest" if entry.license_class != "unknown" else None),
                page_count=parsed.page_count,
                chunk_count=len(drafts),
            )
        )
        chunk_identities.extend(
            (
                content_hash,
                index,
                hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
                draft.token_count,
                draft.section_path,
                draft.is_table,
            )
            for index, draft in enumerate(drafts)
        )
    if len(set(hashes)) != len(hashes):
        raise GraphReplayError("tracked demo manifest contains duplicate document content")
    return _TrackedDemoIdentity(
        document_hashes=tuple(sorted(hashes)),
        documents=tuple(sorted(documents, key=lambda document: document.content_hash)),
        chunk_identities=tuple(sorted(chunk_identities)),
    )


def _require_clean_tracked_demo_source(manifest_path: Path, source_commit: str) -> None:
    """Bind a refresh to clean, tracked demo inputs at its declared commit."""
    try:
        entries = load_manifest(manifest_path)
        repository = Path(
            subprocess.run(
                ["git", "-C", str(manifest_path.parent), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        ).resolve()
        paths = [
            manifest_path.resolve(),
            *(entry.path.resolve() for entry in entries),
            repository / "scripts" / "graph_replay.py",
            repository / "src" / "sci_rag" / "graph" / "extractor.py",
        ]
        relative_paths = [str(path.relative_to(repository)) for path in paths]
        tracked = subprocess.run(
            ["git", "-C", str(repository), "ls-files", "--error-unmatch", "--", *relative_paths],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if tracked.returncode != 0:
            raise GraphReplayError("graph refresh requires every demo source input to be tracked")
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        if dirty:
            raise GraphReplayError(
                "graph refresh refuses a dirty graph replay source checkout or "
                "dirty tracked demo source input"
            )
        actual_commit = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except GraphReplayError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise GraphReplayError(
            f"cannot bind graph refresh to tracked demo sources: {type(exc).__name__}"
        ) from exc
    if actual_commit != source_commit:
        raise GraphReplayError(
            "graph refresh source commit does not match the tracked demo checkout"
        )


def _require_tracked_demo(state: _CorpusState, manifest_path: Path) -> None:
    expected = _tracked_demo_identity(manifest_path)
    if (
        state.document_hashes != expected.document_hashes
        or state.documents != expected.documents
        or state.chunk_identities != expected.chunk_identities
    ):
        raise GraphReplayError(
            "graph replay database must exactly match the tracked demo manifest, documents, and chunks"
        )


def _require_pristine_demo(state: _CorpusState) -> None:
    if state.document_count == 0:
        raise GraphReplayError("graph replay requires the nonempty demo_fixture corpus")
    if state.chunk_count == 0:
        raise GraphReplayError("graph replay requires at least one unstamped demo chunk")
    if state.non_demo_count:
        raise GraphReplayError(
            f"graph replay requires source=demo_fixture; found {state.non_demo_count} other document(s)"
        )
    if state.non_public_count:
        raise GraphReplayError(
            f"graph replay requires license_class=public; found {state.non_public_count} other document(s)"
        )
    if state.stamped_chunk_count:
        raise GraphReplayError(
            "graph replay requires every target chunk to be unstamped; found "
            f"{state.stamped_chunk_count} stamped chunk(s)"
        )
    graph_rows = (
        state.entity_count
        + state.relationship_count
        + state.community_count
        + state.resolution_audit_count
    )
    if graph_rows:
        raise GraphReplayError(
            "graph replay requires empty graph tables; found "
            f"{state.entity_count} entities, {state.relationship_count} relationships, "
            f"{state.community_count} communities, and "
            f"{state.resolution_audit_count} resolution audit rows"
        )


async def _remaining_unstamped_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    async with session_factory() as session:
        return (
            await session.scalar(
                select(func.count(Chunk.id)).where(Chunk.graph_extracted_at.is_(None))
            )
        ) or 0


async def _canonical_graph(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[dict[str, object], int, int]:
    async with session_factory() as session:
        document_rows = (await session.execute(select(Document.id, Document.content_hash))).all()
        chunk_rows = (
            await session.execute(select(Chunk.id, Chunk.document_id, Chunk.chunk_index))
        ).all()
        entities = (await session.execute(select(KgEntity))).scalars().all()
        relationships = (await session.execute(select(KgRelationship))).scalars().all()

    document_hashes = {row.id: row.content_hash for row in document_rows}
    chunk_locators: dict[str, dict[str, object]] = {}
    for row in chunk_rows:
        document_hash = document_hashes.get(row.document_id)
        if document_hash is None:
            raise GraphReplayError(f"chunk {row.id} has no stable document locator")
        chunk_locators[row.id] = {
            "document_content_hash": document_hash,
            "chunk_index": row.chunk_index,
        }

    def document_locator(document_id: str) -> str:
        try:
            return document_hashes[document_id]
        except KeyError as exc:
            raise GraphReplayError(f"graph evidence names missing document {document_id}") from exc

    def chunk_locator(chunk_id: str) -> dict[str, object]:
        try:
            return chunk_locators[chunk_id]
        except KeyError as exc:
            raise GraphReplayError(f"graph evidence names missing chunk {chunk_id}") from exc

    entity_identity = {
        entity.id: {"name": entity.name, "entity_type": entity.entity_type} for entity in entities
    }
    canonical_entities = [
        {
            "name": entity.name,
            "entity_type": entity.entity_type,
            "description": entity.description,
            "aliases": sorted(entity.aliases or []),
            "documents": sorted(document_locator(value) for value in (entity.document_ids or [])),
            "chunks": sorted(
                (chunk_locator(value) for value in (entity.chunk_ids or [])),
                key=lambda item: (
                    cast(str, item["document_content_hash"]),
                    cast(int, item["chunk_index"]),
                ),
            ),
        }
        for entity in entities
    ]
    canonical_entities.sort(
        key=lambda item: (
            cast(str, item["name"]).casefold(),
            cast(str, item["entity_type"]).casefold(),
            _canonical_json(item),
        )
    )

    canonical_relationships: list[dict[str, object]] = []
    for relationship in relationships:
        source = entity_identity.get(relationship.source_entity_id)
        target = entity_identity.get(relationship.target_entity_id)
        if source is None or target is None:
            raise GraphReplayError(f"relationship {relationship.id} has a missing endpoint")
        canonical_relationships.append(
            {
                "source": source,
                "target": target,
                "relation_type": relationship.relation_type,
                "evidence": relationship.evidence,
                "confidence": relationship.confidence,
                "document": (
                    document_locator(relationship.document_id)
                    if relationship.document_id is not None
                    else None
                ),
                "chunk": (
                    chunk_locator(relationship.chunk_id)
                    if relationship.chunk_id is not None
                    else None
                ),
            }
        )
    canonical_relationships.sort(key=lambda item: _canonical_json(item))
    payload: dict[str, object] = {
        "entities": canonical_entities,
        "relationships": canonical_relationships,
    }
    return payload, len(canonical_entities), len(canonical_relationships)


def _successful_batches(call_count: int, stats: ExtractionStats) -> int:
    return max(0, call_count - stats.batches_split - stats.batches_failed)


def _require_identity(
    artifact: ReplayArtifact,
    *,
    corpus_digest: str,
    extraction_model: str,
    current_domain_digest: str,
    batch_size: int,
) -> None:
    if artifact.failed_batches:
        raise GraphReplayError(
            "replay artifact declares failed batches and cannot support a published graph"
        )
    mismatches: list[str] = []
    if artifact.corpus_digest != corpus_digest:
        mismatches.append("corpus digest")
    if artifact.extraction_model != extraction_model:
        mismatches.append("extraction model")
    if artifact.domain_digest != current_domain_digest:
        mismatches.append("domain digest")
    if artifact.batch_size != batch_size:
        mismatches.append("batch size")
    if dict(artifact.generation_parameters) != GENERATION_PARAMETERS:
        mismatches.append("generation parameters")
    if mismatches:
        raise GraphReplayError("replay identity drift: " + ", ".join(mismatches))


def _write_receipt(receipt: ReplayReceipt, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(receipt.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def run_graph_replay(
    *,
    mode: ReplayMode,
    receipt_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    domain: DomainProfile,
    extraction_model: str,
    llm_factory: Callable[[], LLMClient] | None = None,
    artifact_path: Path | None = None,
    artifact_dir: Path | None = None,
    source_commit: str | None = None,
    manifest_path: Path | None = None,
    snapshot: str | None = None,
    batch_size: int = 10,
    rate_limit_s: float = 0.2,
) -> ReplayReceipt:
    """Run one fail-closed benchmark extraction mode and write its receipt."""
    if mode not in {"require", "refresh", "off"}:
        raise GraphReplayError(f"unknown graph replay mode {mode!r}")
    if batch_size < 1:
        raise GraphReplayError("batch size must be at least one")
    if mode == "refresh" and not source_commit:
        raise GraphReplayError("refresh mode needs a nonempty source commit")
    if mode in {"require", "refresh"} and manifest_path is None:
        raise GraphReplayError(f"{mode} mode needs the explicit tracked demo manifest")
    if mode == "refresh":
        assert source_commit is not None
        assert manifest_path is not None
        _require_clean_tracked_demo_source(manifest_path, source_commit)
    state = await _corpus_state(session_factory)
    current_domain_digest = domain_digest(domain.directory)

    selected_artifact: ReplayArtifact | None = None
    selected_path: Path | None = None
    selected_sha: str | None = None
    replayed_calls = 0
    extracted_calls = 0

    if mode in {"require", "refresh"}:
        _require_pristine_demo(state)
        assert manifest_path is not None
        _require_tracked_demo(state, manifest_path)

    if mode == "require":
        if artifact_path is None:
            raise GraphReplayError("require mode needs an explicit artifact path")
        selected_path = artifact_path
        selected_artifact = _load_artifact(artifact_path)
        selected_sha = artifact_sha256(selected_artifact)
        _require_identity(
            selected_artifact,
            corpus_digest=state.digest,
            extraction_model=extraction_model,
            current_domain_digest=current_domain_digest,
            batch_size=batch_size,
        )
        replay = ReplayLLM(
            selected_artifact.calls,
            extractor_contract_version=selected_artifact.extractor_contract_version,
            generation_parameters=selected_artifact.generation_parameters,
        )
        stats = await extract_graph(
            session_factory=session_factory,
            llm=replay,
            domain=domain,
            batch_size=batch_size,
            rate_limit_s=rate_limit_s,
        )
        replay.assert_consumed()
        replayed_calls = replay.consumed_call_count
    else:
        if llm_factory is None:
            raise GraphReplayError(f"{mode} mode needs an extraction provider factory")
        provider = llm_factory()
        effective_model = provider.describe()
        if effective_model != extraction_model:
            raise GraphReplayError(
                "effective extraction model "
                f"{effective_model!r} does not match declared identity {extraction_model!r}"
            )
        if mode == "refresh":
            recording = RecordingLLM(
                provider,
                extractor_contract_version=EXTRACTOR_CONTRACT_VERSION,
                generation_parameters=GENERATION_PARAMETERS,
            )
            llm: LLMClient = recording
            counting = None
        else:
            recording = None
            counting = _CountingLLM(provider)
            llm = counting
        stats = await extract_graph(
            session_factory=session_factory,
            llm=llm,
            domain=domain,
            batch_size=batch_size,
            rate_limit_s=rate_limit_s,
        )
        extracted_calls = (
            len(recording.calls)
            if recording is not None
            else cast(_CountingLLM, counting).call_count
        )

    remaining_unstamped = await _remaining_unstamped_chunks(session_factory)
    if mode == "refresh" and (stats.batches_failed or remaining_unstamped):
        raise GraphReplayError(
            "refresh extraction is incomplete: "
            f"{stats.batches_failed} failed batch(es), "
            f"{remaining_unstamped} unstamped chunk(s); no artifact or receipt was written"
        )
    if mode == "require" and (stats.batches_failed or remaining_unstamped):
        raise GraphReplayError(
            "strict replay is incomplete: "
            f"{stats.batches_failed} failed batch(es), "
            f"{remaining_unstamped} unstamped chunk(s); no receipt was written"
        )

    canonical_graph, entity_count, relationship_count = await _canonical_graph(session_factory)
    graph_digest = _sha256(canonical_graph)

    if mode == "require":
        assert selected_artifact is not None
        observed_successful = _successful_batches(replayed_calls, stats)
        expected = (
            selected_artifact.successful_batches,
            selected_artifact.split_batches,
            selected_artifact.failed_batches,
            selected_artifact.entity_count,
            selected_artifact.relationship_count,
            selected_artifact.graph_digest,
        )
        observed = (
            observed_successful,
            stats.batches_split,
            stats.batches_failed,
            entity_count,
            relationship_count,
            graph_digest,
        )
        if observed != expected:
            raise GraphReplayError(
                f"replayed graph output drift: expected {expected!r}, observed {observed!r}"
            )
    elif mode == "refresh":
        assert recording is not None
        assert source_commit is not None
        if artifact_dir is None:
            raise GraphReplayError("refresh mode needs an artifact directory")
        selected_artifact = ReplayArtifact(
            schema_version=SCHEMA_VERSION,
            extractor_contract_version=EXTRACTOR_CONTRACT_VERSION,
            created_at=datetime.now(UTC).isoformat(),
            source_commit=source_commit,
            corpus_digest=state.digest,
            extraction_model=extraction_model,
            domain_digest=current_domain_digest,
            batch_size=batch_size,
            generation_parameters=GENERATION_PARAMETERS,
            calls=recording.calls,
            successful_batches=_successful_batches(extracted_calls, stats),
            split_batches=stats.batches_split,
            failed_batches=stats.batches_failed,
            entity_count=entity_count,
            relationship_count=relationship_count,
            graph_digest=graph_digest,
        )
        selected_path = write_candidate(selected_artifact, artifact_dir)
        selected_sha = artifact_sha256(selected_artifact)

    receipt = ReplayReceipt(
        mode=mode,
        artifact_path=selected_path,
        artifact_sha256=selected_sha,
        extraction_model=extraction_model,
        domain_digest=current_domain_digest,
        corpus_digest=state.digest,
        snapshot=snapshot,
        replayed_calls=replayed_calls,
        extracted_calls=extracted_calls,
        split_count=stats.batches_split,
        entity_count=entity_count,
        relationship_count=relationship_count,
        graph_digest=graph_digest,
    )
    _write_receipt(receipt, receipt_path)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("require", "refresh", "off"))
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/demo/graph-replay"))
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("eval_results/graph-replay-receipt.json"),
    )
    parser.add_argument("--snapshot")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--rate-limit-s", type=float, default=0.2)
    return parser


async def _run_cli(args: argparse.Namespace) -> ReplayReceipt:
    from sci_rag.config import get_settings
    from sci_rag.db import get_session_factory

    settings = get_settings()
    extraction_model = str(settings.model_spec_for("extraction"))
    return await run_graph_replay(
        mode=cast(ReplayMode, args.mode),
        artifact_path=cast(Path | None, args.artifact),
        artifact_dir=cast(Path, args.artifact_dir),
        receipt_path=cast(Path, args.receipt),
        session_factory=get_session_factory(),
        domain=load_domain(settings.domain_dir),
        extraction_model=extraction_model,
        llm_factory=lambda: get_llm(settings, role="extraction"),
        source_commit=git_commit(),
        manifest_path=Path("data/demo/manifest.jsonl"),
        snapshot=cast(str | None, args.snapshot),
        batch_size=cast(int, args.batch_size),
        rate_limit_s=cast(float, args.rate_limit_s),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = asyncio.run(_run_cli(args))
    except GraphReplayError as exc:
        print(f"graph replay failed: {exc}", file=sys.stderr)
        return 1
    if receipt.artifact_path is not None:
        print(receipt.artifact_path)
    print(f"graph replay receipt: {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
