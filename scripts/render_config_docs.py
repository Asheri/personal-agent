"""Render docs/configuration.md from the runtime and domain models.

The renderer also checks that ``.env.example`` names every ``Settings`` field
and contains no unknown ``SCI_RAG_*`` variable. ``--check`` fails when the
committed page is stale.
"""

from __future__ import annotations

import argparse
import json
import re
import types
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import PydanticUndefined

from sci_rag.config import Settings
from sci_rag.domain import DomainConfig, load_domain
from sci_rag.evals.seeds import SeedQuestion
from sci_rag.ingest.manifest import CorpusEntry

ENV_PREFIX = str(Settings.model_config.get("env_prefix", ""))
ENV_PATTERN = re.compile(r"^#?\s*(SCI_RAG_[A-Z0-9_]+)\s*=")

SETTING_DESCRIPTIONS = {
    "database_url": "Async SQLAlchemy URL for Postgres with pgvector.",
    "google_api_key": "Alternative Google AI Studio key. Also set SCI_RAG_LLM_PROVIDER=google to switch generation.",
    "gcp_project": "Google Cloud project used for Vertex AI credentials.",
    "gcp_location": "Vertex AI region.",
    "embedding_provider": "Embedding route: modelscope (default), google, or local-hash; local-hash is deterministic and offline.",
    "embedding_model": "Provider model identifier stamped into stored embedding versions.",
    "modelscope_device": "ModelScope/SentenceTransformer device: auto, cpu, cuda, or cuda:N; auto delegates device detection.",
    "modelscope_cache_dir": "Optional ModelScope snapshot cache directory; unset uses the ModelScope default.",
    "embedding_dim": "Fixed vector width; fresh installs use 1024. Changing it on a populated schema requires migration and re-embedding.",
    "llm_provider": "Backend a bare model id belongs to. Any model setting may override it inline as `provider:model`.",
    "llm_model": "Generation model for answers, HyDE, communities, reranking, and judging.",
    "extraction_model": "Optional high-volume extraction model; unset inherits the generation model.",
    "judge_model": "Optional evaluation judge model; unset inherits the generation model. Naming a different provider avoids self-graded answers.",
    "anthropic_api_key": "Key for the direct Anthropic API. Unset uses Vertex AI, which needs only a GCP project.",
    "openai_api_key": "Key for the OpenAI-compatible provider. Unset uses Vertex AI credentials against Model Garden.",
    "openai_base_url": "Endpoint for the OpenAI-compatible provider. Unset derives the Vertex Model Garden URL from the project and location.",
    "deepseek_api_key": "Default generation credential for the direct DeepSeek API.",
    "deepseek_base_url": "Endpoint for the direct DeepSeek API.",
    "interactive_stage_timeout_s": "Per-stage timeout for the low-latency interactive profile.",
    "deep_stage_timeout_s": "Per-stage timeout for deep and agent-oriented retrieval.",
    "provider_call_timeout_s": "Extra budget for a stage that calls an embedding or generation provider before its database work: vector, community, graph, and HyDE.",
    "domain_dir": "Path to the validated domain profile and prompts.",
    "data_dir": "Base path for corpus data and snapshots.",
    "server_host": "Host interface for the FastAPI server.",
    "server_port": "Port for REST, OpenAPI, and streamable HTTP MCP.",
    "api_keys": "JSON map of bearer key to scopes, rate limit, and optional model-key binding. Unset is open localhost mode.",
    "cors_origins": "Comma-separated origins accepted by the server CORS middleware.",
}

DOMAIN_DESCRIPTIONS = {
    "name": "Human-readable name for the scientific knowledge base.",
    "description": "Short statement of the corpus domain and intended questions.",
    "entity_types": "Ontology concepts the graph extractor may emit.",
    "entity_types[].name": "Canonical entity-type identifier used in prompts and validation.",
    "entity_types[].description": "Domain explanation sent to the extraction model.",
    "relation_types": "Directed relationship types the graph extractor may emit.",
    "relation_types[].name": "Canonical relation identifier.",
    "relation_types[].description": "Meaning of source RELATION target for the model.",
    "query_classes": "Keyword-routed question families used to shape HyDE passages.",
    "query_classes[].name": "Query-class identifier.",
    "query_classes[].keywords": "Lowercase terms matched against tokenized questions.",
    "query_classes[].hyde_instruction": "Domain-specific style for the hypothetical evidence passage.",
    "retrieval": "Fusion, candidate, graph-confidence, and optional reranker tuning.",
    "retrieval.weights": "Per-layer multipliers used by weighted reciprocal rank fusion.",
    "retrieval.rrf_k": "RRF smoothing constant.",
    "retrieval.candidate_limits": "Maximum candidates requested from each layer before fusion.",
    "retrieval.graph": "Relationship-confidence controls for graph traversal; off by default.",
    "retrieval.graph.min_confidence": "Minimum relationship confidence allowed to extend a graph walk.",
    "retrieval.graph.confidence_weighted": "Order graph candidates by minimum path confidence before hop distance.",
    "retrieval.graph.include_citations": "Expand graph candidates by one resolved document-citation hop.",
    "retrieval.reranker": "Post-fusion second-look configuration; off by default.",
    "retrieval.reranker.enabled": "Whether the configured adapter reranks the fused pool.",
    "retrieval.reranker.adapter": "Reranker implementation: LLM or local cross-encoder.",
    "retrieval.reranker.pool": "Number of fused candidates presented to the reranker.",
    "retrieval.reranker.timeout_s": "Maximum reranker duration before fused-order fallback.",
    "retrieval.reranker.model": "Optional model override for the local cross-encoder.",
    "compression.enabled": (
        "Shipped domain-profile default; change only after paired judged-answer evidence."
    ),
}


def _cell(value: Any) -> str:
    text = " ".join(str(value).split()).replace("|", "\\|")
    return text or "-"


def _type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return " | ".join(repr(value) for value in args)
    if origin in (types.UnionType, Union):
        return " | ".join(_type_name(value) for value in args)
    if origin is not None:
        origin_name = getattr(origin, "__name__", str(origin).replace("typing.", ""))
        return f"{origin_name}[{', '.join(_type_name(value) for value in args)}]"
    return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))


def _default(field: Any) -> str:
    if field.default is not PydanticUndefined:
        value = field.default
    elif field.default_factory is not None:
        value = field.default_factory()
    else:
        return "required"
    if value is None:
        return "unset"
    if value == "":
        return '""'
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return "see nested fields"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return str(value)


MANIFEST_DESCRIPTIONS = {
    "path": "Where the file is, relative to the manifest. The only required field.",
    "title": "The document title, used in citations. Drafted from the first pages when missing.",
    "authors": "Author names, as a list.",
    "year": "Publication year.",
    "doi": "Digital object identifier. Enables Crossref enrichment and retraction checks.",
    "journal": "Journal or venue. Becomes a retrieval filter.",
    "url": "Where the document came from, for the citation.",
    "license_class": "Redistribution rights: `public`, `open_commercial`, `open_noncommercial`, `restricted`, or `unknown`. Never drafted; `unknown` is excluded from any request that restricts rights.",
    "license_source": "The sentence or signal the license class was based on, kept as evidence.",
    "source": "Your own grouping label, such as `journal_papers` or `agency_reports`. Becomes a retrieval filter.",
}

SEED_DESCRIPTIONS = {
    "id": "A short stable identifier, used in reports.",
    "question": "The question as a user would ask it.",
    "reference_answer": "What a correct answer must say. Used by the correctness grader; optional for retrieval scoring.",
    "reference_titles": "Titles of the documents that contain the answer. A retrieved chunk from one of them counts as relevant.",
    "evidence_phrases": "Distinctive strings from the answering passages; numbers with units work best. A retrieved chunk containing one counts as relevant.",
    "tags": "Your own labels, plus two with meaning: `unanswerable` marks a question the corpus cannot answer, and `drafted` marks a model-written question no expert has reviewed.",
}


def _model_rows(model: type[BaseModel], descriptions: dict[str, str]) -> list[str]:
    """One table row per field of a flat JSONL row model."""
    missing = [name for name in model.model_fields if name not in descriptions]
    if missing:
        raise SystemExit(f"{model.__name__} has undocumented fields: {', '.join(missing)}")
    rows = []
    for name, field in model.model_fields.items():
        required = field.is_required()
        default = "required" if required else _default(field)
        rows.append(
            f"| `{name}` | {_cell(_type_name(field.annotation))} | {_cell(default)} "
            f"| {_cell(descriptions[name])} |"
        )
    return rows


def _nested_model(annotation: Any) -> tuple[type[BaseModel] | None, bool]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    if origin is list and args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
        return args[0], True
    return None, False


def _domain_rows(
    model: type[BaseModel] = DomainConfig,
    prefix: str = "",
    default_overrides: dict[str, str] | None = None,
) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for name, field in model.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        rows.append(
            (
                path,
                _type_name(field.annotation),
                (default_overrides or {}).get(path, _default(field)),
                DOMAIN_DESCRIPTIONS.get(path, field.description or "Validated domain setting."),
            )
        )
        nested, repeated = _nested_model(field.annotation)
        if nested is not None:
            rows.extend(
                _domain_rows(
                    nested,
                    f"{path}[]" if repeated else path,
                    default_overrides=default_overrides,
                )
            )
    return rows


def _env_names(path: Path) -> set[str]:
    names = {
        match.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := ENV_PATTERN.match(line))
    }
    expected = {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}
    missing = sorted(expected - names)
    unknown = sorted(names - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing from .env.example: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown in .env.example: {', '.join(unknown)}")
        raise ValueError("; ".join(details))
    return names


def render_config_docs(
    env_example: Path = Path(".env.example"),
    domain_dir: Path = Path("domain"),
) -> str:
    env_names = _env_names(env_example)
    shipped_compression = load_domain(domain_dir).config.compression
    domain_default_overrides = {
        "compression.enabled": str(shipped_compression.enabled).lower(),
    }
    lines = [
        "---",
        "title: Configuration",
        "description: Runtime environment variables and domain profile fields, generated from the current Pydantic models.",
        "---",
        "",
        "# Configuration",
        "",
        "<!-- Generated by scripts/render_config_docs.py; do not edit by hand. -->",
        "",
        f"Runtime settings use `{ENV_PREFIX}` environment variables.",
        "Domain concepts and retrieval settings live in `domain/domain.yaml`.",
        "",
        "## Runtime environment variables",
        "",
        "Pydantic settings resolve explicit constructor values first, then",
        "environment variables, then the local `.env` file, then the defaults",
        "below. `.env.example` names every field and is checked by this",
        "renderer, including commented optional values.",
        "",
        "| Environment variable | Type | Default | Purpose |",
        "|---|---|---|---|",
    ]
    for name, field in Settings.model_fields.items():
        env_name = f"{ENV_PREFIX}{name.upper()}"
        assert env_name in env_names
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{env_name}`",
                    _cell(_type_name(field.annotation)),
                    _cell(_default(field)),
                    _cell(SETTING_DESCRIPTIONS.get(name, field.description or "Runtime setting.")),
                )
            )
            + " |"
        )

    lines += [
        "",
        '!!! warning "Keep credentials out of Git"',
        "    Copy `.env.example` to `.env`; the latter is ignored. Never put",
        "    API keys, bearer-key maps, database passwords, or request-supplied",
        "    LLM provider credentials into documentation, logs, issues, or commits.",
        "",
        "The default provider pair installs with",
        "`uv sync --extra modelscope-embedding --extra openai`. The shipped",
        "`deepseek` generator reads `SCI_RAG_DEEPSEEK_API_KEY`; its default",
        "endpoint is `https://api.deepseek.com`, and",
        "`SCI_RAG_DEEPSEEK_BASE_URL` overrides it. A Google key is an",
        "alternative credential and does not switch generation by itself: also",
        "set `SCI_RAG_LLM_PROVIDER=google`.",
        "Fresh Google projects use `gemini-embedding-001` with",
        "`SCI_RAG_EMBEDDING_DIM=1024`.",
        "",
        "`SCI_RAG_EXTRACTION_MODEL` inherits `SCI_RAG_LLM_MODEL` when unset.",
        "Changing the embedding model is a versioned data operation; changing",
        "its dimension additionally requires a schema migration.",
        "",
        "For an existing 1536-dimensional database, Settings restricts ModelScope",
        "embeddings to 32 through 1024 and fails fast outside that range. Separately,",
        "migration `0007` requires the current configuration to be between 32 and 1024",
        "for every provider and fails fast outside that range. Old Google 1536 `.env`",
        "must be changed to 1024 before `uv run sci-rag db upgrade`. Upgrade in this",
        "order:",
        "",
        "1. Back up the database.",
        "2. Change `SCI_RAG_EMBEDDING_DIM` from 1536 to 1024 in `.env`.",
        "3. Run `uv run sci-rag db upgrade`.",
        "4. Run `uv run sci-rag embed reindex --dry-run`, review the stale counts,",
        "   then run the same command with `--apply`.",
        "",
        "Finish with `uv run sci-rag doctor` to verify revision `0007`, both vector",
        "columns, and the stored embedding versions.",
        "",
        "## `domain/domain.yaml`",
        "",
        "The types and schema defaults below come from the live validation",
        "models. `compression.enabled` is different by design: it is a",
        "corpus-gated setting, so the table reads its shipped value from",
        "`domain/domain.yaml`. List paths use `[]` to show the shape of",
        "each entry.",
        "",
        "| Field path | Type | Default | Purpose |",
        "|---|---|---|---|",
    ]
    for path, annotation, default, description in _domain_rows(
        default_overrides=domain_default_overrides
    ):
        lines.append(
            f"| `{path}` | {_cell(annotation)} | {_cell(default)} | {_cell(description)} |"
        )

    lines += [
        "",
        "## `data/corpus.jsonl`",
        "",
        "The corpus manifest: one JSON object per document. `sci-rag ingest",
        "--manifest` and `sci-rag build --manifest` read it; `sci-rag draft",
        "manifest` writes a first version from the files in a folder; `sci-rag",
        "manifest lint` checks it. Paths resolve relative to the manifest file.",
        "",
        "| Field | Type | Default | Purpose |",
        "|---|---|---|---|",
        *_model_rows(CorpusEntry, MANIFEST_DESCRIPTIONS),
        "",
        "## `domain/eval_seed_questions.jsonl`",
        "",
        "The test questions: one JSON object per question, with the evidence a",
        "correct answer rests on. `sci-rag eval retrieval` and `sci-rag eval",
        "answers` score against them; `sci-rag draft questions` writes a first",
        "version from your corpus. Lines starting with `#` are comments.",
        "",
        "| Field | Type | Default | Purpose |",
        "|---|---|---|---|",
        *_model_rows(SeedQuestion, SEED_DESCRIPTIONS),
        "",
        "## Files beside the YAML profile",
        "",
        "| Path | Contract |",
        "|---|---|",
        "| `domain/prompts/*.md` | `string.Template` prompt files. Preserve every required `$UPPER_CASE` slot. |",
        "| `domain/eval_calibration_labels.jsonl` | Human scores for a set of graded answers, used to check the model grader. Never drafted. |",
        "",
        "[Bring your own domain](bring-your-own-domain.md) explains how to change",
        "these together. [Evaluate your pipeline](evaluation.md) explains why a",
        "tuning value should move only behind measured evidence.",
        "",
    ]
    return "\n".join(lines)


def _write_or_check(output: Path, page: str, *, check: bool) -> int:
    if check:
        if not output.exists() or output.read_text(encoding="utf-8") != page:
            print(f"stale generated reference: {output}; run make docs-reference")
            return 1
        print(f"up to date: {output}")
        return 0
    output.write_text(page, encoding="utf-8")
    print(f"wrote {output}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/configuration.md"))
    parser.add_argument("--env-example", type=Path, default=Path(".env.example"))
    parser.add_argument("--domain-dir", type=Path, default=Path("domain"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    page = render_config_docs(args.env_example, args.domain_dir)
    raise SystemExit(_write_or_check(args.output, page, check=args.check))


if __name__ == "__main__":
    main()
