"""The domain profile: everything that makes YOUR corpus yours.

The kit's code is domain-agnostic. All the domain semantics live in one
directory (``domain/`` by default) that you edit to point the kit at a field:

* ``domain.yaml``: the ontology (entity and relationship types the graph
  extractor looks for), HyDE query classes, and retrieval tuning.
* ``prompts/*.md``: the prompt templates, with ``$UPPER_CASE`` slots.
* ``eval_seed_questions.jsonl``: ground-truth questions for the evaluator.

Templates use :class:`string.Template` (``$SLOT``) rather than ``str.format``
so JSON examples inside prompts never need brace-escaping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class EntityTypeSpec(BaseModel):
    name: str
    description: str = ""


class RelationTypeSpec(BaseModel):
    name: str
    description: str = ""


class QueryClassSpec(BaseModel):
    name: str
    keywords: list[str] = Field(default_factory=list)
    hyde_instruction: str = ""


class RerankerTuning(BaseModel):
    """The post-fusion rerank stage. Off until an ablation earns it a place.

    ``adapter`` picks the implementation: "llm" (one JSON call through the
    configured LLM, no new dependency) or "local" (a sentence-transformers
    cross-encoder behind the ``rerank`` extra). ``pool`` is how many fused
    candidates get a second look; ``model`` overrides the local adapter's
    cross-encoder checkpoint.
    """

    enabled: bool = False
    adapter: Literal["llm", "local"] = "llm"
    pool: int = 20
    timeout_s: float = 15.0
    model: str | None = None


class GraphTuning(BaseModel):
    """Confidence controls for graph traversal.

    Both controls preserve the historical walk by default. A positive
    ``min_confidence`` filters edges before they spend the hop budget, while
    ``confidence_weighted`` ranks candidates by their strongest minimum-edge
    path before using hop distance as the tie-breaker.
    """

    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_weighted: bool = False
    include_citations: bool = False


class RetrievalTuning(BaseModel):
    """Fusion weights and candidate limits; defaults are battle-tested."""

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "vector": 1.5,
            "keyword": 1.0,
            "graph": 0.8,
            "community": 0.6,
            "hyde": 1.2,
        }
    )
    rrf_k: int = 60
    candidate_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "vector": 20,
            "keyword": 20,
            "graph": 20,
            "community": 5,
            "hyde": 20,
        }
    )
    graph: GraphTuning = Field(default_factory=GraphTuning)
    reranker: RerankerTuning = Field(default_factory=RerankerTuning)


class CompressionTuning(BaseModel):
    """Question-aware source compression before answer prompt assembly.

    This remains off until a paired judged-answer evaluation shows quality
    holding while measured prompt tokens fall on the target corpus.
    """

    enabled: bool = Field(
        default=False,
        description="Domain default; enable only after paired judged-answer evidence.",
    )
    relevance_floor: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Drop a model-scored chunk below this relevance score. The default 0.0 "
            "summarizes every source and drops none. A v0.3 sweep found groundedness "
            "and citation accuracy both fall off their ceiling at 0.15 and above. "
            "Raise it only behind a paired "
            "judged-answer run that holds. See docs/evaluation.md."
        ),
    )
    max_tokens_per_chunk: int = Field(
        default=160,
        ge=16,
        le=2048,
        description=(
            "Maximum accepted tokens per summary; over-budget output falls back to full text."
        ),
    )


class DomainConfig(BaseModel):
    name: str
    description: str = ""
    entity_types: list[EntityTypeSpec] = Field(default_factory=list)
    relation_types: list[RelationTypeSpec] = Field(default_factory=list)
    query_classes: list[QueryClassSpec] = Field(default_factory=list)
    retrieval: RetrievalTuning = Field(default_factory=RetrievalTuning)
    compression: CompressionTuning = Field(
        default_factory=CompressionTuning,
        description="Question-aware chunk compression before answer prompt assembly.",
    )


@dataclass
class DomainProfile:
    config: DomainConfig
    directory: Path

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def entity_type_names(self) -> list[str]:
        return [e.name for e in self.config.entity_types]

    @property
    def relation_type_names(self) -> list[str]:
        return [r.name for r in self.config.relation_types]

    def prompt(self, template_name: str) -> Template:
        path = self.directory / "prompts" / f"{template_name}.md"
        if not path.exists():
            raise FileNotFoundError(
                f"Prompt template {template_name!r} not found at {path}. "
                "Each domain ships its prompts in domain/prompts/."
            )
        return Template(path.read_text(encoding="utf-8"))

    def render_prompt(self, template_name: str, **slots: str) -> str:
        return self.prompt(template_name).substitute(**slots)

    def entity_types_block(self) -> str:
        """The ontology formatted for inclusion in an extraction prompt."""
        return "\n".join(
            f"- {e.name}: {e.description}" if e.description else f"- {e.name}"
            for e in self.config.entity_types
        )

    def relation_types_block(self) -> str:
        return "\n".join(
            f"- {r.name}: {r.description}" if r.description else f"- {r.name}"
            for r in self.config.relation_types
        )

    def classify_query(self, query: str) -> QueryClassSpec | None:
        """Pick the query class whose keywords best match; None if nothing hits."""
        words = set(re.findall(r"[a-z0-9]+", query.lower()))
        best: QueryClassSpec | None = None
        best_hits = 0
        for query_class in self.config.query_classes:
            hits = sum(1 for kw in query_class.keywords if kw.lower() in words)
            if hits > best_hits:
                best, best_hits = query_class, hits
        return best

    def seed_questions_path(self) -> Path:
        return self.directory / "eval_seed_questions.jsonl"


def load_domain(directory: Path) -> DomainProfile:
    config_path = directory / "domain.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"No domain.yaml found in {directory}. The domain directory tells the kit "
            "what to extract and how to talk about your field; see domain/README.md."
        )
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = DomainConfig.model_validate(raw)
    return DomainProfile(config=config, directory=directory)


@lru_cache(maxsize=4)
def load_domain_cached(directory: str) -> DomainProfile:
    return load_domain(Path(directory))
