"""Abstract screening with strict model parsing and human-review fallback.

Model decisions are suggestions until they pass a complete response contract
and the configured confidence floor. Any uncertainty becomes an explicit
review row. It can never become an exclusion by accident.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from sci_rag.campaigns.discovery import CandidateWork, normalize_doi
from sci_rag.campaigns.prisma import PrismaCounts, build_prisma_counts
from sci_rag.campaigns.state import CampaignRecord, CampaignState
from sci_rag.domain import DomainProfile
from sci_rag.llm import LLMClient

log = structlog.get_logger(__name__)

ScreeningOutcome = Literal["include", "exclude", "review"]
FinalOutcome = Literal["include", "exclude"]
DecisionSource = Literal["model", "human", "system"]
_SCREEN_STATUSES = frozenset({"screen_included", "screen_excluded", "screen_review"})


class _ModelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(strict=True, ge=1)
    decision: FinalOutcome
    confidence: float = Field(strict=True, ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_must_have_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("reason must not be blank")
        return normalized


class _ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[_ModelDecision]


@dataclass(frozen=True)
class ScreeningDecision:
    doi: str
    title: str
    decision: ScreeningOutcome
    confidence: float | None
    reason: str
    source: DecisionSource
    model_decision: FinalOutcome | None = None
    failure: bool = False
    criteria_sha256: str = ""
    confidence_threshold: float = 0.8


@dataclass
class ScreeningReport:
    criteria: str
    criteria_sha256: str
    confidence_threshold: float
    decisions: list[ScreeningDecision]
    prisma: PrismaCounts
    malformed_responses: int = 0
    missing_abstracts: int = 0
    duplicates_removed: int = 0
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def review_queue(self) -> list[ScreeningDecision]:
        return [decision for decision in self.decisions if decision.decision == "review"]


@dataclass(frozen=True)
class ScreeningContext:
    criteria: str
    criteria_sha256: str
    confidence_threshold: float
    duplicates_removed: int
    malformed_responses: int
    missing_abstracts: int


def criteria_digest(criteria: str) -> str:
    normalized = criteria.strip()
    if not normalized:
        raise ValueError("screening criteria must not be empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def screen_campaign(
    works: list[CandidateWork],
    *,
    criteria: str,
    llm: LLMClient,
    domain: DomainProfile,
    state: CampaignState,
    confidence_threshold: float = 0.8,
    batch_size: int = 20,
    report_path: Path | None = None,
    duplicates_removed: int = 0,
) -> ScreeningReport:
    """Screen each unique work, resuming decisions made under the same criteria."""
    criteria = criteria.strip()
    digest = criteria_digest(criteria)
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0 and 1")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    _validate_unique_works(works)

    prior_malformed = 0
    prior_missing = 0
    if report_path is not None and report_path.exists():
        prior = load_screening_context(report_path)
        if prior.criteria_sha256 == digest and prior.confidence_threshold == confidence_threshold:
            prior_malformed = prior.malformed_responses
            prior_missing = prior.missing_abstracts

    current = latest_screening_decisions(
        state,
        criteria_sha256=digest,
        confidence_threshold=confidence_threshold,
    )
    pending_with_abstract: list[CandidateWork] = []
    missing_abstracts = 0
    for work in works:
        if work.doi in current:
            continue
        if not work.abstract or not work.abstract.strip():
            missing_abstracts += 1
            decision = ScreeningDecision(
                doi=work.doi,
                title=work.title or work.doi,
                decision="review",
                confidence=None,
                reason="Abstract unavailable; human review required.",
                source="system",
                criteria_sha256=digest,
                confidence_threshold=confidence_threshold,
            )
            _persist_decision(state, decision)
            current[work.doi] = decision
        else:
            pending_with_abstract.append(work)

    malformed_responses = 0
    for start in range(0, len(pending_with_abstract), batch_size):
        batch = pending_with_abstract[start : start + batch_size]
        try:
            payload = await llm.generate_json(
                _render_prompt(domain, criteria=criteria, works=batch),
                max_tokens=max(1024, len(batch) * 180),
            )
            parsed = _parse_model_response(payload, expected=len(batch))
        except Exception as exc:
            malformed_responses += 1
            log.warning(
                "campaign_screening_response_invalid",
                error=type(exc).__name__,
                batch_size=len(batch),
            )
            for work in batch:
                decision = ScreeningDecision(
                    doi=work.doi,
                    title=work.title or work.doi,
                    decision="review",
                    confidence=None,
                    reason="Model response invalid; human review required.",
                    source="system",
                    failure=True,
                    criteria_sha256=digest,
                    confidence_threshold=confidence_threshold,
                )
                _persist_decision(state, decision)
                current[work.doi] = decision
            continue

        for work, model_decision in zip(batch, parsed, strict=True):
            outcome: ScreeningOutcome = model_decision.decision
            if model_decision.confidence < confidence_threshold:
                outcome = "review"
            decision = ScreeningDecision(
                doi=work.doi,
                title=work.title or work.doi,
                decision=outcome,
                confidence=model_decision.confidence,
                reason=model_decision.reason,
                source="model",
                model_decision=model_decision.decision,
                criteria_sha256=digest,
                confidence_threshold=confidence_threshold,
            )
            _persist_decision(state, decision)
            current[work.doi] = decision

    report = screening_report_from_state(
        works,
        criteria=criteria,
        state=state,
        confidence_threshold=confidence_threshold,
        duplicates_removed=duplicates_removed,
        malformed_responses=prior_malformed + malformed_responses,
        missing_abstracts=prior_missing + missing_abstracts,
    )
    if report_path is not None:
        write_screening_report(report, report_path)
    return report


def screening_report_from_state(
    works: list[CandidateWork],
    *,
    criteria: str,
    state: CampaignState,
    confidence_threshold: float,
    duplicates_removed: int = 0,
    malformed_responses: int = 0,
    missing_abstracts: int = 0,
) -> ScreeningReport:
    """Rebuild the current report after model or human decisions are appended."""
    digest = criteria_digest(criteria)
    current = latest_screening_decisions(
        state,
        criteria_sha256=digest,
        confidence_threshold=confidence_threshold,
    )
    missing_dois = [work.doi for work in works if work.doi not in current]
    if missing_dois:
        raise ValueError(
            "screening state does not cover every discovered work: " + ", ".join(missing_dois)
        )
    decisions = [current[work.doi] for work in works]
    prisma = build_prisma_counts(
        decisions,
        discovered_total=len(works),
        duplicates_removed=duplicates_removed,
    )
    return ScreeningReport(
        criteria=criteria.strip(),
        criteria_sha256=digest,
        confidence_threshold=confidence_threshold,
        decisions=decisions,
        prisma=prisma,
        malformed_responses=malformed_responses,
        missing_abstracts=missing_abstracts,
        duplicates_removed=duplicates_removed,
    )


def latest_screening_decisions(
    state: CampaignState,
    *,
    criteria_sha256: str,
    confidence_threshold: float,
) -> dict[str, ScreeningDecision]:
    """Return the latest screening disposition per DOI for one protocol."""
    decisions: dict[str, ScreeningDecision] = {}
    for record in state.records:
        if record.status not in _SCREEN_STATUSES:
            continue
        if record.payload.get("criteria_sha256") != criteria_sha256:
            continue
        if record.payload.get("confidence_threshold") != confidence_threshold:
            continue
        decisions[record.doi] = _decision_from_record(record)
    return decisions


def apply_human_review(
    state: CampaignState,
    *,
    doi: str,
    criteria_sha256: str,
    confidence_threshold: float,
    decision: FinalOutcome,
    reason: str,
) -> ScreeningDecision:
    """Append a human disposition for a work currently awaiting review."""
    normalized_doi = normalize_doi(doi)
    if normalized_doi is None:
        raise ValueError(f"invalid DOI for screening review: {doi!r}")
    if decision not in {"include", "exclude"}:
        raise ValueError("human screening decision must be include or exclude")
    reason = " ".join(reason.split())
    if not reason:
        raise ValueError("human screening reason must not be empty")
    current = latest_screening_decisions(
        state,
        criteria_sha256=criteria_sha256,
        confidence_threshold=confidence_threshold,
    ).get(normalized_doi)
    if current is None or current.decision != "review":
        raise ValueError(f"{normalized_doi} is not awaiting review for these criteria")
    reviewed = ScreeningDecision(
        doi=normalized_doi,
        title=current.title,
        decision=decision,
        confidence=None,
        reason=reason,
        source="human",
        model_decision=current.model_decision,
        criteria_sha256=criteria_sha256,
        confidence_threshold=confidence_threshold,
    )
    _persist_decision(state, reviewed)
    return reviewed


def write_screening_report(report: ScreeningReport, path: Path) -> None:
    """Atomically write a reproducible JSON report alongside campaign state."""
    payload = {
        "schema_version": 1,
        "generated_at": report.generated_at,
        "criteria": report.criteria,
        "criteria_sha256": report.criteria_sha256,
        "confidence_threshold": report.confidence_threshold,
        "malformed_responses": report.malformed_responses,
        "missing_abstracts": report.missing_abstracts,
        "duplicates_removed": report.duplicates_removed,
        "prisma": asdict(report.prisma),
        "decisions": [asdict(decision) for decision in report.decisions],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_screening_context(path: Path) -> ScreeningContext:
    """Read and validate the protocol fields needed to resume human review."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read screening report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("screening report must be a JSON object")
    criteria = payload.get("criteria")
    digest = payload.get("criteria_sha256")
    threshold = payload.get("confidence_threshold")
    duplicates = payload.get("duplicates_removed", 0)
    malformed = payload.get("malformed_responses", 0)
    missing_abstracts = payload.get("missing_abstracts", 0)
    if not isinstance(criteria, str) or criteria_digest(criteria) != digest:
        raise ValueError("screening report criteria digest is invalid")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not 0.0 <= float(threshold) <= 1.0
    ):
        raise ValueError("screening report confidence threshold is invalid")
    if isinstance(duplicates, bool) or not isinstance(duplicates, int) or duplicates < 0:
        raise ValueError("screening report duplicate count is invalid")
    for name, value in (
        ("malformed response", malformed),
        ("missing abstract", missing_abstracts),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"screening report {name} count is invalid")
    return ScreeningContext(
        criteria=criteria,
        criteria_sha256=str(digest),
        confidence_threshold=float(threshold),
        duplicates_removed=duplicates,
        malformed_responses=malformed,
        missing_abstracts=missing_abstracts,
    )


def _render_prompt(domain: DomainProfile, *, criteria: str, works: list[CandidateWork]) -> str:
    rows = [
        {
            "index": index,
            "doi": work.doi,
            "title": work.title,
            "abstract": work.abstract,
        }
        for index, work in enumerate(works, start=1)
    ]
    return domain.render_prompt(
        "screening",
        CRITERIA=criteria,
        WORKS_JSON=json.dumps(rows, indent=2, ensure_ascii=False),
    )


def _parse_model_response(payload: Any, *, expected: int) -> list[_ModelDecision]:
    parsed = _ModelResponse.model_validate(payload)
    indexes = [decision.index for decision in parsed.decisions]
    if len(indexes) != expected or sorted(indexes) != list(range(1, expected + 1)):
        raise ValueError("model response must contain each requested index exactly once")
    return sorted(parsed.decisions, key=lambda decision: decision.index)


def _persist_decision(state: CampaignState, decision: ScreeningDecision) -> None:
    status = {
        "include": "screen_included",
        "exclude": "screen_excluded",
        "review": "screen_review",
    }[decision.decision]
    state.append(doi=decision.doi, status=status, payload=asdict(decision))


def _decision_from_record(record: CampaignRecord) -> ScreeningDecision:
    payload = record.payload
    decision = payload.get("decision")
    source = payload.get("source")
    model_decision = payload.get("model_decision")
    confidence = payload.get("confidence")
    if decision not in {"include", "exclude", "review"}:
        raise ValueError(f"campaign screening decision is invalid for {record.doi}")
    if source not in {"model", "human", "system"}:
        raise ValueError(f"campaign screening source is invalid for {record.doi}")
    if model_decision not in {None, "include", "exclude"}:
        raise ValueError(f"campaign model decision is invalid for {record.doi}")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        raise ValueError(f"campaign screening confidence is invalid for {record.doi}")
    title = payload.get("title")
    reason = payload.get("reason")
    digest = payload.get("criteria_sha256")
    failure = payload.get("failure", False)
    threshold = payload.get("confidence_threshold")
    if not isinstance(title, str) or not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"campaign screening reason is invalid for {record.doi}")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"campaign screening criteria digest is invalid for {record.doi}")
    if not isinstance(failure, bool):
        raise ValueError(f"campaign screening failure flag is invalid for {record.doi}")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not 0.0 <= float(threshold) <= 1.0
    ):
        raise ValueError(f"campaign screening threshold is invalid for {record.doi}")
    return ScreeningDecision(
        doi=record.doi,
        title=title,
        decision=decision,
        confidence=float(confidence) if confidence is not None else None,
        reason=" ".join(reason.split()),
        source=source,
        model_decision=model_decision,
        failure=failure,
        criteria_sha256=digest,
        confidence_threshold=float(threshold),
    )


def _validate_unique_works(works: list[CandidateWork]) -> None:
    dois = [work.doi for work in works]
    if len(dois) != len(set(dois)):
        raise ValueError("campaign screening input contains duplicate DOIs")
