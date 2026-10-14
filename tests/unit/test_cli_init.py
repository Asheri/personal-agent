"""`sci-rag init` runs the wizard against an existing checkout.

The full generation path from a parent directory (`sci-rag-new`) is a
separate command; this one specializes the repository you are standing in.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml
from typer.testing import CliRunner

from sci_rag.cli.main import app

REPO_ROOT = Path(__file__).parents[2]
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "300"})
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_TEMPLATE_FILES = (
    "pyproject.toml",
    "Makefile",
    ".env.example",
    "README.md",
    "LICENSE",
    ".github/workflows/ci.yml",
)


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    for relative in _TEMPLATE_FILES:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)
    shutil.copytree(REPO_ROOT / "domain", root / "domain")
    (root / "infra" / "terraform").mkdir(parents=True)
    (root / "infra" / "terraform" / "main.tf").write_text("# terraform\n", encoding="utf-8")
    (root / "data" / "demo").mkdir(parents=True)
    (root / "data" / "demo" / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "examples").mkdir()
    (root / "examples" / "library_quickstart.py").write_text("# example\n", encoding="utf-8")
    return root


def test_init_is_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in _ANSI.sub("", result.output)


def test_init_help_renders() -> None:
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    output = _ANSI.sub("", result.output)
    assert "--quick" in output
    assert "--advanced" in output
    assert "--no-tty" in output


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    before = (checkout / "domain" / "domain.yaml").read_text(encoding="utf-8")

    result = runner.invoke(app, ["init", "--defaults", "--target", str(checkout), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert (checkout / "domain" / "domain.yaml").read_text(encoding="utf-8") == before
    assert not (checkout / ".env").exists()


def test_defaults_generate_a_working_project(tmp_path: Path) -> None:
    from sci_rag.domain import load_domain

    checkout = _checkout(tmp_path)

    result = runner.invoke(app, ["init", "--defaults", "--target", str(checkout)])

    assert result.exit_code == 0, result.output
    assert load_domain(checkout / "domain").name == "My Scientific KB"
    assert (checkout / ".env").exists()


def test_an_answers_file_drives_a_full_generation(tmp_path: Path) -> None:
    from sci_rag.domain import load_domain

    checkout = _checkout(tmp_path)
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "project_name": "Membrane Materials KB",
                "description": "Membrane chemistry and performance for water treatment",
                "author_name": "Berkeley Lab",
                "contact_email": "you@lbl.gov",
                "corpus_source": "openalex_topic",
                "openalex_topic": "polyamide membrane fouling",
                "max_results": 250,
                "pdf_parser": "docling",
                "include_terraform": "No",
                "include_demo_corpus": "No",
                "open_source_license": "MIT",
                "initialize_git": "No",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["init", "--answers-file", str(answers), "--target", str(checkout)])

    assert result.exit_code == 0, result.output
    assert load_domain(checkout / "domain").name == "Membrane Materials KB"
    assert 'name = "membrane-materials-kb"' in (checkout / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "MIT License" in (checkout / "LICENSE").read_text(encoding="utf-8")
    assert "SCI_RAG_CAMPAIGN_MAILTO=you@lbl.gov" in (checkout / ".env").read_text(encoding="utf-8")
    assert not (checkout / "infra" / "terraform").exists()
    assert not (checkout / "data" / "demo").exists()
    assert "polyamide membrane fouling" in (checkout / "Makefile").read_text(encoding="utf-8")


def test_the_change_log_is_printed(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    result = runner.invoke(app, ["init", "--defaults", "--target", str(checkout)])
    output = _ANSI.sub("", result.output)
    assert "domain/domain.yaml" in output
    assert ".env" in output


def test_init_refuses_a_target_that_is_not_a_checkout(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["init", "--defaults", "--target", str(empty)])
    assert result.exit_code != 0
    assert "pyproject.toml" in _ANSI.sub("", result.output)


def test_init_does_not_initialize_git_in_an_existing_checkout(tmp_path: Path) -> None:
    """`sci-rag init` specializes a repo you already have; it never re-inits it."""
    checkout = _checkout(tmp_path)
    answers = tmp_path / "answers.yaml"
    answers.write_text(yaml.safe_dump({"initialize_git": "Yes"}), encoding="utf-8")

    result = runner.invoke(app, ["init", "--answers-file", str(answers), "--target", str(checkout)])

    assert result.exit_code == 0, result.output
    assert not (checkout / ".git").exists()


def test_init_passes_a_captured_key_explicitly_to_ontology_drafting(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    checkout = _checkout(tmp_path)
    key = "init-key-that-must-not-escape"
    captured: dict[str, object] = {}
    llm = object()

    def build(settings, **kwargs):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured.update(kwargs)
        return llm

    def draft(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured["draft_llm"] = kwargs["llm"]
        return None

    monkeypatch.setattr("sci_rag.llm.get_llm", build)
    monkeypatch.setattr("sci_rag.scaffold.wizard.confirm_ontology_draft", draft)
    replies = ["", "", "", "", "", key, ""]

    result = runner.invoke(
        app,
        ["init", "--quick", "--no-tty", "--target", str(checkout)],
        input="\n".join(replies) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert captured["api_key_override"] == key
    assert captured["settings"].llm_provider == "deepseek"
    assert captured["settings"].deepseek_api_key == key
    assert captured["draft_llm"] is llm
    assert key not in result.output


def test_init_ontology_uses_the_resolved_google_model(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    checkout = _checkout(tmp_path)
    key = "google-init-key-that-must-not-escape"
    captured: dict[str, object] = {}
    llm = object()

    def build(settings, **kwargs):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured.update(kwargs)
        return llm

    def draft(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured["draft_llm"] = kwargs["llm"]
        return None

    monkeypatch.setattr("sci_rag.llm.get_llm", build)
    monkeypatch.setattr("sci_rag.scaffold.wizard.confirm_ontology_draft", draft)

    result = runner.invoke(
        app,
        ["init", "--quick", "--no-tty", "--target", str(checkout)],
        input="\n".join(["", "", "", "", "2", key, ""]) + "\n",
    )

    assert result.exit_code == 0, result.output
    settings = captured["settings"]
    assert settings.llm_provider == "google"
    assert settings.llm_model == "gemini-3.6-flash"
    assert captured["api_key_override"] == key
    assert captured["draft_llm"] is llm
    assert key not in result.output


def test_init_also_refuses_an_answers_file_that_asks_to_draft(tmp_path: Path) -> None:
    """`sci-rag init` shares the wizard, so it shares the contract. See #164."""
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump({"ontology": "draft_with_llm", "initialize_git": "No"}), encoding="utf-8"
    )
    target = _checkout(tmp_path)
    before = sorted(path.name for path in target.iterdir())

    result = runner.invoke(app, ["init", "--answers-file", str(answers), "--target", str(target)])
    output = result.output

    assert result.exit_code != 0, output
    assert "draft_with_llm" in output
    assert "keep_demo_example" in output
    assert sorted(path.name for path in target.iterdir()) == before, (
        "a refused run must not have started configuring the checkout"
    )
