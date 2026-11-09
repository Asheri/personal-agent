"""Shared types for the retrieval subsystem.

The design rule that matters most here: **scope precedes ranking**. A scope
(license allowlist, source allowlist, excluded documents) is applied inside
every layer's SQL, before ordering and limiting. Filtering after ranking
would let an out-of-scope row crowd an eligible one out of a bounded
candidate pool, and excluded content could silently shape results. And an
explicitly empty license scope means "return nothing", never "return
everything".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy import ColumnElement, and_, any_, func, or_, select

from sci_rag.db.models import Chunk, Document, KgEntity, KgRelationship

Kind = Literal["chunk", "community"]
Key = tuple[Kind, str]

STAGES = ("vector", "keyword", "graph", "community", "hyde")


@dataclass(frozen=True)
class RetrievalScope:
    """What a caller is allowed to see.

    Two families of dimension live here. The rights dimensions
    (``license_classes``, ``sources``) are allowlists where ``None`` means
    unrestricted and an EMPTY tuple means deny everything: that asymmetry
    is deliberate, because "the caller restricted this to nothing" must
    never read as "show them everything". The metadata dimensions (year
    range, authors, journals, DOI excludes) are ordinary filters where an
    empty tuple simply means nobody asked.
    """

    license_classes: tuple[str, ...] | None = None
    sources: tuple[str, ...] | None = None
    exclude_document_ids: tuple[str, ...] = ()

    # Metadata filters. Scientific corpora are filtered by when, by whom,
    # and where published at least as often as by rights.
    year_min: int | None = None
    year_max: int | None = None
    authors: tuple[str, ...] = ()
    journals: tuple[str, ...] = ()
    exclude_dois: tuple[str, ...] = ()
    date_min: date | None = None
    date_max: date | None = None
    projects: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    auto_tags: tuple[str, ...] = ()
    entity_names: tuple[str, ...] = ()

    # Retraction awareness. Default OFF here so raw retrieval and every
    # existing ablation keep measuring what they measured before; the
    # ANSWER path turns it on, because citing a retracted paper as live
    # evidence is the failure that actually matters.
    exclude_retracted: bool = False
    # A baseline exemption, independently of rights and metadata restrictions.
    include_superseded: bool = False

    def denies_all(self) -> bool:
        return self.license_classes is not None and len(self.license_classes) == 0

    def is_unrestricted(self) -> bool:
        """True when no rights or metadata restriction is present.

        The community layer gates on this: a stored summary aggregates
        evidence across documents before any scope is known, so ANY
        restriction has to disable it. Current-version filtering remains a
        separate baseline. The field coverage test in
        tests/unit/test_retrieval_scope.py makes that distinction explicit.
        """
        return (
            self.license_classes is None
            and self.sources is None
            and not self.exclude_document_ids
            and self.year_min is None
            and self.year_max is None
            and not self.authors
            and not self.journals
            and not self.exclude_dois
            and not self.exclude_retracted
            and self.date_min is None
            and self.date_max is None
            and not self.projects
            and not self.tags
            and not self.auto_tags
            and not self.entity_names
        )


def scope_conditions(scope: RetrievalScope) -> list[ColumnElement[bool]]:
    """SQL conditions implementing a scope, for queries joined to documents."""
    conditions: list[ColumnElement[bool]] = []
    if not scope.include_superseded:
        conditions.append(Document.is_current.is_(True))
    if scope.license_classes is not None:
        conditions.append(Document.license_class.in_(scope.license_classes))
    if scope.sources is not None:
        conditions.append(Document.source.in_(scope.sources))
    if scope.exclude_document_ids:
        conditions.append(Document.id.not_in(scope.exclude_document_ids))
    if scope.year_min is not None:
        conditions.append(Document.publication_year >= scope.year_min)
    if scope.year_max is not None:
        conditions.append(Document.publication_year <= scope.year_max)
    if scope.authors:
        # authors is a Postgres ARRAY: overlap is "shares at least one".
        conditions.append(Document.authors.overlap(list(scope.authors)))
    if scope.journals:
        conditions.append(Document.journal.in_(scope.journals))
    if scope.exclude_dois:
        # A NULL doi is not excluded by a DOI blocklist; not_in() alone
        # would drop those rows, since NULL NOT IN (...) is NULL.
        conditions.append(or_(Document.doi.is_(None), Document.doi.not_in(scope.exclude_dois)))
    if scope.exclude_retracted:
        conditions.append(_not_retracted())
    if scope.date_min is not None:
        conditions.append(or_(Document.doc_date.is_(None), Document.doc_date >= scope.date_min))
    if scope.date_max is not None:
        conditions.append(or_(Document.doc_date.is_(None), Document.doc_date <= scope.date_max))
    if scope.projects:
        conditions.append(Document.project_id.in_(scope.projects))
    if scope.tags:
        conditions.append(Document.tags.overlap(list(scope.tags)))
    if scope.auto_tags:
        conditions.append(Document.auto_tags.overlap(list(scope.auto_tags)))
    if scope.entity_names:
        conditions.append(
            select(Chunk.id)
            .join(KgEntity, Chunk.id == any_(KgEntity.chunk_ids))
            .where(Chunk.document_id == Document.id, KgEntity.name.in_(scope.entity_names))
            .correlate(Document)
            .exists()
        )
    return conditions


def _not_retracted() -> ColumnElement[bool]:
    """Documents Crossref has not flagged as retracted.

    Retraction status lands in ``Document.extra`` during enrichment, so a
    document nobody enriched has no flag at all and is not excluded: this
    filter removes what is KNOWN to be retracted, and the doctor check is
    what surfaces an unenriched corpus.
    """
    flag = Document.extra["crossref"]["is_retracted"]
    return or_(flag.is_(None), flag.as_boolean().is_(False))


def entity_scope_condition(scope: RetrievalScope) -> ColumnElement[bool]:
    """Aggregate descriptions require all attributed documents to be eligible."""
    eligible = select(func.array_agg(Document.id)).where(*scope_conditions(scope)).scalar_subquery()
    return and_(
        func.cardinality(KgEntity.document_ids) > 0, KgEntity.document_ids.contained_by(eligible)
    )


def relationship_scope_condition(scope: RetrievalScope) -> ColumnElement[bool]:
    documents = select(Document.id).where(*scope_conditions(scope))
    chunks = select(Chunk.id).join(Document).where(*scope_conditions(scope))
    return or_(
        KgRelationship.document_id.in_(documents),
        and_(KgRelationship.document_id.is_(None), KgRelationship.chunk_id.in_(chunks)),
    )


@dataclass
class StageTrace:
    """Operational metadata about one retrieval stage. Content-free by design:
    no query text, no chunk text, so traces are always safe to log."""

    stage: str
    status: str  # "success" | "empty" | "timeout" | "error" | "skipped" | "disabled"
    duration_ms: int = 0
    candidate_count: int = 0


@dataclass
class RetrievedItem:
    kind: Kind
    id: str
    score: float
    layers: list[str]
    title: str
    content: str
    document_id: str | None = None
    section_path: str | None = None
    citation: str | None = None
    license_class: str = "unknown"
    source: str = ""
    is_table: bool = False


@dataclass
class RetrievalResult:
    items: list[RetrievedItem]
    traces: list[StageTrace]
    profile: str

    def trace_for(self, stage: str) -> StageTrace | None:
        return next((t for t in self.traces if t.stage == stage), None)

    @property
    def degraded_stages(self) -> list[str]:
        return [t.stage for t in self.traces if t.status in ("timeout", "error")]


@dataclass
class FusedCandidate:
    key: Key
    score: float
    layers: list[str] = field(default_factory=list)
