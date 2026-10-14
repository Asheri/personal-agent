"""The appliers: answers in, file content out.

Each applier is a pure ``(ProjectAnswers, Path) -> list[str]`` over a copy of
the template, so these run offline against real repository files rather than
against a hand-written fixture that could drift from what ships.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from platform_checks import windows_acl_snapshot

from sci_rag.domain import DomainConfig, EntityTypeSpec, QueryClassSpec, RelationTypeSpec
from sci_rag.ingest.manifest import load_manifest
from sci_rag.scaffold import apply
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.questions import default_answers

REPO_ROOT = Path(__file__).parents[2]

# The files an applier reads or rewrites. Copied from the real repository so a
# change to any of them shows up here rather than in a user's generated project.
_TEMPLATE_FILES = (
    "pyproject.toml",
    "Makefile",
    ".env.example",
    "README.md",
    "uv.lock",
    ".github/workflows/ci.yml",
)


@pytest.fixture
def template(tmp_path: Path) -> Path:
    root = tmp_path / "template"
    for relative in _TEMPLATE_FILES:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)
    shutil.copytree(REPO_ROOT / "domain", root / "domain")
    # Stand-ins for the prunable trees: pruning cares that they disappear,
    # not what is inside them.
    (root / "infra" / "terraform").mkdir(parents=True)
    (root / "infra" / "terraform" / "main.tf").write_text("# terraform\n", encoding="utf-8")
    (root / "data" / "demo").mkdir(parents=True)
    (root / "data" / "demo" / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "examples").mkdir()
    (root / "examples" / "library_quickstart.py").write_text("# example\n", encoding="utf-8")
    return root


def _answers(**overrides: object) -> ProjectAnswers:
    raw = dict(default_answers())
    raw.update({k: str(v) for k, v in overrides.items()})
    return ProjectAnswers.from_raw(raw)


# --- domain.yaml ------------------------------------------------------------


def test_domain_yaml_round_trips_when_keeping_the_demo_ontology(template: Path) -> None:
    from sci_rag.domain import load_domain

    apply.apply_domain_yaml(
        _answers(project_name="Membrane KB", description="Membranes", ontology="keep_demo_example"),
        template,
    )
    profile = load_domain(template / "domain")
    assert profile.name == "Membrane KB"
    assert profile.config.description == "Membranes"
    # The demo ontology survives as a worked example.
    assert "Feedstock" in profile.entity_type_names


def test_domain_yaml_round_trips_when_blank(template: Path) -> None:
    from sci_rag.domain import load_domain

    apply.apply_domain_yaml(_answers(project_name="Blank KB", ontology="blank"), template)
    profile = load_domain(template / "domain")
    assert profile.name == "Blank KB"
    assert profile.entity_type_names == []
    assert profile.relation_type_names == []


def test_domain_yaml_round_trips_a_drafted_ontology(template: Path) -> None:
    from sci_rag.domain import load_domain

    drafted = DomainConfig(
        name="ignored",
        entity_types=[EntityTypeSpec(name="Membrane", description="A separation layer")],
        relation_types=[RelationTypeSpec(name="REMOVES")],
        query_classes=[QueryClassSpec(name="performance", keywords=["flux"])],
    )
    raw = dict(default_answers())
    raw.update({"project_name": "Membrane KB", "ontology": "draft_with_llm"})
    answers = ProjectAnswers.from_raw(raw, drafted_ontology=drafted)

    apply.apply_domain_yaml(answers, template)
    profile = load_domain(template / "domain")
    # The project name wins over whatever the model called the domain.
    assert profile.name == "Membrane KB"
    assert profile.entity_type_names == ["Membrane"]
    assert profile.relation_type_names == ["REMOVES"]


def test_domain_yaml_carries_the_reranker_answer(template: Path) -> None:
    from sci_rag.domain import load_domain

    apply.apply_domain_yaml(_answers(reranker="local_cross_encoder"), template)
    reranker = load_domain(template / "domain").config.retrieval.reranker
    assert reranker.enabled is True
    assert reranker.adapter == "local"


# --- seed questions ---------------------------------------------------------


def test_seed_questions_are_reset_to_a_guided_blank(template: Path) -> None:
    apply.apply_seed_questions(_answers(), template)
    seeds = (template / "domain" / "eval_seed_questions.jsonl").read_text(encoding="utf-8")
    assert seeds.startswith("# Ground-truth questions")
    assert "rice straw" not in seeds


@pytest.mark.parametrize("corpus_source", ("local_files", "doi_list", "openalex_topic"))
def test_every_corpus_source_that_is_not_the_demo_gets_the_guided_blank(
    template: Path, corpus_source: str
) -> None:
    """Ground truth for someone else's corpus is worse than none at all."""
    apply.apply_seed_questions(_answers(corpus_source=corpus_source), template)
    seeds = (template / "domain" / "eval_seed_questions.jsonl").read_text(encoding="utf-8")
    assert seeds.startswith("# Ground-truth questions")
    # The template's comment block quotes the field names, so the check is for
    # an actual question line rather than for the word "id".
    assert not [line for line in seeds.splitlines() if line.startswith("{")]


def test_demo_only_keeps_the_seed_questions_its_corpus_answers(template: Path) -> None:
    """`make demo` scores retrieval, so a demo project needs demo ground truth.

    The reset exists so a new project does not evaluate its own corpus against
    the synthetic one's answers. When the synthetic corpus is the corpus, the
    reset removed the only ground truth the shipped `demo` target has, and the
    documented run ended at `No questions found`.
    """
    before = (template / "domain" / "eval_seed_questions.jsonl").read_text(encoding="utf-8")

    changes = apply.apply_seed_questions(_answers(corpus_source="demo_only"), template)

    after = (template / "domain" / "eval_seed_questions.jsonl").read_text(encoding="utf-8")
    assert after == before
    assert [line for line in after.splitlines() if line.startswith("{")], (
        "the demo corpus questions have to survive generation"
    )
    assert "rice straw" in after.casefold()
    assert any("kept" in change for change in changes)


# --- .env -------------------------------------------------------------------


def test_env_keeps_the_guided_comments_from_the_example(template: Path) -> None:
    apply.apply_env_file(_answers(), template)
    env = (template / ".env").read_text(encoding="utf-8")
    assert "# sci-rag-kit configuration" in env
    assert "# --- Embeddings" in env


def test_generated_env_contains_deepseek_and_modelscope(tmp_path: Path) -> None:
    root = tmp_path
    (root / ".env.example").write_text(
        "SCI_RAG_LLM_PROVIDER=google\n"
        "SCI_RAG_LLM_MODEL=gemini-3.6-flash\n"
        "SCI_RAG_EMBEDDING_PROVIDER=google\n"
        "SCI_RAG_EMBEDDING_MODEL=gemini-embedding-001\n"
        "SCI_RAG_EMBEDDING_DIM=1536\n"
        "# SCI_RAG_DEEPSEEK_API_KEY=\n",
        encoding="utf-8",
    )
    answers = ProjectAnswers(
        project_name="Demo",
        repo_name="demo",
        credentials="deepseek",
        deepseek_api_key="secret",
    )

    changes = apply.apply_env_file(answers, root)

    env = (root / ".env").read_text(encoding="utf-8")
    assert "SCI_RAG_LLM_PROVIDER=deepseek" in env
    assert "SCI_RAG_LLM_MODEL=deepseek-flash" in env
    assert "SCI_RAG_EMBEDDING_PROVIDER=modelscope" in env
    assert "SCI_RAG_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B" in env
    assert "SCI_RAG_EMBEDDING_DIM=1024" in env
    assert "SCI_RAG_DEEPSEEK_API_KEY=secret" in env
    assert "SCI_RAG_MODELSCOPE_DEVICE=auto" in env
    assert "SCI_RAG_MODELSCOPE_CACHE_DIR=" in env
    assert "secret" not in repr(changes)


def test_generated_env_is_private_to_its_owner(template: Path) -> None:
    if os.name == "nt":
        env_path = template / ".env"
        env_path.write_text("fixture\n", encoding="utf-8")
        subprocess.run(
            ["icacls", str(env_path), "/grant:r", "*S-1-1-0:(M)"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        apply.apply_env_file(_answers(google_api_key="captured-secret"), template)
        acl = windows_acl_snapshot(env_path)
        assert acl["Protected"] is True
        assert acl["Count"] == 1
        assert acl["Sid"] == acl["CurrentSid"]
        assert "FullControl" in str(acl["Rights"])
        assert acl["AccessType"] == "Allow"
        assert acl["Inherited"] is False
        return

    apply.apply_env_file(_answers(google_api_key="captured-secret"), template)
    mode = stat.S_IMODE((template / ".env").stat().st_mode)
    assert mode == 0o600


def test_env_leaves_illustrative_examples_alone(template: Path) -> None:
    # .env.example documents the provider settings with commented
    # "provider:model" examples. Only the first assignment of a key is the
    # setting; rewriting the later ones with the chosen value would turn a
    # worked example into confidently wrong advice.
    apply.apply_env_file(_answers(llm_model="gemini-2.5-flash"), template)
    env = (template / ".env").read_text(encoding="utf-8")

    assignments = [line for line in env.splitlines() if line.startswith("SCI_RAG_LLM_MODEL=")]
    assert assignments == ["SCI_RAG_LLM_MODEL=gemini-2.5-flash"]
    assert "#   SCI_RAG_LLM_MODEL=anthropic:claude-haiku-4-5" in env


def test_generated_env_preserves_generation_role_overrides(template: Path) -> None:
    apply.apply_env_file(
        _answers(
            credentials="vertex_ai",
            extraction_model="anthropic:claude-haiku-4-5",
            judge_model="openai-compatible:xai/grok-4.1-fast",
        ),
        template,
    )
    env = (template / ".env").read_text(encoding="utf-8")

    assert "SCI_RAG_EXTRACTION_MODEL=anthropic:claude-haiku-4-5" in env
    assert "SCI_RAG_JUDGE_MODEL=openai-compatible:xai/grok-4.1-fast" in env


def test_env_for_an_ai_studio_key_enables_only_that_option(template: Path) -> None:
    apply.apply_env_file(
        _answers(credentials="google_ai_studio", google_api_key="captured-studio-key"), template
    )
    env = (template / ".env").read_text(encoding="utf-8")
    assert "\nSCI_RAG_GOOGLE_API_KEY=captured-studio-key" in env
    assert "\nSCI_RAG_GCP_PROJECT=" not in env


@pytest.mark.parametrize(
    ("credentials", "expected_llm_provider", "expected_llm_model"),
    [
        ("google_ai_studio", "google", "gemini-3.6-flash"),
        ("vertex_ai", "google", "gemini-3.6-flash"),
        ("deepseek", "deepseek", "deepseek-flash"),
    ],
)
def test_env_coordinates_credentials_with_provider_defaults(
    template: Path,
    credentials: str,
    expected_llm_provider: str,
    expected_llm_model: str,
) -> None:
    if credentials == "deepseek":
        answers = _answers(credentials=credentials, deepseek_api_key="deepseek-secret")
        active_key = "SCI_RAG_DEEPSEEK_API_KEY=deepseek-secret"
    else:
        answers = _answers(
            credentials=credentials,
            embedding_provider="google",
            google_api_key="google-secret",
            gcp_project="science-project",
        )
        active_key = "SCI_RAG_GOOGLE_API_KEY=google-secret"

    apply.apply_env_file(answers, template)
    env = (template / ".env").read_text(encoding="utf-8")

    assert f"SCI_RAG_LLM_PROVIDER={expected_llm_provider}" in env
    assert f"SCI_RAG_LLM_MODEL={expected_llm_model}" in env
    assert active_key in env
    if credentials == "deepseek":
        assert "SCI_RAG_EMBEDDING_PROVIDER=modelscope" in env
        assert "SCI_RAG_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B" in env
        assert "SCI_RAG_EMBEDDING_DIM=1024" in env
    else:
        assert "SCI_RAG_EMBEDDING_PROVIDER=google" in env
        assert "SCI_RAG_EMBEDDING_MODEL=gemini-embedding-001" in env
        assert "SCI_RAG_EMBEDDING_DIM=1024" in env


def test_env_for_vertex_enables_the_project_and_location(template: Path) -> None:
    apply.apply_env_file(_answers(credentials="vertex_ai", gcp_project="science-project"), template)
    env = (template / ".env").read_text(encoding="utf-8")
    assert "\nSCI_RAG_GCP_PROJECT=science-project" in env
    assert "\nSCI_RAG_GCP_LOCATION=us-central1" in env
    assert "\nSCI_RAG_GOOGLE_API_KEY=" not in env


def test_env_change_log_never_contains_the_api_key(template: Path) -> None:
    key = "secret-key-that-must-not-escape"

    changes = apply.apply_env_file(
        _answers(credentials="google_ai_studio", google_api_key=key), template
    )

    assert key not in repr(changes)


def test_env_offline_leaves_both_credential_options_commented(template: Path) -> None:
    key = "offline-key-that-must-not-escape"
    apply.apply_env_file(_answers(credentials="offline", deepseek_api_key=key), template)
    env = (template / ".env").read_text(encoding="utf-8")
    assert "\nSCI_RAG_GOOGLE_API_KEY=" not in env
    assert "\nSCI_RAG_GCP_PROJECT=" not in env
    assert "\nSCI_RAG_DEEPSEEK_API_KEY=" not in env
    assert "\nSCI_RAG_EMBEDDING_PROVIDER=local-hash" in env
    assert key not in env


def test_env_carries_the_model_answers(template: Path) -> None:
    apply.apply_env_file(_answers(llm_model="gemini-3-pro", embedding_dim="768"), template)
    env = (template / ".env").read_text(encoding="utf-8")
    assert "\nSCI_RAG_LLM_MODEL=gemini-3-pro" in env
    assert "\nSCI_RAG_EMBEDDING_DIM=768" in env


def test_env_writes_the_campaign_mailto_from_the_contact_email(template: Path) -> None:
    apply.apply_env_file(_answers(contact_email="you@lbl.gov"), template)
    env = (template / ".env").read_text(encoding="utf-8")
    assert "\nSCI_RAG_CAMPAIGN_MAILTO=you@lbl.gov" in env


def test_env_omits_the_mailto_when_no_email_was_given(template: Path) -> None:
    apply.apply_env_file(_answers(contact_email=""), template)
    assert "SCI_RAG_CAMPAIGN_MAILTO" not in (template / ".env").read_text(encoding="utf-8")


# --- pyproject.toml ---------------------------------------------------------


def test_pyproject_takes_the_name_and_description(template: Path) -> None:
    apply.apply_pyproject(
        _answers(repo_name="membrane-materials-kb", description="Membrane chemistry"), template
    )
    text = (template / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "membrane-materials-kb"' in text
    assert 'description = "Membrane chemistry"' in text


def test_pyproject_drops_extras_the_answers_did_not_select(template: Path) -> None:
    apply.apply_pyproject(_answers(pdf_parser="pypdf", reranker="none"), template)
    text = (template / "pyproject.toml").read_text(encoding="utf-8")
    assert "docling = [" not in text
    assert "rerank = [" not in text
    # Token counting is not driven by any answer, so it always survives.
    assert "tokenizers = [" in text


def test_pyproject_keeps_the_extras_the_answers_selected(template: Path) -> None:
    apply.apply_pyproject(_answers(pdf_parser="docling", reranker="local_cross_encoder"), template)
    text = (template / "pyproject.toml").read_text(encoding="utf-8")
    assert "docling = [" in text
    assert "rerank = [" in text


def test_pyproject_pins_the_answered_python_version(template: Path) -> None:
    apply.apply_pyproject(_answers(python_version="3.11"), template)
    text = (template / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in text


# --- corpus scaffold --------------------------------------------------------


def test_local_files_corpus_manifest_parses_as_an_empty_manifest(template: Path) -> None:
    apply.apply_corpus_scaffold(_answers(corpus_source="local_files"), template)
    assert (template / "data" / "raw" / ".gitkeep").exists()
    manifest = template / "data" / "corpus.jsonl"
    assert manifest.exists()
    # Every line is a comment, so load_manifest sees a valid, empty manifest.
    assert load_manifest(manifest) == []


def test_doi_list_corpus_writes_a_commented_header(template: Path) -> None:
    apply.apply_corpus_scaffold(_answers(corpus_source="doi_list"), template)
    dois = (template / "data" / "dois.txt").read_text(encoding="utf-8")
    assert dois.lstrip().startswith("#")
    assert "10." in dois


def test_openalex_corpus_writes_a_make_target_with_the_topic(template: Path) -> None:
    apply.apply_corpus_scaffold(
        _answers(
            corpus_source="openalex_topic", openalex_topic="polyamide fouling", max_results=250
        ),
        template,
    )
    makefile = (template / "Makefile").read_text(encoding="utf-8")
    assert "corpus:" in makefile
    assert 'sci-rag campaign build --topic "polyamide fouling" --max-results 250' in makefile


def test_doi_list_make_target_points_at_the_doi_file(template: Path) -> None:
    apply.apply_corpus_scaffold(_answers(corpus_source="doi_list"), template)
    makefile = (template / "Makefile").read_text(encoding="utf-8")
    assert "--doi-file data/dois.txt" in makefile


def test_demo_only_corpus_adds_no_corpus_target(template: Path) -> None:
    apply.apply_corpus_scaffold(_answers(corpus_source="demo_only"), template)
    assert "corpus:" not in (template / "Makefile").read_text(encoding="utf-8")


# --- pruning ----------------------------------------------------------------


def test_declining_terraform_removes_the_tree_and_the_ci_job(template: Path) -> None:
    apply.apply_pruning(_answers(include_terraform="No"), template)
    assert not (template / "infra" / "terraform").exists()
    ci = (template / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "terraform:" not in ci
    assert "hashicorp/setup-terraform" not in ci
    # The jobs after it must survive.
    assert "docs-links:" in ci
    assert "docs:" in ci


def test_keeping_terraform_leaves_the_ci_job_alone(template: Path) -> None:
    apply.apply_pruning(_answers(include_terraform="Yes"), template)
    assert (template / "infra" / "terraform").exists()
    assert "terraform:" in (template / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )


def test_declining_cloud_database_removes_only_its_assets(template: Path) -> None:
    cloud_script = template / "scripts" / "cloud_postgres.py"
    cloud_script.parent.mkdir(parents=True)
    cloud_script.write_text("# cloud helper\n", encoding="utf-8")
    cloud_module = template / "infra" / "terraform" / "dev-database"
    cloud_module.mkdir()
    (cloud_module / "main.tf").write_text("# cloud module\n", encoding="utf-8")

    apply.apply_pruning(_answers(include_cloud_database="No"), template)

    assert not cloud_script.exists()
    assert not cloud_module.exists()
    assert (template / "infra" / "terraform" / "main.tf").exists()


def test_keeping_cloud_database_leaves_its_assets(template: Path) -> None:
    cloud_script = template / "scripts" / "cloud_postgres.py"
    cloud_script.parent.mkdir(parents=True)
    cloud_script.write_text("# cloud helper\n", encoding="utf-8")
    cloud_module = template / "infra" / "terraform" / "dev-database"
    cloud_module.mkdir()
    (cloud_module / "main.tf").write_text("# cloud module\n", encoding="utf-8")

    apply.apply_pruning(_answers(include_cloud_database="Yes"), template)

    assert cloud_script.exists()
    assert cloud_module.exists()


def test_declining_the_demo_corpus_removes_the_demo_and_the_examples(template: Path) -> None:
    """examples/library_quickstart.py reads data/demo, so they go together."""
    apply.apply_pruning(_answers(include_demo_corpus="No"), template)
    assert not (template / "data" / "demo").exists()
    assert not (template / "examples").exists()


def test_pruned_paths_are_not_referenced_by_the_generated_build(template: Path) -> None:
    """The class of bug that breaks a generated repo's very first CI run."""
    apply.apply_pruning(_answers(include_terraform="No", include_demo_corpus="No"), template)
    makefile = (template / "Makefile").read_text(encoding="utf-8")
    ci = (template / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for surface in (makefile, ci):
        assert "examples" not in surface
        assert "data/demo" not in surface
        assert "infra/terraform" not in surface
    # And the targets that only made sense with a demo corpus are gone.
    assert "demo:" not in makefile
    assert "demo-cloud:" not in makefile
    assert "benchmark:" not in makefile


# --- license ----------------------------------------------------------------


def test_license_is_written_with_the_author_and_year(template: Path) -> None:
    apply.apply_license(
        _answers(author_name="Berkeley Lab", open_source_license="MIT"), template, year=2026
    )
    text = (template / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "2026 Berkeley Lab" in text


def test_declining_a_license_removes_the_file(template: Path) -> None:
    (template / "LICENSE").write_text("BSD-3-Clause ...\n", encoding="utf-8")
    apply.apply_license(_answers(open_source_license="No license file"), template, year=2026)
    assert not (template / "LICENSE").exists()


# --- README -----------------------------------------------------------------


def test_readme_opening_is_rewritten_for_the_project(template: Path) -> None:
    apply.apply_readme(
        _answers(project_name="Membrane Materials KB", description="Membrane chemistry"), template
    )
    readme = (template / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Membrane Materials KB")
    assert "Membrane chemistry" in readme
    # The kit's own opening is gone.
    assert "A template repository for retrieval-augmented generation" not in readme
    # Everything from the first section heading onward survives.
    assert "## Components" in readme


def test_readme_attribution_uses_the_unhyphenated_display_name(template: Path) -> None:
    """A generated project inherits this line, so the kit's name is spelled once here."""
    apply.apply_readme(_answers(), template)
    readme = (template / "README.md").read_text(encoding="utf-8")
    assert "[Sci RAG Kit](" in readme
    assert "Sci-RAG Kit" not in readme


# --- Makefile ---------------------------------------------------------------


def test_setup_target_installs_default_and_selected_extras(template: Path) -> None:
    apply.apply_makefile(_answers(pdf_parser="docling", reranker="local_cross_encoder"), template)
    makefile = (template / "Makefile").read_text(encoding="utf-8")
    assert (
        "\tuv sync --extra modelscope-embedding --extra openai "
        "--extra docling --extra rerank\n" in makefile
    )


def test_setup_target_keeps_default_extras_without_selected_extras(template: Path) -> None:
    apply.apply_makefile(_answers(pdf_parser="pypdf", reranker="none"), template)
    makefile = (template / "Makefile").read_text(encoding="utf-8")
    assert "\tuv sync --extra modelscope-embedding --extra openai\n" in makefile


# --- the whole run ----------------------------------------------------------


def test_apply_all_reports_every_file_it_touched(template: Path) -> None:
    changes = apply.apply_all(_answers(initialize_git="No"), template, year=2026)
    joined = "\n".join(changes)
    for expected in ("domain/domain.yaml", ".env", "pyproject.toml", "README.md", "LICENSE"):
        assert expected in joined


# ADR 0004's no-placeholder constraint used to be asserted here, against the
# five-file fixture above. That fixture has nothing under docs/, so the check
# could not see any file capable of violating it, and the documentation's
# claim about it was false for two years. It now lives in
# tests/unit/test_scaffold_runner_coherence.py, which generates from the real
# template for every environment manager. See #166.


def test_git_init_works_where_git_has_no_configured_identity(template: Path) -> None:
    """A fresh machine, a container, and a CI runner all often have none.

    `git commit` refuses to run without a user.email, so without a fallback the
    first commit of a generated project silently does not happen.
    """
    import subprocess

    changes = apply.apply_git(_answers(initialize_git="Yes", author_name="Berkeley Lab"), template)

    assert changes == [apply._log("git", "initialized, 1 commit")]
    log = subprocess.run(
        ["git", "log", "-1", "--format=%an <%ae>"],
        cwd=template,
        capture_output=True,
        text=True,
        check=True,
    )
    assert log.stdout.strip()


def test_a_configured_git_identity_is_not_overridden(template: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=template, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "mine@example.org"], cwd=template, check=True)
    subprocess.run(["git", "config", "user.name", "Mine"], cwd=template, check=True)

    identity = apply._git_identity(template, _answers(author_name="Someone Else"))

    assert identity == []


# --- the generated lockfile still describes the generated project ------------
#
# F-018 in the 2026-08-29 documentation route audit: the applier renamed the
# package in pyproject.toml and left the root record in uv.lock saying
# `sci-rag-kit`, so an untouched generated project failed `uv lock --check
# --offline` with exit 2 before the reader had typed anything.


def _rename_project(answers: ProjectAnswers, root: Path) -> None:
    """The two appliers that together decide what the lockfile must say.

    `relock` stands in for uv so this stays a unit test. What uv does when it
    is really there is proved by the `generate (uv)` CI leg, which runs
    `uv lock --check --offline` against the generated project.
    """
    apply.apply_pyproject(answers, root)
    apply.apply_uv_lock(answers, root, relock=_stub_relock)


def _stub_relock(root: Path) -> apply.RelockOutcome:
    """What `uv lock --offline` does to the root record, minus the resolver."""
    path = root / "uv.lock"
    name = re.search(
        r'(?m)^name = "([^"]+)"$', (root / "pyproject.toml").read_text(encoding="utf-8")
    ).group(1)
    blocks = path.read_text(encoding="utf-8").split("[[package]]")
    for index, block in enumerate(blocks):
        if 'source = { editable = "." }' in block:
            blocks[index] = re.sub(r'(?m)^name = ".*"$', f'name = "{name}"', block, count=1)
            break
    path.write_text("[[package]]".join(blocks), encoding="utf-8")
    return apply.RelockOutcome(how="offline")


def _lock_root_record(root: Path) -> dict[str, str]:
    """The name and version of the editable root package in uv.lock."""
    text = (root / "uv.lock").read_text(encoding="utf-8")
    for block in text.split("[[package]]"):
        if 'source = { editable = "." }' not in block:
            continue
        return {
            "name": re.search(r'name = "([^"]+)"', block).group(1),
            "version": re.search(r'version = "([^"]+)"', block).group(1),
        }
    raise AssertionError("uv.lock has no editable root package record")


def _pyproject_field(root: Path, field: str) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(rf'(?m)^{field} = "([^"]+)"$', text).group(1)


def test_the_lock_root_record_follows_the_renamed_package(template: Path) -> None:
    _rename_project(
        _answers(project_name="Membrane Materials KB", repo_name="membrane-materials-kb"), template
    )

    assert _pyproject_field(template, "name") == "membrane-materials-kb"
    assert _lock_root_record(template)["name"] == "membrane-materials-kb"


def test_the_lock_and_pyproject_agree_on_the_version(template: Path) -> None:
    """uv checks the version too, so moving only the name would still fail."""
    _rename_project(
        _answers(project_name="Membrane Materials KB", repo_name="membrane-materials-kb"), template
    )

    assert _lock_root_record(template)["version"] == _pyproject_field(template, "version")


def test_the_default_project_name_is_covered_too(template: Path) -> None:
    """The audit reproduced this with --defaults as well as an answers file."""
    _rename_project(_answers(), template)

    assert _lock_root_record(template)["name"] == _pyproject_field(template, "name")


def test_a_lock_that_cannot_be_relocked_is_removed_rather_than_shipped(
    template: Path,
) -> None:
    """The one thing that must never happen is a lock describing something else."""
    changes = apply.apply_uv_lock(
        _answers(),
        template,
        relock=lambda root: apply.RelockOutcome(how=None, reason="uv is not available"),
    )

    assert not (template / "uv.lock").exists()
    assert any("uv.lock" in change and "removed" in change for change in changes), changes
    assert any("uv is not available" in change for change in changes), (
        "a silent fallback hides why the reader has no lockfile"
    )


def test_a_relock_says_whether_it_reached_the_network(template: Path) -> None:
    """`--template-path` promises no network, so the report has to say."""
    offline = apply.apply_uv_lock(
        _answers(), template, relock=lambda root: apply.RelockOutcome(how="offline")
    )
    assert any("relocked offline" in change for change in offline), offline

    online = apply.apply_uv_lock(
        _answers(), template, relock=lambda root: apply.RelockOutcome(how="online")
    )
    assert any("relocked online" in change for change in online), online


def test_a_relocked_project_reports_it(template: Path) -> None:
    changes = apply.apply_uv_lock(
        _answers(repo_name="membrane-materials-kb"), template, relock=_stub_relock
    )

    assert (template / "uv.lock").exists()
    assert any("membrane-materials-kb" in change for change in changes), changes


def test_a_project_with_no_lock_is_left_alone(template: Path) -> None:
    """pixi, conda, and venv + pip delete theirs before this ever runs."""
    (template / "uv.lock").unlink()

    assert apply.apply_uv_lock(_answers(), template, relock=_stub_relock) == []


def test_the_uv_leg_of_generated_projects_checks_the_lockfile() -> None:
    """A static assertion did not catch this. The resolver has to run."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "generated-projects.yml").read_text(
        encoding="utf-8"
    )
    assert "uv lock --check" in workflow, (
        "the generated uv project is never checked against its own lockfile"
    )


def test_an_apache_project_is_told_where_its_copyright_goes(template: Path) -> None:
    """The license itself says NOTICE, so generation has to say it too. See #165."""
    changes = apply.apply_license(
        _answers(open_source_license="Apache-2.0", author_name="A Scientist"),
        template,
        year=2026,
    )

    license_text = (template / "LICENSE").read_text(encoding="utf-8")
    assert "END OF TERMS AND CONDITIONS" in license_text
    assert "A Scientist" not in license_text

    guidance = " ".join(changes)
    assert "NOTICE" in guidance
    assert "Copyright 2026 A Scientist" in guidance


def test_a_bsd_project_gets_no_notice_advice_it_does_not_need(template: Path) -> None:
    changes = apply.apply_license(
        _answers(open_source_license="BSD-3-Clause", author_name="A Scientist"),
        template,
        year=2026,
    )

    assert "A Scientist" in (template / "LICENSE").read_text(encoding="utf-8")
    assert "NOTICE" not in " ".join(changes)
