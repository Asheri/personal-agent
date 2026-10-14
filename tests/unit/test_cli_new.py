"""`sci-rag-new` end to end against a local checkout.

The network path has its own tests in test_scaffold_fetch.py; these drive the
whole command, which is where the fetch, the wizard, and the appliers have to
agree about the target directory.
"""

from __future__ import annotations

import io
import re
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sci_rag.cli.main import app as main_app
from sci_rag.cli.new import _preflight_credentials, app
from sci_rag.scaffold.prompt import PlainPrompter

REPO_ROOT = Path(__file__).parents[2]
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "300"})
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_FILES = ("pyproject.toml", "Makefile", "Dockerfile", ".env.example", "README.md", "LICENSE")
_TREES = ("domain", ".github")


def test_main_cli_registers_new_with_mode_and_plain_fallback_flags() -> None:
    result = runner.invoke(main_app, ["new", "--help"])

    assert result.exit_code == 0, result.output
    output = _ANSI.sub("", result.output)
    assert "--quick" in output
    assert "--advanced" in output
    assert "--no-tty" in output
    assert "--no-preflight" in output


def test_cancelling_an_interactive_prompt_exits_cleanly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.prompt import PromptAborted

    def abort(**_kwargs):  # type: ignore[no-untyped-def]
        raise PromptAborted("Setup cancelled.")

    monkeypatch.setattr("sci_rag.scaffold.wizard.collect_answers", abort)

    result = runner.invoke(app, ["--template-path", str(REPO_ROOT)])

    assert result.exit_code == 1
    output = _ANSI.sub("", result.output)
    assert "Setup cancelled." in output
    assert "Traceback" not in output


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "template"
    root.mkdir(parents=True)
    for name in _FILES:
        shutil.copy(REPO_ROOT / name, root / name)
    for tree in _TREES:
        shutil.copytree(REPO_ROOT / tree, root / tree)
    (root / "data" / "demo").mkdir(parents=True)
    (root / "data" / "demo" / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "infra" / "terraform").mkdir(parents=True)
    (root / "infra" / "terraform" / "main.tf").write_text("# tf\n", encoding="utf-8")
    return root


def test_defaults_create_a_project_directory(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.domain import load_domain

    ambient_deepseek_key = "ambient-deepseek-key-that-must-not-escape"
    ambient_google_key = "ambient-google-key-that-must-not-escape"
    monkeypatch.setenv("SCI_RAG_DEEPSEEK_API_KEY", ambient_deepseek_key)
    monkeypatch.setenv("SCI_RAG_GOOGLE_API_KEY", ambient_google_key)

    result = runner.invoke(
        app,
        [
            "--defaults",
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
    )

    assert result.exit_code == 0, result.output
    project = tmp_path / "workspace" / "my-scientific-kb"
    assert project.is_dir()
    assert load_domain(project / "domain").name == "My Scientific KB"
    env = (project / ".env").read_text(encoding="utf-8")
    active_keys = {
        line.split("=", 1)[0]
        for line in env.splitlines()
        if "=" in line and not line.startswith("#")
    }
    assert "SCI_RAG_LLM_PROVIDER=deepseek" in env
    assert "SCI_RAG_LLM_MODEL=deepseek-flash" in env
    assert "SCI_RAG_EMBEDDING_PROVIDER=modelscope" in env
    assert "SCI_RAG_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B" in env
    assert "SCI_RAG_EMBEDDING_DIM=1024" in env
    assert "SCI_RAG_DEEPSEEK_API_KEY" not in active_keys
    assert "SCI_RAG_GOOGLE_API_KEY" not in active_keys
    assert ambient_deepseek_key not in env
    assert ambient_google_key not in env
    output = _ANSI.sub("", result.output)
    assert ambient_deepseek_key not in output
    assert ambient_google_key not in output
    assert "make setup" in output
    assert "sci-rag build data/raw" in output
    assert "sci-rag draft ontology --from-corpus" in output
    assert "sci-rag draft questions --count 10" in output
    assert "docs/bring-your-own-domain.md" in output


def test_the_directory_is_named_from_the_answers(tmp_path: Path) -> None:
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump({"project_name": "Membrane Materials KB", "initialize_git": "No"}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "--answers-file",
            str(answers),
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "workspace" / "membrane-materials-kb").is_dir()


def test_a_generated_project_gets_its_own_git_history(tmp_path: Path) -> None:
    """Unlike `sci-rag init`, this one creates the directory, so it may init."""
    result = runner.invoke(
        app,
        [
            "--defaults",
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "workspace" / "my-scientific-kb" / ".git").is_dir()


def test_an_existing_non_empty_directory_is_refused(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    existing = workspace / "my-scientific-kb"
    existing.mkdir(parents=True)
    (existing / "mine.txt").write_text("do not touch\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--defaults",
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(workspace),
        ],
    )

    assert result.exit_code == 1
    assert "not empty" in _ANSI.sub("", result.output)
    assert (existing / "mine.txt").read_text(encoding="utf-8") == "do not touch\n"


# F-012 in the 2026-08-29 documentation route audit: an answers file could
# ask for `ontology: draft_with_llm`, and every answers-file run is
# noninteractive, so the draft was skipped and the answer replaced with
# `keep_demo_example`. Generation exited 0 and produced the worked demo
# ontology, which is not what the file asked for.
#
# The contract is now that the value is invalid in an answers file. Drafting
# still happens interactively, and `sci-rag draft ontology --print-prompt`
# with `--from-file` is the deterministic route for automation.


def test_defaults_pick_a_deterministic_ontology_with_no_fallback(tmp_path: Path) -> None:
    """--defaults selected nothing, so it should not announce a skipped draft."""
    result = runner.invoke(
        app,
        [
            "--defaults",
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
    )
    output = _ANSI.sub("", result.output)

    assert result.exit_code == 0, output
    assert "Skipping the LLM ontology draft" not in output
    assert "no draft was accepted" not in output


def test_an_answers_file_asking_to_draft_the_ontology_is_refused(tmp_path: Path) -> None:
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump({"ontology": "draft_with_llm", "initialize_git": "No"}), encoding="utf-8"
    )
    workspace = tmp_path / "workspace"

    result = runner.invoke(
        app,
        [
            "--answers-file",
            str(answers),
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(workspace),
        ],
    )
    output = _ANSI.sub("", result.output)

    assert result.exit_code != 0, output
    assert "draft_with_llm" in output
    assert "keep_demo_example" in output and "blank" in output, (
        "a refusal has to name what to write instead"
    )
    assert "sci-rag draft ontology" in output, (
        "a refusal should point at the route that does work without a terminal"
    )


def test_the_refusal_happens_before_anything_is_generated(tmp_path: Path) -> None:
    """Failing after a template copy would leave a half-made project behind."""
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump({"ontology": "draft_with_llm", "initialize_git": "No"}), encoding="utf-8"
    )
    workspace = tmp_path / "workspace"

    runner.invoke(
        app,
        [
            "--answers-file",
            str(answers),
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(workspace),
        ],
    )

    assert not workspace.exists() or list(workspace.iterdir()) == []


def test_the_deterministic_ontology_answers_still_work(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    for choice in ("keep_demo_example", "blank"):
        answers = tmp_path / f"answers-{choice}.yaml"
        answers.write_text(
            yaml.safe_dump(
                {"ontology": choice, "repo_name": f"kb-{choice}", "initialize_git": "No"}
            ),
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "--answers-file",
                str(answers),
                "--template-path",
                str(checkout),
                "--output-dir",
                str(tmp_path / "workspace"),
            ],
        )
        assert result.exit_code == 0, _ANSI.sub("", result.output)


def test_next_steps_use_the_chosen_managers_commands(tmp_path: Path) -> None:
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump({"environment_manager": "pixi", "initialize_git": "No"}), encoding="utf-8"
    )
    result = runner.invoke(
        app,
        [
            "--answers-file",
            str(answers),
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
    )
    output = _ANSI.sub("", result.output)
    assert "cd my-scientific-kb" in output
    assert "pixi install" in output
    assert "pixi run sci-rag doctor" in output
    assert "uv run" not in output


def test_an_unknown_answer_key_is_reported(tmp_path: Path) -> None:
    answers = tmp_path / "answers.yaml"
    answers.write_text(yaml.safe_dump({"projct_name": "typo"}), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--answers-file",
            str(answers),
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
    )
    assert result.exit_code == 1
    assert "projct_name" in _ANSI.sub("", result.output)


def test_answers_file_writes_a_key_without_printing_it(tmp_path: Path) -> None:
    key = "secret-key-that-must-not-escape"
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "credentials": "google_ai_studio",
                "google_api_key": key,
                "initialize_git": "No",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "--answers-file",
            str(answers),
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
    )

    assert result.exit_code == 0, result.output
    project = tmp_path / "workspace" / "my-scientific-kb"
    assert f"SCI_RAG_GOOGLE_API_KEY={key}" in (project / ".env").read_text(encoding="utf-8")
    assert key not in result.output


def test_answers_file_preserves_explicit_default_valued_environment_values(
    tmp_path: Path,
) -> None:
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "credentials": "google_ai_studio",
                "embedding_provider": "google",
                "llm_model": "deepseek-flash",
                "embedding_dim": 1024,
                "initialize_git": "No",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "--answers-file",
            str(answers),
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
    )

    assert result.exit_code == 0, result.output
    env = (tmp_path / "workspace" / "my-scientific-kb" / ".env").read_text(encoding="utf-8")
    assert "SCI_RAG_LLM_PROVIDER=google" in env
    assert "SCI_RAG_LLM_MODEL=deepseek-flash" in env
    assert "SCI_RAG_EMBEDDING_PROVIDER=google" in env
    assert "SCI_RAG_EMBEDDING_DIM=1024" in env


def test_failed_preflight_can_continue_without_downgrading_the_project(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import CredentialProbe

    key = "rejected-key-that-must-not-escape"
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_modelscope_dependencies",
        lambda: CredentialProbe(True, "ModelScope dependencies are installed."),
    )
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_google_credentials",
        lambda **_kwargs: CredentialProbe(
            False,
            "Google rejected the API key.",
            "Create a valid AI Studio key.",
        ),
    )

    def should_not_draft(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("option 3 must skip ontology drafting")

    monkeypatch.setattr("sci_rag.scaffold.wizard.confirm_ontology_draft", should_not_draft)
    replies = ["", "", "", "", "", "2", key, "", "3"]

    result = runner.invoke(
        app,
        [
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
        input="\n".join(replies) + "\n",
    )

    assert result.exit_code == 0, result.output
    output = _ANSI.sub("", result.output)
    assert "Google rejected the API key." in output
    assert "Continue without a model" in output
    assert "Traceback" not in output
    assert key not in output
    env = (tmp_path / "workspace" / "my-scientific-kb" / ".env").read_text(encoding="utf-8")
    assert f"SCI_RAG_GOOGLE_API_KEY={key}" in env
    assert "SCI_RAG_EMBEDDING_PROVIDER=google" in env


def test_successful_preflight_passes_the_explicit_key_to_the_ontology_draft(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import CredentialProbe

    key = "verified-key-that-must-not-escape"
    captured: dict[str, object] = {}
    llm = object()
    order: list[str] = []
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_modelscope_dependencies",
        lambda: CredentialProbe(True, "ModelScope dependencies are installed."),
    )
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_deepseek_credentials",
        lambda **_kwargs: (
            order.append("probe") or CredentialProbe(True, "gemini-2.5-flash answered in 1 ms.")
        ),
    )

    from sci_rag.scaffold.fetch import fetch_template as real_fetch

    def fetch(*args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("fetch")
        return real_fetch(*args, **kwargs)

    def build(settings, **kwargs):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured.update(kwargs)
        return llm

    def draft(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured["draft_llm"] = kwargs["llm"]
        return None

    monkeypatch.setattr("sci_rag.llm.get_llm", build)
    monkeypatch.setattr("sci_rag.scaffold.fetch.fetch_template", fetch)
    monkeypatch.setattr("sci_rag.scaffold.wizard.confirm_ontology_draft", draft)
    replies = ["", "", "", "", "", "", key, ""]

    result = runner.invoke(
        app,
        [
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
        input="\n".join(replies) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert captured["api_key_override"] == key
    assert captured["draft_llm"] is llm
    assert captured["settings"].llm_provider == "deepseek"
    assert captured["settings"].deepseek_api_key == key
    assert key not in result.output
    assert order[:2] == ["probe", "fetch"]


def test_google_defaults_use_resolved_values_for_preflight_and_ontology(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import CredentialProbe

    key = "google-key-that-must-not-escape"
    probe_args: dict[str, object] = {}
    build_args: dict[str, object] = {}
    llm = object()

    def probe(**kwargs):  # type: ignore[no-untyped-def]
        probe_args.update(kwargs)
        return CredentialProbe(True, "Google answered in 1 ms.")

    def should_not_check_dependencies(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Google defaults must not run the ModelScope dependency check")

    def build(settings, **kwargs):  # type: ignore[no-untyped-def]
        build_args["settings"] = settings
        build_args.update(kwargs)
        return llm

    def draft(*_args, **kwargs):  # type: ignore[no-untyped-def]
        build_args["draft_llm"] = kwargs["llm"]
        return None

    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_google_credentials", probe)
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_modelscope_dependencies",
        should_not_check_dependencies,
    )
    monkeypatch.setattr("sci_rag.llm.get_llm", build)
    monkeypatch.setattr("sci_rag.scaffold.wizard.confirm_ontology_draft", draft)

    result = runner.invoke(
        app,
        [
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
        input="\n".join(["", "", "", "", "", "2", key, ""]) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert probe_args["model"] == "gemini-3.6-flash"
    assert "embedding_provider" not in probe_args
    assert probe_args["model"] != "deepseek-flash"
    settings = build_args["settings"]
    assert settings.llm_provider == "google"
    assert settings.llm_model == "gemini-3.6-flash"
    assert build_args["draft_llm"] is llm
    assert key not in result.output


@pytest.mark.parametrize(
    ("credentials", "llm_provider", "llm_model", "expected_fix"),
    [
        (
            "google_ai_studio",
            "deepseek",
            "deepseek:deepseek-flash",
            "Select DeepSeek credentials or set the generation provider/model to Google.",
        ),
        (
            "deepseek",
            "google",
            "gemini-3.6-flash",
            "Select Google credentials or set the generation provider/model to DeepSeek.",
        ),
    ],
)
def test_preflight_rejects_a_cross_provider_pair_before_probing(
    credentials: str,
    llm_provider: str,
    llm_model: str,
    expected_fix: str,
) -> None:
    def should_not_probe(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("a cross-provider credential must not be probed")

    output = io.StringIO()
    prompter = PlainPrompter(io.StringIO(), output)
    raw = {
        "project_name": "Mismatched KB",
        "repo_name": "mismatched-kb",
        "credentials": credentials,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
    }

    verified = _preflight_credentials(
        raw,
        prompter,
        explicit_fields={"llm_provider", "llm_model"},
        probe=should_not_probe,
    )

    assert verified is False
    assert "Credential and generation provider do not match." in output.getvalue()
    assert expected_fix in output.getvalue()


@pytest.mark.parametrize(
    (
        "credentials",
        "answer_provider",
        "answer_model",
        "role_field",
        "role_model",
        "expected_fix",
    ),
    [
        (
            "google_ai_studio",
            "google",
            "gemini-3.6-flash",
            "extraction_model",
            "anthropic:claude-haiku-4-5",
            "Select Vertex AI credentials or set every generation role to Google.",
        ),
        (
            "google_ai_studio",
            "google",
            "gemini-3.6-flash",
            "judge_model",
            "openai-compatible:xai/grok-4.1-fast",
            "Select Vertex AI credentials or set every generation role to Google.",
        ),
        (
            "deepseek",
            "deepseek",
            "deepseek-flash",
            "extraction_model",
            "openai-compatible:xai/grok-4.1-fast",
            "Select Vertex AI credentials or set every generation role to DeepSeek.",
        ),
        (
            "deepseek",
            "deepseek",
            "deepseek-flash",
            "judge_model",
            "anthropic:claude-haiku-4-5",
            "Select Vertex AI credentials or set every generation role to DeepSeek.",
        ),
    ],
)
def test_preflight_rejects_role_specific_cross_provider_pairs_before_probing(
    credentials: str,
    answer_provider: str,
    answer_model: str,
    role_field: str,
    role_model: str,
    expected_fix: str,
) -> None:
    def should_not_probe(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("a cross-provider generation role must not be probed")

    output = io.StringIO()
    prompter = PlainPrompter(io.StringIO(), output)
    raw = {
        "project_name": "Role Mismatch",
        "repo_name": "role-mismatch",
        "credentials": credentials,
        "llm_provider": answer_provider,
        "llm_model": answer_model,
        role_field: role_model,
    }
    explicit_fields = {"llm_provider", "llm_model", role_field}

    verified = _preflight_credentials(
        raw,
        prompter,
        explicit_fields=explicit_fields,
        probe=should_not_probe,
    )

    assert verified is False
    assert "Credential and generation provider do not match." in output.getvalue()
    assert expected_fix in output.getvalue()


def test_deepseek_recovery_switches_to_google_probe_and_final_ontology(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import CredentialProbe

    deepseek_key = "deepseek-key-that-must-not-escape"
    google_key = "google-key-that-must-not-escape"
    deepseek_calls: list[dict[str, object]] = []
    google_calls: list[dict[str, object]] = []
    build_args: dict[str, object] = {}
    llm = object()

    def deepseek_probe(**kwargs):  # type: ignore[no-untyped-def]
        deepseek_calls.append(kwargs)
        return CredentialProbe(False, "DeepSeek rejected the key.", "Try another provider.")

    def google_probe(**kwargs):  # type: ignore[no-untyped-def]
        google_calls.append(kwargs)
        return CredentialProbe(True, "Google answered in 1 ms.")

    def build(settings, **kwargs):  # type: ignore[no-untyped-def]
        build_args["settings"] = settings
        build_args.update(kwargs)
        return llm

    def draft(*_args, **kwargs):  # type: ignore[no-untyped-def]
        build_args["draft_llm"] = kwargs["llm"]
        return None

    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_deepseek_credentials",
        deepseek_probe,
    )
    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_google_credentials", google_probe)
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_modelscope_dependencies",
        lambda: CredentialProbe(True, "ModelScope dependencies are installed."),
    )
    monkeypatch.setattr("sci_rag.llm.get_llm", build)
    monkeypatch.setattr("sci_rag.scaffold.wizard.confirm_ontology_draft", draft)

    result = runner.invoke(
        app,
        [
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
        input="\n".join(["", "", "", "", "", "", deepseek_key, "", "2", google_key]) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert len(deepseek_calls) == 1
    assert len(google_calls) == 1
    assert google_calls[0]["model"] == "gemini-3.6-flash"
    assert "embedding_provider" not in google_calls[0]
    assert google_calls[0]["model"] != "deepseek-flash"
    settings = build_args["settings"]
    assert settings.llm_provider == "google"
    assert settings.llm_model == "gemini-3.6-flash"
    assert build_args["draft_llm"] is llm

    env = (tmp_path / "workspace" / "my-scientific-kb" / ".env").read_text(encoding="utf-8")
    assert "SCI_RAG_LLM_PROVIDER=google" in env
    assert "SCI_RAG_LLM_MODEL=gemini-3.6-flash" in env
    assert "SCI_RAG_EMBEDDING_PROVIDER=google" in env
    assert f"SCI_RAG_GOOGLE_API_KEY={google_key}" in env
    assert "\nSCI_RAG_DEEPSEEK_API_KEY=" not in env
    assert deepseek_key not in result.output
    assert google_key not in result.output


def test_missing_modelscope_dependency_is_visible_and_skips_the_draft(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import CredentialProbe

    key = "deepseek-key-that-must-not-escape"
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_modelscope_dependencies",
        lambda: CredentialProbe(
            False,
            "Missing local embedding dependencies: modelscope.",
            "Install them with `uv sync --extra modelscope-embedding`.",
        ),
    )

    def should_not_probe(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("the local dependency failure must stop the credential probe")

    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_deepseek_credentials", should_not_probe)
    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_google_credentials", should_not_probe)

    def should_not_draft(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("a failed local dependency check must skip ontology drafting")

    monkeypatch.setattr("sci_rag.scaffold.wizard.confirm_ontology_draft", should_not_draft)

    result = runner.invoke(
        app,
        [
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
        input="\n".join(["", "", "", "", "", "", key, ""]) + "\n",
    )

    assert result.exit_code == 0, result.output
    output = _ANSI.sub("", result.output)
    assert "Missing local embedding dependencies" in output
    assert "uv sync --extra modelscope-embedding" in output
    assert key not in output


def test_no_preflight_skips_the_probe(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def should_not_probe(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("--no-preflight must skip the probe")

    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_google_credentials", should_not_probe)
    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_deepseek_credentials", should_not_probe)
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_modelscope_dependencies", should_not_probe
    )
    monkeypatch.setattr("sci_rag.llm.get_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "sci_rag.scaffold.wizard.confirm_ontology_draft",
        lambda *_args, **_kwargs: None,
    )
    key = "unprobed-key-that-must-not-escape"
    replies = ["", "", "", "", "", "", key, ""]

    result = runner.invoke(
        app,
        [
            "--no-preflight",
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
        input="\n".join(replies) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert key not in result.output


def test_offline_setup_skips_the_probe_without_a_flag(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def should_not_probe(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("offline setup must skip the probe")

    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_google_credentials", should_not_probe)
    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_deepseek_credentials", should_not_probe)
    replies = ["", "", "", "", "", "4", ""]

    result = runner.invoke(
        app,
        [
            "--template-path",
            str(_checkout(tmp_path)),
            "--output-dir",
            str(tmp_path / "workspace"),
        ],
        input="\n".join(replies) + "\n",
    )

    assert result.exit_code == 0, result.output


def test_unexpected_failure_is_sanitized_without_a_traceback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def explode(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("failure included secret-key-value")

    monkeypatch.setattr("sci_rag.scaffold.wizard.collect_answers", explode)

    result = runner.invoke(app)

    assert result.exit_code == 1
    output = _ANSI.sub("", result.output)
    assert "Setup failed unexpectedly (RuntimeError)." in output
    assert "--no-preflight" in output
    assert "Traceback" not in output
    assert "secret-key-value" not in output


def test_vertex_failure_can_switch_to_an_ai_studio_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import CredentialProbe

    key = "replacement-key-that-must-not-escape"
    calls: list[dict[str, str]] = []

    def probe(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        if len(calls) == 1:
            return CredentialProbe(False, "ADC is missing.", "Log in first.")
        return CredentialProbe(True, "The replacement key works.")

    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_google_credentials", probe)
    output = io.StringIO()
    prompter = PlainPrompter(io.StringIO(f"2\n{key}\n"), output)
    raw = {
        "project_name": "Vertex KB",
        "repo_name": "vertex-kb",
        "credentials": "vertex_ai",
        "gcp_project": "old-project",
        "llm_model": "gemini-2.5-flash",
    }

    assert _preflight_credentials(raw, prompter) is True
    assert raw == {
        "project_name": "Vertex KB",
        "repo_name": "vertex-kb",
        "credentials": "google_ai_studio",
        "gcp_project": "",
        "google_api_key": key,
        "llm_model": "gemini-2.5-flash",
    }
    assert calls[0]["gcp_project"] == "old-project"
    assert calls[1]["api_key"] == key
    assert key not in output.getvalue()
