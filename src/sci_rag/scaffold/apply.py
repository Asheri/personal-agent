"""The appliers: answers in, files out.

Each function takes the validated answers and a project root and returns a
change log describing what it did. They are ordinary functions over text, so
every one of them is testable offline against a copy of the real template.

There is no templating engine and no placeholder syntax here. The kit stays a
runnable repository; these functions rewrite its configuration in place, which
is why `sci-rag init` can run inside a checkout the user already has.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from sci_rag.domain import DomainConfig, RetrievalTuning, load_domain
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.licenses import needs_notice_file, render_license
from sci_rag.scaffold.permissions import set_owner_only

SEED_TEMPLATE = """\
# Ground-truth questions for the evaluation harness (one JSON object per line).
# Write 10 to 20 questions a domain expert can vouch for. Format:
#
# {"id": "unique-slug",
#  "question": "As a user would ask it",
#  "reference_answer": "What a correct answer must say",
#  "reference_titles": ["Exact document title that contains the answer"],
#  "evidence_phrases": ["a distinctive string from the answering passage", "42.7 g/L"],
#  "tags": ["your-label"]}
#
# Include one question the corpus canNOT answer, tagged "unanswerable",
# as an honesty probe. See docs/evaluation.md for advice on writing these.
"""

CORPUS_MANIFEST_TEMPLATE = """\
# Your corpus manifest: one JSON object per line, blank and # lines ignored.
# Only "path" is required; the kit does something sensible with the rest.
#
# {"path": "data/raw/paper.pdf",
#  "title": "Exact document title",
#  "authors": ["Family, Given"],
#  "year": 2024,
#  "doi": "10.0000/example",
#  "journal": "Journal Name",
#  "url": "https://example.org/paper.pdf",
#  "license_class": "public",
#  "source": "my-collection"}
#
# license_class controls redistribution. "unknown" is treated as unsafe to
# redistribute. See "Scope precedes ranking" in docs/methodology.md.
"""

DOI_FILE_TEMPLATE = """\
# One DOI per line. Blank lines and lines starting with # are ignored.
# Build the corpus from these with `make corpus`.
#
# 10.1016/j.memsci.2023.121000
"""

DOMAIN_YAML_HEADER = """\
# ---------------------------------------------------------------------------
# The domain profile. This file, the prompts/ folder next to it, and
# eval_seed_questions.jsonl are the ONLY things you edit to point the kit at
# a new scientific field. See domain/README.md for a guided walkthrough.
#
# Written by the sci-rag setup wizard. Re-run it with `sci-rag init`, or just
# edit this file: it is validated by the same model the kit reads it with.
# ---------------------------------------------------------------------------
"""

_KIT_URL = "https://github.com/sustainability-software-lab/sci-rag-kit"

# Only these two extras are driven by an answer. tokenizers is orthogonal, so
# it stays in a generated project either way.
_ANSWER_DRIVEN_EXTRAS = ("docling", "rerank")


# The change log is shown to the user and is the example on the docs homepage,
# so the label column is fixed rather than hand-aligned per call site.
_LOG_COLUMN = 23


def _log(label: str, detail: str) -> str:
    # A label wider than the column keeps a minimum gap rather than running
    # into its detail, which is how the documented transcript reads.
    padded = label.ljust(_LOG_COLUMN) if len(label) < _LOG_COLUMN else f"{label}   "
    return f"{padded}{detail}"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- domain profile ---------------------------------------------------------


def _domain_config(answers: ProjectAnswers, root: Path) -> DomainConfig:
    """The ontology the answers ask for, as a validated model.

    Serializing a :class:`DomainConfig` rather than patching YAML text means a
    generated ``domain.yaml`` cannot be something ``load_domain()`` rejects.
    The cost is the demo file's inline commentary, which the header above
    replaces with a pointer to the walkthrough.
    """
    retrieval = RetrievalTuning(reranker=answers.reranker_tuning())

    if answers.ontology == "draft_with_llm" and answers.drafted_ontology is not None:
        drafted = answers.drafted_ontology
        return DomainConfig(
            name=answers.project_name,
            description=answers.description,
            entity_types=drafted.entity_types,
            relation_types=drafted.relation_types,
            query_classes=drafted.query_classes,
            retrieval=retrieval,
        )

    if answers.ontology == "blank":
        return DomainConfig(
            name=answers.project_name, description=answers.description, retrieval=retrieval
        )

    existing = load_domain(root / "domain").config
    return DomainConfig(
        name=answers.project_name,
        description=answers.description,
        entity_types=existing.entity_types,
        relation_types=existing.relation_types,
        query_classes=existing.query_classes,
        retrieval=retrieval,
    )


def apply_domain_yaml(answers: ProjectAnswers, root: Path) -> list[str]:
    config = _domain_config(answers, root)
    body = yaml.safe_dump(
        config.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=88
    )
    _write(root / "domain" / "domain.yaml", DOMAIN_YAML_HEADER + "\n" + body)
    return [
        _log(
            "domain/domain.yaml",
            f"{len(config.entity_types)} entity types, "
            f"{len(config.relation_types)} relation types, "
            f"{len(config.query_classes)} query classes",
        )
    ]


#: The demo's own ground truth, beside the documents it answers. The demo
#: targets read this, so they work whatever the reader's corpus source is.
DEMO_SEED_QUESTIONS = Path("data") / "demo" / "eval_seed_questions.jsonl"


def apply_seed_questions(answers: ProjectAnswers, root: Path) -> list[str]:
    """Give the demo its own ground truth, and the reader theirs.

    Two files, because there are two corpora and two sets of questions.

    `data/demo/eval_seed_questions.jsonl` belongs to the synthetic corpus and
    travels with it. The `demo`, `demo-cloud`, and `benchmark` targets name it
    explicitly, so they score the documents they ingest.

    `domain/eval_seed_questions.jsonl` is the reader's. It is reset to a
    guided blank, because the bundled questions are answers about documents
    their corpus does not contain, and a bare `sci-rag eval retrieval` reading
    that blank refuses rather than scoring their corpus against synthetic
    ground truth. A `demo_only` project is the case where the two coincide:
    the demo is their corpus, so their file keeps the bundled questions.
    """
    log: list[str] = []
    source = root / "domain" / "eval_seed_questions.jsonl"
    bundled = source.read_text(encoding="utf-8") if source.exists() else ""

    if answers.include_demo_corpus and bundled:
        _write(root / DEMO_SEED_QUESTIONS, bundled)
        log.append(_log(DEMO_SEED_QUESTIONS.as_posix(), "ground truth for the demo corpus"))

    if answers.corpus_source == "demo_only":
        log.append(_log("domain/eval_seed_questions.jsonl", "kept: the demo corpus is the corpus"))
        return log

    _write(source, SEED_TEMPLATE)
    log.append(_log("domain/eval_seed_questions.jsonl", "guided blank"))
    return log


# --- .env -------------------------------------------------------------------

_ENV_LINE = re.compile(r"^(?P<comment>#\s*)?(?P<key>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")


def apply_env_file(answers: ProjectAnswers, root: Path) -> list[str]:
    """Generate `.env` from `.env.example`, keeping its guided comments.

    The example file is the documentation for these settings, so the generated
    file is the example with values filled in and the credential option the
    user did not choose left commented out, rather than a fresh minimal file.
    """
    api_key = answers.credentials == "google_ai_studio"
    vertex = answers.credentials == "vertex_ai"
    deepseek_key = bool(answers.credentials == "deepseek" and answers.deepseek_api_key)
    deepseek_value = answers.deepseek_api_key if deepseek_key else ""
    overrides: dict[str, tuple[str, bool]] = {
        "SCI_RAG_GOOGLE_API_KEY": (answers.google_api_key, api_key),
        "SCI_RAG_GCP_PROJECT": (answers.gcp_project, vertex),
        "SCI_RAG_GCP_LOCATION": ("us-central1", vertex),
        "SCI_RAG_DEEPSEEK_API_KEY": (deepseek_value, deepseek_key),
        "SCI_RAG_EMBEDDING_PROVIDER": (answers.embedding_provider, True),
        "SCI_RAG_EMBEDDING_MODEL": (answers.embedding_model, True),
        "SCI_RAG_EMBEDDING_DIM": (str(answers.embedding_dim), True),
        "SCI_RAG_LLM_PROVIDER": (answers.llm_provider, True),
        "SCI_RAG_LLM_MODEL": (answers.llm_model, True),
        "SCI_RAG_EXTRACTION_MODEL": (
            answers.extraction_model or "",
            answers.extraction_model is not None,
        ),
        "SCI_RAG_JUDGE_MODEL": (
            answers.judge_model or "",
            answers.judge_model is not None,
        ),
    }

    lines: list[str] = []
    substituted: set[str] = set()
    present_keys: set[str] = set()
    for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
        match = _ENV_LINE.match(line)
        key = match.group("key") if match else None
        if key:
            present_keys.add(key)
        if key in overrides and key not in substituted:
            value, enabled = overrides[key]
            prefix = "" if enabled else "# "
            lines.append(f"{prefix}{key}={value}")
            substituted.add(key)
        else:
            # Only the first assignment of a key is the setting; later ones are
            # illustrative, like the commented "provider:model" examples. They
            # must survive verbatim -- rewriting them with the chosen value
            # turns worked examples into confidently wrong advice.
            lines.append(line)

    # 旧版模板可能缺少新供应商的配置项。缺失时补写, 避免只替换存在的
    # Google 默认值后生成一个仍无法选择 ModelScope 或 DeepSeek 的项目。
    for key in (
        "SCI_RAG_EMBEDDING_PROVIDER",
        "SCI_RAG_EMBEDDING_MODEL",
        "SCI_RAG_EMBEDDING_DIM",
        "SCI_RAG_LLM_PROVIDER",
        "SCI_RAG_LLM_MODEL",
    ):
        if key not in substituted:
            value, _enabled = overrides[key]
            lines.append(f"{key}={value}")

    if "SCI_RAG_DEEPSEEK_API_KEY" not in substituted:
        value, enabled = overrides["SCI_RAG_DEEPSEEK_API_KEY"]
        prefix = "" if enabled else "# "
        lines.append(f"{prefix}SCI_RAG_DEEPSEEK_API_KEY={value}")
    if "SCI_RAG_MODELSCOPE_DEVICE" not in present_keys:
        lines.append("SCI_RAG_MODELSCOPE_DEVICE=auto")
    if "SCI_RAG_MODELSCOPE_CACHE_DIR" not in present_keys:
        lines.append("# SCI_RAG_MODELSCOPE_CACHE_DIR=")

    if answers.contact_email:
        lines += [
            "",
            "# --- Campaigns (OpenAlex, Crossref, Unpaywall polite pool) ------------------",
            "# Sent as the mailto identifying you to the metadata APIs. They rate-limit",
            "# anonymous traffic harder, so this makes campaigns faster and better behaved.",
            f"SCI_RAG_CAMPAIGN_MAILTO={answers.contact_email}",
            "# An OpenAlex premium key, if your institution has one.",
            "# OPENALEX_API_KEY=",
        ]

    env_path = root / ".env"
    _write(env_path, "\n".join(lines) + "\n")
    set_owner_only(env_path)
    return [
        _log(
            ".env",
            f"{answers.credentials}, {answers.llm_model}, {answers.embedding_model}",
        )
    ]


# --- build context ----------------------------------------------------------


_BUILD_DEFINITION_FILES = ("Dockerfile", ".dockerignore")
_BUILD_MANIFESTS = ((".dockerignore", ""), (".gcloudignore", "/"))


def dockerfile_context_sources(dockerfile: str) -> list[str]:
    """The paths a Dockerfile copies out of its build context.

    ``COPY --from=<stage>`` reads from an earlier stage, not the context.
    """
    sources: list[str] = []
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("COPY ") or "--from=" in stripped:
            continue
        parts = [part for part in stripped.split()[1:-1] if not part.startswith("--")]
        sources.extend(parts)
    return sources


def apply_build_context(answers: ProjectAnswers, root: Path) -> list[str]:
    """Admit exactly what this project's own Dockerfile copies.

    The kit's `.dockerignore` is fail closed and its allowlist is uv's:
    `pyproject.toml`, `uv.lock`, and the runtime inputs. A generated project
    keeps that file but not that Dockerfile. pixi copies a `pixi.toml`, conda
    an `environment.yml`, venv + pip a `requirements.txt`, and every one of
    those was excluded by the manifest it inherited, so the documented
    container route could not build.

    Deriving the allowlist from the rendered Dockerfile rather than from a
    per-manager list is what keeps the two from drifting again: a template
    that starts copying something new admits it in the same change.
    """
    dockerfile = root / "Dockerfile"
    if not dockerfile.exists():
        return []

    admitted = sorted(
        {
            source.split("/", 1)[0]
            for source in dockerfile_context_sources(dockerfile.read_text(encoding="utf-8"))
        }
        | set(_BUILD_DEFINITION_FILES)
    )

    changed: list[str] = []
    for name, anchor in _BUILD_MANIFESTS:
        path = root / name
        if not path.exists():
            continue
        rewritten = _readmit(path.read_text(encoding="utf-8"), admitted, anchor=anchor)
        if rewritten != path.read_text(encoding="utf-8"):
            _write(path, rewritten)
            changed.append(_log(name, f"admits {', '.join(admitted)}"))
    return changed


def _readmit(text: str, admitted: list[str], *, anchor: str) -> str:
    """Replace the re-admission block, keeping everything else exactly as is.

    The comments, the exclude-everything line, and the trailing bytecode
    exclusions are all load bearing and none of them depend on the manager.
    """
    lines = text.splitlines()
    first = next(index for index, line in enumerate(lines) if line.startswith("!"))
    last = max(index for index, line in enumerate(lines) if line.startswith("!"))
    block = [f"!{anchor}{name}" for name in admitted]
    return "\n".join(lines[:first] + block + lines[last + 1 :]) + "\n"


# --- .python-version --------------------------------------------------------


def apply_python_version(answers: ProjectAnswers, root: Path) -> list[str]:
    """Pin the interpreter file to the selected version.

    pyenv, uv, and rye all read this file, so leaving it at the template's
    value gave a reader a different interpreter from the one their CI, their
    image, and their package metadata had all agreed on.
    """
    path = root / ".python-version"
    if not path.exists():
        return []
    if path.read_text(encoding="utf-8").strip() == answers.python_version:
        return []
    _write(path, f"{answers.python_version}\n")
    return [_log(".python-version", answers.python_version)]


# --- uv.lock ----------------------------------------------------------------


@dataclass(frozen=True)
class RelockOutcome:
    """Whether the lockfile could be brought in line, and how.

    `how` says which attempt succeeded, so a reader can tell whether their
    generator reached the network. The offline route is the ordinary one.
    """

    how: str | None
    reason: str = ""


def _uv_relock(root: Path) -> RelockOutcome:
    """Bring the retained lockfile in line with the rewritten pyproject.

    The generated project only ever narrows the manifest: the package is
    renamed, the Python floor rises to the selected version, and unselected
    extras go away. Nothing new has to be resolved, so uv can usually do this
    from the lockfile it already has. Measured on a generated project, it
    removed 91 packages, retained 112, and changed the pinned version of none
    of them.

    Offline is tried first because it is the honest default: a generator
    should not reach the network without saying so. If the cache cannot
    satisfy it, one online attempt follows, because a correct lockfile is
    worth a download and the alternative is no lockfile at all.
    """
    attempts = ((["uv", "lock", "--offline"], "offline"), (["uv", "lock"], "online"))
    reason = "uv is not available"
    for command, label in attempts:
        try:
            completed = subprocess.run(
                command, cwd=root, capture_output=True, check=False, timeout=300
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            reason = f"{' '.join(command)}: {type(exc).__name__}"
            continue
        if completed.returncode == 0:
            return RelockOutcome(how=label)
        reason = _first_error_line(completed.stderr.decode("utf-8", "replace")) or (
            f"{' '.join(command)} exited {completed.returncode}"
        )
    return RelockOutcome(how=None, reason=reason)


def _first_error_line(stderr: str) -> str:
    for line in stderr.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("error"):
            return stripped[:200]
    return ""


def apply_uv_lock(
    answers: ProjectAnswers,
    root: Path,
    *,
    relock: Callable[[Path], RelockOutcome] = _uv_relock,
) -> list[str]:
    """Make the lockfile describe the generated project, or take it away.

    The template's lock describes the template: its name, its Python floor,
    and every extra it offers. A generated project renames the package,
    narrows the floor, and drops the extras the reader did not pick, so the
    retained lock described something else and `uv lock --check` refused it
    before the reader had typed anything.

    There are only two acceptable outcomes, and shipping a lockfile that
    disagrees with its own manifest is neither. If uv cannot be run here the
    lock is removed and the reader is told, which is what the other three
    managers already do with theirs.
    """
    path = root / "uv.lock"
    if not path.exists():
        return []
    outcome = relock(root)
    if outcome.how is not None:
        return [_log("uv.lock", f"relocked {outcome.how} for {answers.repo_name}")]
    path.unlink()
    return [
        _log("uv.lock", f"removed, `uv lock` recreates it. Could not relock: {outcome.reason}"),
    ]


# --- pyproject.toml ---------------------------------------------------------


def _drop_block_with_leading_comments(lines: list[str], predicate) -> list[str]:  # type: ignore[no-untyped-def]
    """Remove a line and the comment block that introduces it.

    Configuration files in this repo document each entry with a comment
    directly above it. Dropping the entry without its comment leaves prose
    describing something that is no longer there.
    """
    keep = list(lines)
    for index in range(len(keep) - 1, -1, -1):
        if not predicate(keep[index]):
            continue
        start = index
        while start > 0 and keep[start - 1].lstrip().startswith("#"):
            start -= 1
        del keep[start : index + 1]
    return keep


def apply_pyproject(answers: ProjectAnswers, root: Path) -> list[str]:
    path = root / "pyproject.toml"
    text = path.read_text(encoding="utf-8")

    text = re.sub(r'(?m)^name = ".*"$', f'name = "{answers.repo_name}"', text, count=1)
    text = re.sub(
        r'(?m)^description = ".*"$', f'description = "{answers.description}"', text, count=1
    )
    text = re.sub(
        r'(?m)^requires-python = ">=.*"$',
        f'requires-python = ">={answers.python_version}"',
        text,
        count=1,
    )
    # mypy's floor is a pin too. Left at the template's value, a project that
    # supports only 3.12 would be type checked against semantics it declares
    # it does not run on.
    text = re.sub(
        r'(?m)^python_version = ".*"$',
        f'python_version = "{answers.python_version}"',
        text,
        count=1,
    )

    lines = text.splitlines()
    # A project pinned to 3.12 should not advertise 3.11 support.
    dropped = [version for version in ("3.11", "3.12") if version < answers.python_version]
    for version in dropped:
        lines = [
            line
            for line in lines
            if line.strip() != f'"Programming Language :: Python :: {version}",'
        ]

    unwanted = [extra for extra in _ANSWER_DRIVEN_EXTRAS if extra not in answers.extras]
    for extra in unwanted:
        lines = _drop_block_with_leading_comments(
            lines, lambda line, extra=extra: line.startswith(f"{extra} = [")
        )

    _write(path, "\n".join(lines) + "\n")
    kept = ", ".join(answers.extras) or "none"
    return [_log("pyproject.toml", f"name, description, extras: {kept}")]


# --- README -----------------------------------------------------------------


def apply_readme(answers: ProjectAnswers, root: Path) -> list[str]:
    """Replace the kit's opening with the project's, keeping the rest.

    Everything from the first section heading down describes capabilities the
    generated project still has, so only the pitch above it is rewritten.
    """
    path = root / "README.md"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^## ", text)
    body = text[match.start() :] if match else ""

    opening = (
        f"# {answers.project_name}\n"
        "\n"
        f"{answers.description}\n"
        "\n"
        f"Built from [Sci RAG Kit]({_KIT_URL}): hybrid GraphRAG retrieval on PostgreSQL,\n"
        "grounded answers with citations, an evaluation harness, and REST plus MCP\n"
        "endpoints. What makes it this project rather than the kit lives in `domain/`.\n"
        "\n"
    )
    _write(path, opening + body)
    return [_log("README.md", "rewritten opening")]


# --- corpus scaffold --------------------------------------------------------

_CORPUS_TARGET_MARKER = "## corpus: build the document corpus this project was set up for."


def _append_make_target(root: Path, block: str) -> None:
    path = root / "Makefile"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^\.PHONY: (.*)$", lambda m: f".PHONY: {m.group(1)} corpus", text, count=1)
    _write(path, text.rstrip("\n") + "\n\n" + block)


def apply_corpus_scaffold(answers: ProjectAnswers, root: Path) -> list[str]:
    run = answers.runner.run

    if answers.corpus_source == "local_files":
        _write(root / "data" / "raw" / ".gitkeep", "")
        _write(root / "data" / "corpus.jsonl", CORPUS_MANIFEST_TEMPLATE)
        return [_log("data/corpus.jsonl", "commented field shape, ready for your documents")]

    if answers.corpus_source == "openalex_topic":
        command = (
            f'sci-rag campaign build --topic "{answers.openalex_topic}" '
            f"--max-results {answers.max_results}"
        )
        _append_make_target(
            root,
            f"{_CORPUS_TARGET_MARKER}\ncorpus:\n\t{run(command)}\n",
        )
        return [_log("data/campaigns/", f'openalex topic "{answers.openalex_topic}"')]

    if answers.corpus_source == "doi_list":
        _write(root / "data" / "dois.txt", DOI_FILE_TEMPLATE)
        command = "sci-rag campaign build --doi-file data/dois.txt"
        _append_make_target(
            root,
            f"{_CORPUS_TARGET_MARKER}\ncorpus:\n\t{run(command)}\n",
        )
        return [_log("data/dois.txt", "commented header, one DOI per line")]

    return [_log("data/demo/", "kept as the corpus; next step is `make demo`")]


# --- Makefile ---------------------------------------------------------------


def _remove_make_target(text: str, name: str) -> str:
    """Drop a target, its recipe, and the comment and variables above it."""
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(rf"^{re.escape(name)}:( |$)", line)), None
    )
    if start is None:
        return text

    end = start + 1
    while end < len(lines) and (lines[end].startswith("\t") or not lines[end].strip()):
        end += 1
    # Trailing blanks belong to the separator, not the target; keep exactly one.
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1

    while start > 0 and (
        lines[start - 1].lstrip().startswith("#") or re.match(r"^[A-Z_]+ *:?=", lines[start - 1])
    ):
        start -= 1
    while start > 0 and not lines[start - 1].strip():
        start -= 1
        break

    del lines[start:end]
    return "\n".join(lines) + "\n"


def apply_makefile(answers: ProjectAnswers, root: Path) -> list[str]:
    """Point the task commands at the chosen environment manager.

    Every command comes from the runner profile, so a project generated for a
    different manager cannot end up with another manager's commands here.
    """
    path = root / "Makefile"
    text = path.read_text(encoding="utf-8")

    sync = answers.runner.sync(extras=answers.extras)
    lines = text.splitlines()
    setup = next(
        (index for index, line in enumerate(lines) if re.match(r"^setup:( |$)", line)),
        None,
    )
    if setup is not None:
        recipe = next(
            (index for index in range(setup + 1, len(lines)) if lines[index].startswith("\t")),
            None,
        )
        if recipe is not None:
            lines[recipe] = f"\t{sync}"
            text = "\n".join(lines) + "\n"

    notes = [f"commands prefixed with `{answers.runner.run_prefix}`"]
    if answers.include_cloud_database:
        text = _use_cloud_postgres(text, answers)
        notes.append("Cloud SQL development database included")
    else:
        text = _remove_cloud_postgres_dispatch(text)
    if answers.runner.offers_local_postgres:
        text = _default_to_local_postgres(text)
        notes.append("database defaults to conda-forge, no Docker needed")

    if answers.include_demo_corpus:
        text = _score_demo_targets_against_demo_questions(text)

    _write(path, text)
    return [_log("Makefile", ", ".join(notes))]


#: Targets that ingest the demo corpus and then evaluate it. They score the
#: demo's ground truth, not the reader's. `eval` and `eval-ablation` are the
#: reader's own and are deliberately absent.
_DEMO_EVAL_TARGETS = ("demo", "demo-cloud", "benchmark")
_EVAL_COMMANDS = ("sci-rag eval retrieval", "sci-rag eval answers")


def _score_demo_targets_against_demo_questions(text: str) -> str:
    """Point the demo targets at the questions that came with the demo corpus.

    Without this they read `domain/eval_seed_questions.jsonl`, which is the
    reader's file and a guided blank for every corpus source but `demo_only`,
    so the target ingested and retrieved and then exited 1 on `No questions
    found`. Naming the demo's own file keeps the two sets of ground truth
    apart: a bare `sci-rag eval retrieval` still reads the reader's, and still
    refuses when it is empty.
    """
    lines = text.splitlines(keepends=True)
    for name in _DEMO_EVAL_TARGETS:
        start = next(
            (i for i, line in enumerate(lines) if re.match(rf"^{re.escape(name)}:( |$)", line)),
            None,
        )
        if start is None:
            continue
        index = start + 1
        while index < len(lines) and (lines[index].startswith("\t") or not lines[index].strip()):
            line = lines[index]
            if any(command in line for command in _EVAL_COMMANDS):
                lines[index] = line.rstrip("\n") + f" --questions {DEMO_SEED_QUESTIONS}\n"
            index += 1
    return "".join(lines)


def _default_to_local_postgres(text: str) -> str:
    """Make the bundled server the backend a reader gets by default.

    Only reached for a manager whose channel ships PostgreSQL. Bundling a
    server changes which branch runs when nobody chooses, and nothing else:
    `SCI_RAG_DB_BACKEND` is a public contract, so `docker` still has to reach
    the compose service and `local` still has to reach the helper script.
    Rewriting the docker recipe instead would start a loopback cluster with
    trust authentication for a reader who explicitly asked for the isolated
    container, which is a claim about their machine that is not true.

    The `local` recipe needs no work here. It already names the helper, and
    the runner pass rewrites its `uv run` prefix along with every other
    command in the file.
    """
    return text.replace("SCI_RAG_DB_BACKEND ?= docker", "SCI_RAG_DB_BACKEND ?= local", 1)


def _use_cloud_postgres(text: str, answers: ProjectAnswers) -> str:
    """Render the optional cloud helper through the selected runner profile."""
    run = answers.runner.run("python scripts/cloud_postgres.py", project_slug=answers.repo_name)
    return text.replace("uv run python scripts/cloud_postgres.py", run)


def _remove_cloud_postgres_dispatch(text: str) -> str:
    """Remove the cloud branch, and the offer of it, when the helper is pruned.

    The fallback message is part of the dispatch. Removing the branch and
    leaving the message listing `cloud` gives a reader a recipe that
    recommends a backend and then exits 2 when they take it.
    """
    for action in ("start", "stop"):
        block = (
            "ifeq ($(SCI_RAG_DB_BACKEND),cloud)\n"
            f"\tuv run python scripts/cloud_postgres.py {action}\n"
            "else ifeq ($(SCI_RAG_DB_BACKEND),local)"
        )
        text = text.replace(block, "ifeq ($(SCI_RAG_DB_BACKEND),local)")
    return text.replace("choose docker, local, or cloud.", "choose docker or local.")


# --- license ----------------------------------------------------------------


def apply_license(answers: ProjectAnswers, root: Path, *, year: int | None = None) -> list[str]:
    path = root / "LICENSE"
    resolved_year = year if year is not None else datetime.now(tz=UTC).year
    text = render_license(
        answers.open_source_license, author=answers.author_name, year=resolved_year
    )
    if text is None:
        path.unlink(missing_ok=True)
        return [_log("LICENSE", "removed (no license file)")]
    _write(path, text)
    if needs_notice_file(answers.open_source_license):
        # Apache's own appendix says the copyright belongs in a NOTICE file
        # or a source header, so the generator says it here rather than
        # editing a published legal text.
        return [
            _log("LICENSE", f"{answers.open_source_license}, full text"),
            _log(
                "note",
                "Apache-2.0 keeps your copyright out of LICENSE. Add a NOTICE file, "
                f'or a source header, reading "Copyright {resolved_year} '
                f'{answers.author_name or "the authors"}".',
            ),
        ]
    return [_log("LICENSE", answers.open_source_license)]


# --- pruning ----------------------------------------------------------------


def _remove_yaml_job(text: str, name: str) -> str:
    """Drop one job from a GitHub Actions workflow.

    A generated repository whose first CI run fails on a directory the wizard
    deleted is worse than no CI at all, so declining a feature has to take its
    job with it.
    """
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line == f"  {name}:"), None)
    if start is None:
        return text
    end = start + 1
    while end < len(lines) and not re.match(r"^  \S", lines[end]):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    while start > 0 and not lines[start - 1].strip():
        start -= 1
        break
    del lines[start:end]
    return "\n".join(lines) + "\n"


def _remove_markdown_section(text: str, heading: str) -> str:
    """Drop one H3 section while preserving the surrounding page structure."""
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line == f"### {heading}"), None)
    if start is None:
        return text
    end = start + 1
    while end < len(lines) and not re.match(r"^#{1,3} ", lines[end]):
        end += 1
    del lines[start:end]
    return "\n".join(lines) + "\n"


def _drop_lint_path(text: str, path_name: str) -> str:
    """Remove a directory from every ruff invocation.

    ``ruff check src tests examples scripts`` exits non-zero on a path that
    does not exist, so pruning a tree has to prune it from the lint command in
    both the Makefile and the workflow.
    """
    return re.sub(
        rf"(?m)(ruff (?:check|format --check)[^\n]*?) {re.escape(path_name)}\b", r"\1", text
    )


def apply_pruning(answers: ProjectAnswers, root: Path) -> list[str]:
    # The kit's own planning and agent workspaces are development history, not
    # the user's. They also describe every environment manager at once, so
    # leaving them in place would make a generated project look incoherent.
    removed: list[str] = []
    for name in ("planning", "full-stack-development", "superpowers", "aegis"):
        internal_docs = root / "docs" / name
        if internal_docs.is_dir():
            shutil.rmtree(internal_docs, ignore_errors=True)
            removed.append(f"docs/{name}/")

    if not answers.include_terraform:
        shutil.rmtree(root / "infra" / "terraform", ignore_errors=True)
        infra = root / "infra"
        if infra.is_dir() and not any(infra.iterdir()):
            infra.rmdir()
        workflow = root / ".github" / "workflows" / "ci.yml"
        if workflow.exists():
            _write(workflow, _remove_yaml_job(workflow.read_text(encoding="utf-8"), "terraform"))
        removed.append("infra/terraform/")

    if not answers.include_cloud_database:
        (root / "scripts" / "cloud_postgres.py").unlink(missing_ok=True)
        shutil.rmtree(root / "infra" / "terraform" / "dev-database", ignore_errors=True)
        makefile = root / "Makefile"
        if makefile.exists():
            _write(
                makefile,
                _remove_cloud_postgres_dispatch(makefile.read_text(encoding="utf-8")),
            )
        removed.extend(["scripts/cloud_postgres.py", "infra/terraform/dev-database/"])

    if not answers.include_demo_corpus:
        replay_only_files = (
            "scripts/graph_replay.py",
            "tests/unit/test_graph_replay_contract.py",
            "tests/integration/test_graph_replay.py",
            "tests/unit/test_graph_replay_makefile.py",
            "tests/unit/test_graph_replay_scaffold.py",
            "docs/adr/0011-committed-benchmark-graph-replay.md",
        )
        for relative in replay_only_files:
            (root / relative).unlink(missing_ok=True)
        for relative in ("docs/STYLE.md", "mkdocs.yml"):
            path = root / relative
            if path.exists():
                text = "\n".join(
                    line
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if "0011-committed-benchmark-graph-replay.md" not in line
                )
                _write(path, text.rstrip("\n") + "\n")
        faq = root / "docs" / "faq.md"
        if faq.exists():
            _write(
                faq,
                _remove_markdown_section(
                    faq.read_text(encoding="utf-8"),
                    "Why commit model output for the demo benchmark?",
                ),
            )
        shutil.rmtree(root / "data" / "demo", ignore_errors=True)
        shutil.rmtree(root / "examples", ignore_errors=True)
        makefile = root / "Makefile"
        if makefile.exists():
            text = makefile.read_text(encoding="utf-8")
            # benchmark-check before benchmark: the remover matches a target
            # name at the start of a line, and dropping `benchmark` first
            # would leave its check target pointing at reports nothing writes.
            for target in (
                "demo",
                "demo-cloud",
                "benchmark-refresh-graph",
                "benchmark-check",
                "benchmark",
            ):
                while re.search(rf"(?m)^{re.escape(target)}:(?: |$)", text):
                    text = _remove_make_target(text, target)
            text = re.sub(
                r"(?m)^(?:BENCH_GRAPH_REPLAY|GRAPH_REPLAY_RECEIPT)\s*:?=.*\n?",
                "",
                text,
            )
            text = re.sub(r"(?m)^(\.PHONY:.*)$", lambda m: _drop_phony(m.group(1)), text, count=1)
            text = _drop_lint_path(text, "examples")
            _write(makefile, text)
        workflow = root / ".github" / "workflows" / "ci.yml"
        if workflow.exists():
            _write(workflow, _drop_lint_path(workflow.read_text(encoding="utf-8"), "examples"))
        removed.extend(
            [
                "data/demo/",
                "examples/",
                *replay_only_files,
            ]
        )

    if not removed:
        return []
    return [_log("removed", ", ".join(removed))]


_PRUNED_PHONY = {
    "demo",
    "demo-cloud",
    "benchmark",
    "benchmark-check",
    "benchmark-refresh-graph",
    "clean-demo",
}


def _drop_phony(line: str) -> str:
    prefix, _, names = line.partition(":")
    kept = [name for name in names.split() if name not in _PRUNED_PHONY]
    return f"{prefix}: {' '.join(kept)}"


# --- git --------------------------------------------------------------------


def _git_identity(root: Path, answers: ProjectAnswers) -> list[str]:
    """`-c` overrides for the commit, only when git has no identity of its own.

    A fresh machine, a container, and a CI runner all commonly have no
    ``user.email`` configured, and `git commit` refuses to run without one.
    Falling back to the name and email the user just typed into the wizard
    beats not making the first commit at all. A configured identity always
    wins: overriding someone's own git config would be worse than the problem.
    """
    try:
        configured = subprocess.run(
            ["git", "config", "user.email"], cwd=root, capture_output=True, text=True
        )
    except OSError:
        return []
    if configured.returncode == 0 and configured.stdout.strip():
        return []
    name = answers.author_name or "sci-rag-kit"
    email = answers.contact_email or "noreply@example.invalid"
    return ["-c", f"user.name={name}", "-c", f"user.email={email}"]


def apply_git(answers: ProjectAnswers, root: Path) -> list[str]:
    """Initialize a repository, but never touch one that already exists.

    `sci-rag init` runs inside a checkout the user already has, so re-running
    `git init` there would be, at best, surprising.
    """
    if not answers.initialize_git or (root / ".git").exists():
        return []
    try:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        identity = _git_identity(root, answers)
        for command in (["add", "-A"], ["commit", "-m", "Initial commit"]):
            subprocess.run(
                ["git", *identity, *command], cwd=root, check=True, capture_output=True, text=True
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        return [_log("git", f"not initialized ({type(exc).__name__})")]
    return [_log("git", "initialized, 1 commit")]


# --- the whole run ----------------------------------------------------------


def apply_all(
    answers: ProjectAnswers, root: Path, *, year: int | None = None, allow_git: bool = True
) -> list[str]:
    """Run every applier in dependency order and return the combined log.

    Pruning goes first so the later writers never touch a file that is about
    to be deleted, and the corpus scaffold goes after the Makefile writer so
    its new target lands at the end.

    ``allow_git`` is off for `sci-rag init`, which configures a checkout the
    user already has. The ``initialize_git`` answer belongs to a run that
    creates the directory, and honouring it in an existing repository would
    mean initializing on top of the user's own history.
    """
    changes: list[str] = []
    changes += apply_pruning(answers, root)
    changes += apply_domain_yaml(answers, root)
    changes += apply_seed_questions(answers, root)
    changes += apply_env_file(answers, root)
    changes += apply_pyproject(answers, root)
    changes += apply_python_version(answers, root)
    changes += apply_makefile(answers, root)
    changes += apply_docs(answers, root)
    changes += apply_runner(answers, root)
    changes += apply_corpus_scaffold(answers, root)
    changes += apply_license(answers, root, year=year)
    changes += apply_readme(answers, root)
    if allow_git:
        changes += apply_git(answers, root)
    changes += [_log("note", note) for note in answers.coercions]
    return changes


# --- environment manager ----------------------------------------------------

# The surfaces a generated project executes or instructs from. Every one of
# them is rendered from the runner profile, and the coherence test asserts
# that none of them mentions a manager the user did not choose.
#
# CHANGELOG.md and docs/changelog.md are deliberately absent: they are the
# upstream template's history, and rewriting a past release note to mention a
# tool that release never used would be a lie in the service of a test.
COHERENCE_SURFACES = (
    "Makefile",
    "Dockerfile",
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "domain/README.md",
    ".github/workflows",
    ".devcontainer",
    "docs",
    "scripts",
    "src/sci_rag/cli/main.py",
)

_COHERENCE_SUFFIXES = {".md", ".yml", ".yaml", ".json", ".py", ""}
# docs/planning is pruned during generation, so this is belt and braces for a
# caller that runs the runner pass on its own. The changelogs are the upstream
# template's history: rewriting a past release note to mention a tool that
# release never used would be a lie in the service of a green test.
_COHERENCE_EXCLUDE = ("docs/planning", "docs/changelog.md", "CHANGELOG.md")


# Workflows that belong to the kit and not to a project made from it.
# `generated-projects.yml` generates a project per manager, so a generated
# project carrying it would try to generate projects. `release.yml` publishes
# under the name `sci-rag-kit` through this repository's Trusted Publishing
# configuration, so shipping it pre-wired would be worse than shipping none.
# Both also legitimately name every environment manager at once.
KIT_ONLY_WORKFLOWS = ("generated-projects.yml", "release.yml")

# Rendered whole from the profile, so the ordered text pass must skip them.
# Substituting inside a JSON string value breaks its quoting, which is how a
# venv+pip devcontainer ended up unparseable.
_RENDERED_WHOLE = ("Dockerfile", ".devcontainer/devcontainer.json")


def coherence_files(root: Path) -> list[Path]:
    """Every file the runner rewrite has to reach, resolved against a tree."""
    found: list[Path] = []
    for surface in COHERENCE_SURFACES:
        candidate = root / surface
        if candidate.is_file():
            found.append(candidate)
        elif candidate.is_dir():
            found.extend(
                path
                for path in sorted(candidate.rglob("*"))
                if path.is_file() and path.suffix in _COHERENCE_SUFFIXES
            )
    return [
        path
        for path in found
        if not any(part in path.relative_to(root).as_posix() for part in _COHERENCE_EXCLUDE)
    ]


def _rewrite_ci_setup(text: str, answers: ProjectAnswers) -> str:
    """Swap the workflow's manager bootstrap for the chosen one.

    The setup step is a block rather than a single string (the action plus its
    inputs), so it is replaced whole rather than by the ordered text pass.
    """
    profile = answers.runner
    block = profile.ci_setup_yaml(python_version=answers.python_version)
    matrix_block = profile.ci_setup_yaml(python_version="${{ matrix.python-version }}")
    pattern = re.compile(
        r"      - uses: astral-sh/setup-uv@v7\n"
        r"        with:\n"
        r"          python-version: (?P<version>[^\n]+)\n"
        r"          enable-cache: true"
    )

    def replace(match: re.Match[str]) -> str:
        return matrix_block if "matrix" in match.group("version") else block

    return pattern.sub(replace, text)


def _pin_ci_python_matrix(text: str, answers: ProjectAnswers) -> str:
    """Collapse the workflow matrix to the single answered interpreter.

    The template tests 3.11 and 3.12 because it supports both. A generated
    project pins one, and for the manifest-first managers the manifest decides
    it regardless, so the second leg would rebuild the same environment.
    """
    return re.sub(
        r'(?m)^(\s*)python-version: \["3\.11", "3\.12"\]$',
        lambda m: f'{m.group(1)}python-version: ["{answers.python_version}"]',
        text,
    )


def _write_dockerfile(answers: ProjectAnswers, root: Path) -> None:
    _write(
        root / "Dockerfile",
        answers.runner.dockerfile(
            python_version=answers.python_version,
            project_slug=answers.repo_name,
            dependency_file=answers.dependency_file,
        ),
    )


def _write_devcontainer(answers: ProjectAnswers, root: Path) -> None:
    """Point the dev container at the chosen manager.

    The lock file records a resolved digest for the uv feature, so it is
    removed rather than rewritten with a digest that would be invented.
    """
    import json

    path = root / ".devcontainer" / "devcontainer.json"
    if not path.exists():
        return
    profile = answers.runner
    config = json.loads(path.read_text(encoding="utf-8"))
    config["name"] = answers.repo_name
    config["workspaceFolder"] = f"/workspaces/{answers.repo_name}"
    config["features"] = {profile.devcontainer_feature: {}} if profile.devcontainer_feature else {}
    config["postCreateCommand"] = profile.devcontainer_post_create(project_slug=answers.repo_name)
    settings = config.get("customizations", {}).get("vscode", {}).get("settings")
    if isinstance(settings, dict) and "python.defaultInterpreterPath" in settings:
        settings["python.defaultInterpreterPath"] = profile.devcontainer_interpreter(
            project_slug=answers.repo_name
        )
    _write(path, json.dumps(config, indent=2) + "\n")
    (root / ".devcontainer" / "devcontainer-lock.json").unlink(missing_ok=True)


# The kit's own onboarding surface: how to install sci-rag-kit and what its
# wizard looks like. A project made with that wizard has already been
# onboarded, so carrying it would put someone else's install instructions on
# the user's homepage. The regions are marked in docs/index.md rather than
# matched by heading text, so editing the copy cannot break this.
_ONBOARDING_BEGIN = "<!-- BEGIN KIT ONBOARDING"
_ONBOARDING_END = "<!-- END KIT ONBOARDING -->"

_FEATURE_REGION = re.compile(
    r"(?ms)^<!-- BEGIN GENERATED PROJECT FEATURE: (?P<name>[a-z0-9-]+) -->\n"
    r"(?P<body>.*?)"
    r"^<!-- END GENERATED PROJECT FEATURE: (?P=name) -->\n?"
)
_FEATURE_REQUIREMENTS = {
    "cloud-helper": ("scripts/cloud_postgres.py",),
    "cloud-provisioning": ("infra/terraform/dev-database",),
}

KIT_ONLY_DOCS = (
    "docs/assets/casts",
    "docs/assets/vendor/asciinema-player",
    "docs/javascripts/cast.js",
    "scripts/render_cast.py",
    "tests/unit/test_docs_transcript.py",
)


def _strip_marked_regions(text: str) -> str:
    while _ONBOARDING_BEGIN in text:
        head, _, rest = text.partition(_ONBOARDING_BEGIN)
        _, _, tail = rest.partition(_ONBOARDING_END)
        text = head.rstrip("\n") + "\n" + tail.lstrip("\n")
    return text


def _render_feature_regions(text: str, root: Path) -> str:
    """Keep marked documentation only when its required files survived pruning."""

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        try:
            requirements = _FEATURE_REQUIREMENTS[name]
        except KeyError as exc:
            raise ValueError(f"unknown generated-project documentation feature: {name}") from exc
        if all((root / requirement).exists() for requirement in requirements):
            return match.group("body").rstrip("\n") + "\n"
        return ""

    return _FEATURE_REGION.sub(replace, text)


def apply_docs(answers: ProjectAnswers, root: Path) -> list[str]:
    """Remove kit-only and pruned-feature material from generated documentation.

    The pipx instructions and recorded wizard session install the kit, which a
    generated project has already done. Feature regions follow their retained
    files after pruning, so a project never documents a helper or module it no
    longer has. This runs before runner rewriting so kept command examples still
    adopt the selected environment manager.

    The onboarding player's supporting entries in ``mkdocs.yml`` and the
    ``Makefile`` go too, because a dangling asset or deleted renderer would break
    the generated project's documentation build.
    """
    del answers  # retained files, not answers, decide which feature regions survive

    docs = root / "docs"
    if docs.exists():
        for page in sorted(docs.rglob("*.md")):
            text = _render_feature_regions(page.read_text(encoding="utf-8"), root)
            if page == docs / "index.md":
                text = _strip_marked_regions(text)
            _write(page, text)

    for relative in KIT_ONLY_DOCS:
        path = root / relative
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

    config = root / "mkdocs.yml"
    if config.exists():
        text = config.read_text(encoding="utf-8")
        text = re.sub(r"(?ms)^extra_javascript:\n(?:[ #].*\n|\n(?=[ #]))*", "", text)
        text = "\n".join(
            line
            for line in text.splitlines()
            if "asciinema-player" not in line and "assets/casts" not in line
        )
        _write(config, text.rstrip("\n") + "\n")

    makefile = root / "Makefile"
    if makefile.exists():
        text = _remove_make_target(makefile.read_text(encoding="utf-8"), "cast")
        text = "\n".join(line for line in text.splitlines() if "render_cast.py" not in line)
        text = text.replace(" docs-reference cast ", " docs-reference ")
        _write(makefile, text.rstrip("\n") + "\n")

    return [_log("docs/", "kit onboarding, player, and cast removed")]


def apply_runner(answers: ProjectAnswers, root: Path) -> list[str]:
    """Render every manager-wired surface for the chosen environment manager.

    The template is already a uv project, so choosing uv is a no-op. For the
    other three this rewrites the task commands, the CI bootstrap, the
    container, the dev container, and the docs from one profile, then writes
    whatever manifest that manager needs.
    """
    from sci_rag.scaffold.manifests import write_manifest

    profile = answers.runner
    changes = write_manifest(answers, root)

    substitutions = profile.substitutions_from_uv(project_slug=answers.repo_name)
    touched = 0
    rendered_whole = {(root / name).resolve() for name in _RENDERED_WHOLE}
    for path in coherence_files(root):
        if path.resolve() in rendered_whole:
            continue
        original = path.read_text(encoding="utf-8", errors="strict")
        text = original
        if path.name.endswith(".yml") and path.parent.name == "workflows":
            text = _pin_ci_python_matrix(_rewrite_ci_setup(text, answers), answers)
        for old, new in substitutions:
            text = text.replace(old, new)
        if text != original:
            _write(path, text)
            touched += 1

    for workflow in KIT_ONLY_WORKFLOWS:
        (root / ".github" / "workflows" / workflow).unlink(missing_ok=True)

    _write_dockerfile(answers, root)
    _write_devcontainer(answers, root)
    if profile.lockfile != "uv.lock":
        (root / "uv.lock").unlink(missing_ok=True)
    else:
        changes += apply_uv_lock(answers, root)
    changes += apply_build_context(answers, root)

    changes.append(_log("Dockerfile", f"{profile.label} base image"))
    changes.append(_log(".devcontainer/", profile.devcontainer_feature or "plain python feature"))
    if touched:
        changes.append(_log("rendered", f"{touched} files for {profile.label}"))
    if profile.lockfile and profile.lockfile != "uv.lock":
        changes.append(_log(profile.lockfile, f"created on first `{profile.sync()}`"))
    return changes
