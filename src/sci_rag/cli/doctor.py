"""`sci-rag doctor`: check the whole setup in one command.

Runs through configuration, domain profile, database, schema, corpus,
graph, and credentials, and prints a table of findings with a fix hint
for anything wrong. Static by default (no model calls); `--probe` adds a
live round-trip through the embedding and generation models.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from sci_rag.domain import DomainConfig
from sci_rag.evals.seeds import SeedQuestion

if TYPE_CHECKING:
    from sci_rag.config import Settings

console = Console()

_PROMPT_FILES = (
    "entity_extraction",
    "query_entities",
    "hyde",
    "answer",
    "community_summary",
    "judge_grounding",
    "judge_correctness",
)
_LATEST_SCHEMA_REVISION = "0007"
_MODELSCOPE_INSTALL_FIX = "uv sync --extra modelscope-embedding"


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail"
    detail: str
    fix: str = ""


#: Below this an ontology is too thin for the graph extractor to find structure:
#: three types is the smallest set that can express a relation between two
#: different things.
_MIN_ENTITY_TYPES = 3

_SCREAMING_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _database_start_hint() -> str:
    """Name the backend the operator selected instead of always prescribing Docker."""
    backend = os.environ.get("SCI_RAG_DB_BACKEND", "docker").strip().lower()
    command = {
        "docker": "docker compose up -d --wait",
        "local": "uv run python scripts/local_postgres.py start",
        "cloud": "uv run python scripts/cloud_postgres.py start",
    }.get(backend)
    if command is None:
        return (
            f"SCI_RAG_DB_BACKEND={backend!r} is invalid; choose docker, local, or cloud, "
            "then run make db-up."
        )
    return f"Run `{command}` for the configured {backend} backend"


def _ontology_coherence_check(config: DomainConfig) -> Check:
    """Whether the ontology can do its job, not merely whether it parses.

    An ontology of one type parses. So does one with the same name twice, where
    the second silently shadows the first everywhere a name is looked up. Both
    show up later as a graph that extracted nothing, which is a much harder
    thing to diagnose than a row in this table.
    """
    duplicates: list[str] = []
    for label, specs in (
        ("entity type", config.entity_types),
        ("relation type", config.relation_types),
        ("query class", config.query_classes),
    ):
        seen: set[str] = set()
        for spec in specs:
            if spec.name in seen:
                duplicates.append(f"{label} {spec.name!r}")
            seen.add(spec.name)
    if duplicates:
        return Check(
            "ontology",
            "fail",
            "duplicate name(s): " + ", ".join(duplicates),
            "Names are looked up by string, so a duplicate silently shadows the first.",
        )

    if len(config.entity_types) < _MIN_ENTITY_TYPES:
        return Check(
            "ontology",
            "warn",
            f"{len(config.entity_types)} entity type(s); fewer than {_MIN_ENTITY_TYPES} "
            "leaves the graph extractor almost nothing to find",
            "uv run sci-rag draft ontology --from-corpus",
        )

    odd = [r.name for r in config.relation_types if not _SCREAMING_SNAKE.match(r.name)]
    if odd:
        return Check(
            "ontology",
            "warn",
            "relation type(s) not in SCREAMING_SNAKE_CASE: " + ", ".join(odd),
            "Relations read as 'source RELATION target'; the convention is what makes "
            "extracted edges legible.",
        )

    return Check(
        "ontology",
        "ok",
        f"{len(config.entity_types)} entity types, {len(config.relation_types)} relation "
        f"types, {len(config.query_classes)} query classes, names unique",
    )


def _seed_coherence_check(questions: list[SeedQuestion]) -> Check:
    """Whether the seed set can measure anything, not merely whether it loads.

    ``load_seed_questions`` already rejects malformed JSON and duplicate ids.
    What it cannot see is a set with nothing to check an answer against, or one
    with no honesty probe, which is an evaluation that cannot tell you whether
    the assistant admits a gap or fills it from model priors.
    """
    if not questions:
        return Check(
            "seed coherence",
            "warn",
            "no seed questions",
            "uv run sci-rag draft questions, or write them by hand.",
        )

    probes = [q for q in questions if not q.answerable]
    bare = [
        q.id for q in questions if q.answerable and not (q.reference_titles or q.evidence_phrases)
    ]
    if bare:
        return Check(
            "seed coherence",
            "warn",
            f"{len(bare)} answerable question(s) cite nothing, so retrieval can never "
            f"score them: {', '.join(sorted(bare)[:5])}",
            "Give each one reference_titles, evidence_phrases, or both.",
        )
    if not probes:
        return Check(
            "seed coherence",
            "warn",
            "no question tagged `unanswerable`",
            "Add one honesty probe: without it, nothing checks whether the assistant "
            "admits a gap instead of inventing an answer.",
        )
    return Check(
        "seed coherence",
        "ok",
        f"{len(questions)} question(s), {len(probes)} honesty probe(s), every answerable "
        "one cites evidence",
    )


def _drafted_ground_truth_check(questions: list[SeedQuestion]) -> Check:
    """How much of the ground truth is still model-drafted and unreviewed."""
    drafted = [q.id for q in questions if q.drafted]
    if not drafted:
        return Check("ground truth", "ok", f"{len(questions)} question(s), none awaiting review")
    return Check(
        "ground truth",
        "warn",
        f"{len(drafted)} of {len(questions)} question(s) are model-drafted and "
        f"unreviewed: {', '.join(sorted(drafted)[:5])}",
        "Check each against the document it cites, then delete its `drafted` tag. "
        "Until then every eval report says its numbers are provisional.",
    )


def _grounding_check(questions: list[SeedQuestion], titles: set[str]) -> Check:
    """Whether the seed set and the ingested corpus are talking about each other.

    Only meaningful once documents exist. A reference title that matches no
    ingested document scores zero forever, and it looks exactly like a
    retrieval failure in the report.
    """
    normalized = {" ".join(title.lower().split()) for title in titles}
    unresolved = sorted(
        {
            title
            for question in questions
            for title in question.reference_titles
            if " ".join(title.lower().split()) not in normalized
        }
    )
    if unresolved:
        return Check(
            "ground truth vs corpus",
            "warn",
            f"{len(unresolved)} reference title(s) match no ingested document: "
            + ", ".join(repr(title) for title in unresolved[:3]),
            "Retrieval scores those questions zero forever, which reads as a retrieval "
            "failure. Fix the titles or ingest the documents.",
        )
    return Check(
        "ground truth vs corpus",
        "ok",
        "every reference title resolves to an ingested document",
    )


def _manifest_check(manifest_path: Path) -> Check | None:
    """Paths that still exist, and how many rows nobody has classified.

    Returns ``None`` when there is no manifest: a project that ingests by
    folder never writes one, and a missing file it never promised is not a
    finding.
    """
    if not manifest_path.exists():
        return None
    from sci_rag.ingest.manifest import load_manifest

    try:
        entries = load_manifest(manifest_path)
    except Exception as exc:
        return Check(
            "manifest",
            "fail",
            f"{type(exc).__name__}: {exc}",
            "Fix the JSONL (one valid JSON object per line).",
        )
    if not entries:
        return Check("manifest", "warn", f"{manifest_path.name} has no rows", "")

    missing = [entry.path.name for entry in entries if not entry.path.exists()]
    if missing:
        return Check(
            "manifest",
            "fail",
            f"{len(missing)} path(s) no longer exist: " + ", ".join(sorted(missing)[:5]),
            "Ingestion will fail on them. Restore the files or drop the rows.",
        )
    unknown = sum(1 for entry in entries if entry.license_class == "unknown")
    if unknown:
        return Check(
            "manifest",
            "warn",
            f"{len(entries)} row(s), {unknown} with unknown rights",
            "Unknown rights are excluded from scoped retrieval, which is the safe "
            'default. Decide them: see "Scope precedes ranking" in docs/methodology.md.',
        )
    return Check("manifest", "ok", f"{len(entries)} row(s), every path present, rights declared")


def doctor(
    probe: bool = typer.Option(
        False, "--probe", help="Also make one tiny live embedding and generation call."
    ),
) -> None:
    """Diagnose the environment: config, domain, database, corpus, credentials."""
    import asyncio

    checks = asyncio.run(_run_checks(probe=probe))

    table = Table(title="sci-rag doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    table.add_column("Fix", overflow="fold")
    icon = {"ok": "[green]ok[/green]", "warn": "[yellow]warn[/yellow]", "fail": "[red]FAIL[/red]"}
    for check in checks:
        table.add_row(check.name, icon[check.status], check.detail, check.fix)
    console.print(table)

    failures = [c for c in checks if c.status == "fail"]
    if failures:
        console.print(f"[red]{len(failures)} check(s) failed.[/red]")
        raise typer.Exit(1)
    console.print("[green]All checks passed.[/green]")


def _embedding_provider_check(settings: Settings) -> Check:
    """Whether the selected embedding route can actually answer calls.

    The three routes fail in different ways. Google needs a credential,
    local-hash deliberately runs without one, and ModelScope needs optional
    local packages plus a non-empty model id. Settings rejects an invalid
    ModelScope dimension during configuration loading, before doctor can build
    a table. Constructing the ModelScope embedder does not download anything;
    the first embed call loads the model.
    """
    if settings.embedding_provider == "google":
        mode = settings.credentials_mode()
        if mode != "none":
            return Check("credentials", "ok", f"mode={mode}")
        return Check(
            "credentials",
            "fail",
            "The google embedding provider is selected but no credentials are set.",
            "Set SCI_RAG_GOOGLE_API_KEY or SCI_RAG_GCP_PROJECT in .env, or use "
            "SCI_RAG_EMBEDDING_PROVIDER=local-hash for an offline dry run.",
        )
    if settings.embedding_provider == "local-hash":
        return Check(
            "credentials",
            "warn",
            "local-hash runs offline, but its rankings are lexical rather than semantic.",
            "Keep it for offline dry runs, or select a semantic embedding provider when "
            "rankings need meaning.",
        )

    missing = [name for name in ("modelscope", "sentence_transformers") if find_spec(name) is None]
    if missing:
        return Check(
            "credentials",
            "fail",
            "Missing local embedding dependencies: " + ", ".join(missing),
            _MODELSCOPE_INSTALL_FIX,
        )

    model_id = settings.embedding_model.strip()
    if not model_id:
        return Check(
            "credentials",
            "fail",
            f"modelscope model={settings.embedding_model!r}",
            "Set SCI_RAG_EMBEDDING_MODEL to a non-empty model id.",
        )
    return Check(
        "credentials",
        "ok",
        f"modelscope model={model_id}, dim={settings.embedding_dim}; dependencies installed",
    )


def _llm_credential_checks(settings: Settings) -> list[Check]:
    """One check per generation provider actually in use.

    Each provider carries its own credentials, so a deployment can embed with
    an AI Studio key while generating through Claude on Vertex. Checking the
    union of configured roles keeps the report honest about what will fail.

    A project that asks nothing of any provider is reported as a warning
    instead. Its generation features really are unavailable and the row still
    says so, but a project the user deliberately set up to run offline is not
    misconfigured, and failing it teaches them to ignore the diagnosis.
    """
    roles: dict[str, list[str]] = {}
    for role in ("answer", "extraction", "judge"):
        spec = settings.model_spec_for(role)
        roles.setdefault(spec.provider, []).append(role)

    offline = settings.is_offline()
    offline_fixes = {
        "google": "Set SCI_RAG_GOOGLE_API_KEY or SCI_RAG_GCP_PROJECT in .env to turn them on.",
        "deepseek": "Set SCI_RAG_DEEPSEEK_API_KEY in .env to turn them on.",
        "anthropic": "Set SCI_RAG_ANTHROPIC_API_KEY or SCI_RAG_GCP_PROJECT in .env to turn them on.",
        "openai-compatible": (
            "Set SCI_RAG_OPENAI_API_KEY or SCI_RAG_GCP_PROJECT in .env to turn them on."
        ),
    }
    checks: list[Check] = []
    for provider, used_by in roles.items():
        label = f"llm credentials ({provider})"
        where = ", ".join(used_by)
        if offline:
            checks.append(
                Check(
                    label,
                    "warn",
                    f"This project runs offline, so {where} are unavailable.",
                    offline_fixes[provider],
                )
            )
        elif provider == "google":
            if settings.credentials_mode() == "none":
                checks.append(
                    Check(
                        label,
                        "fail",
                        f"Used for {where}, but no Google credentials are set.",
                        "Set SCI_RAG_GOOGLE_API_KEY or SCI_RAG_GCP_PROJECT in .env.",
                    )
                )
            else:
                checks.append(Check(label, "ok", f"{where} via {settings.credentials_mode()}"))
        elif provider == "anthropic":
            if settings.anthropic_api_key:
                checks.append(Check(label, "ok", f"{where} via SCI_RAG_ANTHROPIC_API_KEY"))
            elif settings.gcp_project:
                checks.append(
                    Check(label, "ok", f"{where} via Vertex AI ({settings.gcp_location})")
                )
            else:
                checks.append(
                    Check(
                        label,
                        "fail",
                        f"Used for {where}, but neither Vertex nor an Anthropic key is set.",
                        "Set SCI_RAG_GCP_PROJECT to use Claude as a Vertex partner model, "
                        "or SCI_RAG_ANTHROPIC_API_KEY for the direct API.",
                    )
                )
        elif provider == "deepseek":
            if settings.deepseek_api_key:
                checks.append(Check(label, "ok", f"{where} via SCI_RAG_DEEPSEEK_API_KEY"))
            else:
                checks.append(
                    Check(
                        label,
                        "fail",
                        f"Used for {where}, but SCI_RAG_DEEPSEEK_API_KEY is not set.",
                        "Set SCI_RAG_DEEPSEEK_API_KEY in .env.",
                    )
                )
        else:  # openai-compatible
            if settings.openai_base_url and not settings.openai_api_key:
                checks.append(
                    Check(
                        label,
                        "fail",
                        f"Used for {where}: SCI_RAG_OPENAI_BASE_URL is set without a key.",
                        "Set SCI_RAG_OPENAI_API_KEY, or unset the base URL to use Vertex AI.",
                    )
                )
            elif settings.openai_api_key:
                target = settings.openai_base_url or "the OpenAI API"
                checks.append(Check(label, "ok", f"{where} via {target}"))
            elif settings.gcp_project:
                checks.append(
                    Check(label, "ok", f"{where} via Vertex Model Garden ({settings.gcp_location})")
                )
            else:
                checks.append(
                    Check(
                        label,
                        "fail",
                        f"Used for {where}, but no endpoint is configured.",
                        "Set SCI_RAG_GCP_PROJECT for Vertex Model Garden partner models, "
                        "or SCI_RAG_OPENAI_API_KEY (with an optional SCI_RAG_OPENAI_BASE_URL).",
                    )
                )
    return checks


async def _run_checks(*, probe: bool) -> list[Check]:
    from sci_rag.config import get_settings

    settings = get_settings()
    checks: list[Check] = []

    # --- configuration -------------------------------------------------
    mode = settings.credentials_mode()
    checks.append(
        Check(
            "config",
            "ok",
            f"embedding={settings.embedding_provider}:{settings.embedding_model}@{settings.embedding_dim}, "
            f"llm={settings.model_spec_for('answer')}, "
            f"extraction={settings.model_spec_for('extraction')}, "
            f"judge={settings.model_spec_for('judge')}, "
            f"google_credentials={mode}",
        )
    )
    checks.append(_embedding_provider_check(settings))
    checks.extend(_llm_credential_checks(settings))

    # --- domain profile -------------------------------------------------
    try:
        from sci_rag.domain import load_domain

        domain = load_domain(settings.domain_dir)
        missing_prompts = [
            name
            for name in _PROMPT_FILES
            if not (domain.directory / "prompts" / f"{name}.md").exists()
        ]
        if missing_prompts:
            checks.append(
                Check(
                    "domain",
                    "fail",
                    f"missing prompt template(s): {', '.join(missing_prompts)}",
                    "Restore them from the template's domain/prompts/ directory.",
                )
            )
        else:
            checks.append(
                Check(
                    "domain",
                    "ok",
                    f"{domain.name!r}: {len(domain.entity_type_names)} entity types, "
                    f"{len(domain.relation_type_names)} relation types, "
                    f"{len(domain.config.query_classes)} query classes",
                )
            )
    except Exception as exc:
        checks.append(
            Check(
                "domain",
                "fail",
                f"{type(exc).__name__}: {exc}",
                "Fix domain/domain.yaml (see domain/README.md).",
            )
        )
        domain = None

    seed_questions: list[SeedQuestion] = []
    if domain is not None:
        checks.append(_ontology_coherence_check(domain.config))
        try:
            from sci_rag.evals import load_seed_questions

            questions = load_seed_questions(domain.seed_questions_path())
            seed_questions = questions
            probes = sum(1 for q in questions if not q.answerable)
            status = "ok" if questions else "warn"
            note = f"{len(questions)} seed question(s), {probes} honesty probe(s)"
            checks.append(
                Check(
                    "seed questions",
                    status,
                    note,
                    "" if questions else "Write ground-truth questions before trusting any eval.",
                )
            )
            checks.append(_seed_coherence_check(questions))
            checks.append(_drafted_ground_truth_check(questions))
        except FileNotFoundError:
            checks.append(
                Check(
                    "seed questions",
                    "warn",
                    "domain/eval_seed_questions.jsonl not found",
                    "Create it (see docs/evaluation.md); evals need ground truth.",
                )
            )
        except Exception as exc:
            checks.append(
                Check(
                    "seed questions",
                    "fail",
                    f"{type(exc).__name__}: {exc}",
                    "Fix the JSONL (one valid JSON object per line).",
                )
            )

    # --- corpus manifest ---------------------------------------------------
    manifest_check = _manifest_check(settings.data_dir / "corpus.jsonl")
    if manifest_check is not None:
        checks.append(manifest_check)

    # --- parser availability ---------------------------------------------
    from sci_rag.ingest import docling_available

    if docling_available():
        checks.append(Check("pdf parser", "ok", "docling installed"))
    else:
        checks.append(
            Check(
                "pdf parser",
                "warn",
                "docling not installed; PDFs fall back to pypdf (reduced table fidelity)",
                "uv sync --extra docling",
            )
        )

    # --- database ---------------------------------------------------------
    from sqlalchemy import text

    from sci_rag.db import dispose_engine, get_engine

    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        checks.append(
            Check(
                "database",
                "fail",
                f"cannot connect ({type(exc).__name__})",
                f"{_database_start_hint()}, or fix SCI_RAG_DATABASE_URL in .env.",
            )
        )
        await dispose_engine()
        return checks
    checks.append(Check("database", "ok", settings.database_url.split("@")[-1]))

    async with engine.connect() as conn:
        vector_version = await conn.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        if vector_version is None:
            available = await conn.scalar(
                text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'")
            )
            checks.append(
                Check(
                    "pgvector",
                    "fail",
                    "extension not installed in this database"
                    + ("" if available else " (and not available on this server)"),
                    "Run sci-rag db upgrade (it creates the extension), or run "
                    f"the configured backend first: {_database_start_hint()}.",
                )
            )
            await dispose_engine()
            return checks
        checks.append(Check("pgvector", "ok", f"version {vector_version}"))

        revision = None
        try:
            revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        except Exception:
            await conn.rollback()
        if revision is None:
            checks.append(
                Check(
                    "schema",
                    "fail",
                    "tables not created yet",
                    "uv run sci-rag db upgrade",
                )
            )
            await dispose_engine()
            return checks
        if revision != _LATEST_SCHEMA_REVISION:
            checks.append(
                Check(
                    "schema",
                    "fail",
                    f"migration revision {revision}; expected {_LATEST_SCHEMA_REVISION}",
                    "uv run sci-rag db upgrade",
                )
            )
            await dispose_engine()
            return checks
        checks.append(Check("schema", "ok", f"migration revision {revision}"))

        expected_vector_type = f"vector({settings.embedding_dim})"
        vector_type_mismatches = []
        for table, column in (
            ("chunks", "embedding"),
            ("kg_communities", "summary_embedding"),
        ):
            column_type = await conn.scalar(
                text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = to_regclass(:table) AND attname = :column"
                ).bindparams(table=table, column=column)
            )
            label = f"{table}.{column}"
            if column_type is None:
                vector_type_mismatches.append(f"{label} is missing")
            elif column_type != expected_vector_type:
                vector_type_mismatches.append(
                    f"{label} has type {column_type}, expected {expected_vector_type}"
                )

        if vector_type_mismatches:
            checks.append(
                Check(
                    "embedding dimension",
                    "fail",
                    "; ".join(vector_type_mismatches) + f"; settings say {expected_vector_type}",
                    "Align SCI_RAG_EMBEDDING_DIM with the column, or recreate the "
                    "schema and re-ingest (see docs/quickstart.md troubleshooting).",
                )
            )
        else:
            checks.append(Check("embedding dimension", "ok", expected_vector_type))

        documents = await conn.scalar(text("SELECT count(*) FROM documents")) or 0
        chunks = await conn.scalar(text("SELECT count(*) FROM chunks")) or 0
        unembedded = (
            await conn.scalar(text("SELECT count(*) FROM chunks WHERE embedding IS NULL")) or 0
        )
        if documents == 0:
            checks.append(
                Check(
                    "corpus",
                    "warn",
                    "empty",
                    "uv run sci-rag ingest --manifest data/demo/manifest.jsonl (or your own corpus)",
                )
            )
        elif unembedded:
            checks.append(
                Check(
                    "corpus",
                    "warn",
                    f"{documents} documents, {chunks} chunks, {unembedded} without embeddings",
                    "Re-run ingestion for the affected documents.",
                )
            )
        else:
            checks.append(Check("corpus", "ok", f"{documents} documents, {chunks} chunks"))

        # Only meaningful once documents exist: a reference title that matches
        # nothing scores zero forever, and it reads as a retrieval failure.
        if documents and seed_questions:
            titles = {
                row[0]
                for row in (await conn.execute(text("SELECT title FROM documents"))).all()
                if row[0]
            }
            checks.append(_grounding_check(seed_questions, titles))

        retracted = (
            await conn.scalar(
                text(
                    "SELECT count(*) FROM documents "
                    "WHERE extra #>> '{crossref,is_retracted}' = 'true'"
                )
            )
            or 0
        )
        if retracted:
            checks.append(
                Check(
                    "retractions",
                    "warn",
                    f"{retracted} document(s) are flagged as retracted",
                    "Answers exclude them by default. Review them and use "
                    "sci-rag corpus delete when they should leave the corpus.",
                )
            )
        else:
            checks.append(Check("retractions", "ok", "no known retracted documents"))

        if chunks:
            from sci_rag.embed import get_embedder

            # An embedder that cannot be constructed is a diagnosis, not a
            # crash. Letting it escape kills the whole command before it
            # prints anything, including the credentials row that explains
            # why the embedder could not be built in the first place.
            # ModelScope construction only reads its version stamp; the first
            # embed call downloads and loads the model.
            try:
                current_version = get_embedder(settings).version
            except Exception as exc:
                checks.append(
                    Check(
                        "embedding versions",
                        "warn",
                        f"cannot be checked: {type(exc).__name__}: {str(exc)[:120]}",
                        "Fix the embedding provider configuration above, then re-run.",
                    )
                )
            else:
                stale_chunks = (
                    await conn.scalar(
                        text(
                            "SELECT count(*) FROM chunks "
                            "WHERE embedding_version IS DISTINCT FROM :v"
                        ).bindparams(v=current_version)
                    )
                    or 0
                )
                stale_communities = (
                    await conn.scalar(
                        text(
                            "SELECT count(*) FROM kg_communities WHERE summary IS NOT NULL "
                            "AND summary_embedding_version IS DISTINCT FROM :v"
                        ).bindparams(v=current_version)
                    )
                    or 0
                )
                if stale_chunks or stale_communities:
                    checks.append(
                        Check(
                            "embedding versions",
                            "warn",
                            f"{stale_chunks} chunk(s) and {stale_communities} community "
                            f"summar(ies) not on {current_version}",
                            "uv run sci-rag embed reindex --apply",
                        )
                    )
                else:
                    checks.append(
                        Check("embedding versions", "ok", f"all rows on {current_version}")
                    )

        orphaned = (
            await conn.scalar(
                text(
                    "SELECT count(*) FROM kg_entities "
                    "WHERE chunk_ids = '{}' AND document_ids = '{}' "
                    "AND canonical_entity_id IS NULL"
                )
            )
            or 0
        )
        if orphaned:
            checks.append(
                Check(
                    "graph hygiene",
                    "warn",
                    f"{orphaned} entit(ies) with no evidence (left by deletions)",
                    "uv run sci-rag graph gc --apply",
                )
            )

        duplicate_candidates = (
            await conn.scalar(
                text(
                    "WITH surfaces AS ("
                    "SELECT id, entity_type, lower(regexp_replace(name, '[^[:alnum:]]+', '', 'g')) "
                    "AS normalized FROM kg_entities WHERE canonical_entity_id IS NULL) "
                    "SELECT count(*) FROM ("
                    "SELECT entity_type, normalized FROM surfaces "
                    "WHERE normalized <> '' GROUP BY entity_type, normalized HAVING count(*) > 1"
                    ") duplicate_groups"
                )
            )
            or 0
        )
        if duplicate_candidates:
            checks.append(
                Check(
                    "entity resolution",
                    "warn",
                    f"{duplicate_candidates} exact normalized duplicate group(s)",
                    "uv run sci-rag graph resolve-entities --dry-run",
                )
            )
        else:
            checks.append(Check("entity resolution", "ok", "no exact normalized duplicates"))

        entities = await conn.scalar(text("SELECT count(*) FROM kg_entities")) or 0
        communities = await conn.scalar(text("SELECT count(*) FROM kg_communities")) or 0
        if documents and not entities:
            checks.append(
                Check(
                    "knowledge graph",
                    "warn",
                    "no entities yet (graph and community layers will return nothing)",
                    "uv run sci-rag graph extract && uv run sci-rag graph communities",
                )
            )
        else:
            checks.append(
                Check("knowledge graph", "ok", f"{entities} entities, {communities} communities")
            )

    # --- live probe -------------------------------------------------------
    if probe:
        checks.extend(await _live_probe(settings))

    await dispose_engine()
    return checks


async def _live_probe(settings) -> list[Check]:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import _safe_provider_text, probe_model_credentials

    checks: list[Check] = []
    try:
        from sci_rag.embed import get_embedder

        embedder = get_embedder(settings)
        start = time.monotonic()
        [vector] = await embedder.embed(["doctor probe"], task="query")
        checks.append(
            Check(
                "embedding probe",
                "ok",
                f"{embedder.version}, {len(vector)} dims, {int((time.monotonic() - start) * 1000)} ms",
            )
        )
    except Exception as exc:
        if settings.embedding_provider == "modelscope":
            message = str(exc)
            if _MODELSCOPE_INSTALL_FIX in message or "modelscope-embedding" in message:
                fix = _MODELSCOPE_INSTALL_FIX
            else:
                fix = (
                    "Check SCI_RAG_EMBEDDING_MODEL, SCI_RAG_MODELSCOPE_CACHE_DIR, and "
                    "network access, then rerun `uv run sci-rag doctor --probe`."
                )
        else:
            fix = "Check credentials and SCI_RAG_EMBEDDING_MODEL."
        checks.append(
            Check(
                "embedding probe",
                "fail",
                f"{type(exc).__name__}: {_safe_provider_text(exc, limit=120)}",
                fix,
            )
        )

    generation = await probe_model_credentials(settings)
    checks.append(
        Check(
            "generation probe",
            "ok" if generation.ok else "fail",
            generation.detail,
            generation.fix,
        )
    )
    return checks
