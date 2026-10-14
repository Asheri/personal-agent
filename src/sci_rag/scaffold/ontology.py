"""Drafting a starting ontology with the configured model.

The ontology is the one part of a domain profile that is genuinely hard to
write cold, so the wizard offers to draft it. Model output is untrusted: the
response is parsed into the same :class:`~sci_rag.domain.DomainConfig` that
``load_domain()`` reads, so a malformed draft raises here rather than being
written as YAML that only fails later when the graph extractor runs.

The LLM client is imported inside the function. ``sci-rag-new`` must start
without touching the generation stack.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from sci_rag.domain import DomainConfig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sci_rag.llm import LLMClient

PROMPT_NAME = "ontology_draft"


class OntologyDraftError(RuntimeError):
    """The model's ontology draft could not be trusted."""


def render_prompt(domain_dir: Path, *, project_name: str, description: str) -> str:
    from string import Template

    path = domain_dir / "prompts" / f"{PROMPT_NAME}.md"
    if not path.exists():
        raise OntologyDraftError(
            f"No ontology drafting prompt at {path}. It ships in the template's "
            "domain/prompts/ directory."
        )
    return Template(path.read_text(encoding="utf-8")).substitute(
        PROJECT_NAME=project_name, DESCRIPTION=description
    )


async def draft_ontology(
    domain_dir: Path,
    *,
    project_name: str,
    description: str,
    llm: LLMClient | None = None,
    settings: Any = None,
) -> DomainConfig:
    """Ask the model for an ontology and return it only if it validates."""
    from sci_rag.llm import parse_json_loosely

    if llm is None:
        from sci_rag.config import get_settings
        from sci_rag.llm import get_llm

        llm = get_llm(settings or get_settings())

    prompt = render_prompt(domain_dir, project_name=project_name, description=description)
    raw = await llm.generate(prompt, temperature=0.2, max_tokens=4096, json_mode=True)

    try:
        payload = parse_json_loosely(raw)
    except ValueError as exc:
        raise OntologyDraftError(f"The model did not return JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise OntologyDraftError(
            f"Expected a JSON object with entity_types, got {type(payload).__name__}."
        )

    try:
        config = DomainConfig.model_validate(
            {
                "name": project_name,
                "description": description,
                "entity_types": payload.get("entity_types", []),
                "relation_types": payload.get("relation_types", []),
                "query_classes": payload.get("query_classes", []),
            }
        )
    except ValidationError as exc:
        raise OntologyDraftError(f"The drafted ontology did not validate: {exc}") from exc

    if not config.entity_types:
        raise OntologyDraftError(
            "The draft contained no entity type. Redraft, or choose a blank ontology "
            "and write it yourself."
        )
    return config


def summarize(config: DomainConfig) -> list[tuple[str, str]]:
    """Label and value rows for showing a draft back to the user."""
    return [
        ("Entity types", ", ".join(e.name for e in config.entity_types)),
        ("Relation types", ", ".join(r.name for r in config.relation_types)),
        ("Query classes", ", ".join(q.name for q in config.query_classes)),
    ]
