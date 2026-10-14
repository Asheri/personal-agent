"""Drafting an ontology against the corpus, not against a one-line description.

The wizard already offers a cold draft, made from a sentence before any
document exists. That is the best guess available at project creation, and it
is a guess. Once documents are ingested, ``docs/bring-your-own-domain.md``
tells the user how to notice it was wrong ("near zero entities means the
ontology and the corpus are talking past each other") and then leaves them to
fix it by hand. This module is the assisted fix.

Two things it will not do. It will not touch the ``retrieval:`` and
``compression:`` blocks, which are tuned numbers an ablation earned rather than
domain semantics. And it will not accept a refinement that empties the
ontology: a model asking to remove everything is a bad refinement, not an
instruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from sci_rag.domain import DomainConfig, EntityTypeSpec, QueryClassSpec, RelationTypeSpec
from sci_rag.draft import DraftError, complete, parse_json_object
from sci_rag.draft import render_prompt as _render_template
from sci_rag.draft.sampling import PassageSample, format_passages

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sci_rag.domain import DomainProfile
    from sci_rag.llm import LLMClient

_SpecT = TypeVar("_SpecT", bound=BaseModel)

PROMPT_NAME = "ontology_from_corpus"

#: What the prompt shows when there is nothing to refine. Doubles as the
#: switch the model reads to choose which reply shape to return.
NO_EXISTING_ONTOLOGY = "(none yet: this project has no ontology to refine)"

PROPOSAL_HEADER = """\
# Model-drafted ontology, awaiting your review.
#
# The retrieval: and compression: blocks below were carried over from your
# current domain.yaml untouched. They are tuned numbers an ablation earned,
# not domain semantics, so nothing here proposes changes to them.
#
# The guiding comments from the shipped domain.yaml are not reproduced here.
# Review this file, then move it over domain.yaml, or re-run with --apply.
"""

_KINDS = {
    "entity_type": ("entity_types", EntityTypeSpec),
    "relation_type": ("relation_types", RelationTypeSpec),
    "query_class": ("query_classes", QueryClassSpec),
}


@dataclass
class DraftedOntology:
    """Either a whole ontology or the delta the model would apply to one."""

    entity_types: list[EntityTypeSpec] = field(default_factory=list)
    relation_types: list[RelationTypeSpec] = field(default_factory=list)
    query_classes: list[QueryClassSpec] = field(default_factory=list)
    #: ``(kind, name, reason)``. Empty for a from-scratch draft.
    removals: list[tuple[str, str, str]] = field(default_factory=list)
    #: True when the reply came back in the additions/removals shape.
    is_refinement: bool = False


def _ontology_block(config: DomainConfig) -> str:
    lines = ["Entity types:"]
    lines += [
        f"- {e.name}: {e.description}" if e.description else f"- {e.name}"
        for e in config.entity_types
    ]
    lines += ["", "Relation types:"]
    lines += [
        f"- {r.name}: {r.description}" if r.description else f"- {r.name}"
        for r in config.relation_types
    ]
    lines += ["", "Query classes:"]
    lines += [
        f"- {q.name}: {', '.join(q.keywords)}" if q.keywords else f"- {q.name}"
        for q in config.query_classes
    ]
    return "\n".join(lines)


def render_prompt(
    domain: DomainProfile, *, sample: PassageSample, existing: DomainConfig | None
) -> str:
    """The corpus-grounded prompt, identical in both lanes.

    ``existing`` is the switch: shown an ontology, the model is asked for
    additions and removals with reasons; shown none, it is asked for the whole
    thing. One template covers both so the instructions stay in
    ``domain/prompts/`` where a user can read and edit them.
    """
    return _render_template(
        domain.directory,
        PROMPT_NAME,
        DOMAIN_NAME=domain.name,
        DESCRIPTION=domain.config.description or "(not described)",
        EXISTING_ONTOLOGY=(
            _ontology_block(existing) if existing is not None else NO_EXISTING_ONTOLOGY
        ),
        PASSAGES=format_passages(sample.passages),
    )


def _specs(rows: Any, model: type[_SpecT], label: str) -> list[_SpecT]:
    if rows in (None, []):
        return []
    if not isinstance(rows, list):
        raise DraftError(f"Expected a list of {label}, got {type(rows).__name__}.")
    try:
        return [model.model_validate(row) for row in rows]
    except ValidationError as exc:
        raise DraftError(f"The drafted {label} did not validate: {exc}") from exc


def parse_reply(raw: str) -> DraftedOntology:
    """Validate an untrusted reply, in whichever of the two shapes came back."""
    payload = parse_json_object(raw, expecting="entity_types or additions")

    if "additions" in payload or "removals" in payload:
        additions = payload.get("additions") or {}
        if not isinstance(additions, dict):
            raise DraftError(
                f"Expected an object under 'additions', got {type(additions).__name__}."
            )
        removals: list[tuple[str, str, str]] = []
        for row in payload.get("removals") or []:
            if not isinstance(row, dict):
                raise DraftError("Each removal must be an object with kind, name, and reason.")
            kind = str(row.get("kind") or "")
            name = str(row.get("name") or "")
            reason = str(row.get("reason") or "")
            if kind not in _KINDS or not name:
                raise DraftError(
                    f"A removal named kind {kind!r} and name {name!r}; kind must be one of "
                    f"{', '.join(sorted(_KINDS))}."
                )
            if not reason:
                raise DraftError(f"The removal of {name!r} came with no reason.")
            removals.append((kind, name, reason))
        return DraftedOntology(
            entity_types=_specs(additions.get("entity_types"), EntityTypeSpec, "entity types"),
            relation_types=_specs(
                additions.get("relation_types"), RelationTypeSpec, "relation types"
            ),
            query_classes=_specs(additions.get("query_classes"), QueryClassSpec, "query classes"),
            removals=removals,
            is_refinement=True,
        )

    drafted = DraftedOntology(
        entity_types=_specs(payload.get("entity_types"), EntityTypeSpec, "entity types"),
        relation_types=_specs(payload.get("relation_types"), RelationTypeSpec, "relation types"),
        query_classes=_specs(payload.get("query_classes"), QueryClassSpec, "query classes"),
    )
    if not drafted.entity_types:
        raise DraftError(
            "The draft contained no entity type. Redraft, or keep the ontology you have "
            "and edit it yourself."
        )
    return drafted


def apply_refinement(
    current: DomainConfig, drafted: DraftedOntology, *, replace: bool = False
) -> DomainConfig:
    """Merge a draft into the current profile, keeping the tuned blocks.

    ``replace`` swaps the domain semantics wholesale, which is what
    ``--from-corpus`` asks for. Without it the draft is treated as a delta:
    additions are appended and named removals dropped, so a type nobody
    questioned survives untouched.
    """
    merged = current.model_copy(deep=True)

    if replace:
        merged.entity_types = list(drafted.entity_types)
        merged.relation_types = list(drafted.relation_types)
        merged.query_classes = list(drafted.query_classes)
    else:
        removed: dict[str, set[str]] = {attribute: set() for attribute, _ in _KINDS.values()}
        for kind, name, _ in drafted.removals:
            removed[_KINDS[kind][0]].add(name)
        for attribute, additions in (
            ("entity_types", drafted.entity_types),
            ("relation_types", drafted.relation_types),
            ("query_classes", drafted.query_classes),
        ):
            kept = [
                spec for spec in getattr(merged, attribute) if spec.name not in removed[attribute]
            ]
            known = {spec.name for spec in kept}
            kept += [spec for spec in additions if spec.name not in known]
            setattr(merged, attribute, kept)

    if not merged.entity_types:
        raise DraftError(
            "That refinement would leave no entity type at all. A model asking to remove "
            "everything is a bad refinement, not an instruction; nothing was changed."
        )
    return merged


def summarize_change(before: DomainConfig, after: DomainConfig) -> list[str]:
    """The diff a reviewer reads before deciding to apply anything."""
    lines: list[str] = []
    for attribute, label in (
        ("entity_types", "entity type"),
        ("relation_types", "relation type"),
        ("query_classes", "query class"),
    ):
        old = {spec.name for spec in getattr(before, attribute)}
        new = {spec.name for spec in getattr(after, attribute)}
        lines += [f"  + {label}: {name}" for name in sorted(new - old)]
        lines += [f"  - {label}: {name}" for name in sorted(old - new)]
    if not lines:
        lines.append("  (no change to the ontology)")
    return lines


def render_yaml(config: DomainConfig) -> str:
    """The domain profile a drafting run proposes, header and all."""
    body = yaml.safe_dump(config.model_dump(), sort_keys=False, allow_unicode=True, width=88)
    return f"{PROPOSAL_HEADER}\n{body}"


async def draft_from_corpus(
    domain: DomainProfile,
    *,
    sample: PassageSample,
    existing: DomainConfig | None,
    llm: LLMClient | None = None,
    settings: Any = None,
    raw_reply: str | None = None,
) -> DraftedOntology:
    """Ask what these documents are actually about, and validate the answer."""
    if raw_reply is not None:
        return parse_reply(raw_reply)
    prompt = render_prompt(domain, sample=sample, existing=existing)
    return parse_reply(await complete(prompt, llm=llm, settings=settings))


__all__ = [
    "NO_EXISTING_ONTOLOGY",
    "PROMPT_NAME",
    "PROPOSAL_HEADER",
    "DraftedOntology",
    "apply_refinement",
    "draft_from_corpus",
    "parse_reply",
    "render_prompt",
    "render_yaml",
    "summarize_change",
]
