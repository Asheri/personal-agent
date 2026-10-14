"""Dependency manifests for the managers that do not read pyproject directly.

pixi reads pyproject but needs its own tables; conda and pip need a file of
their own. All three are derived from the project's real dependency lists, so
a dependency added to pyproject.toml reaches every manager.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from sci_rag.scaffold import manifests
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.questions import default_answers

REPO_ROOT = Path(__file__).parents[2]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    shutil.copy(REPO_ROOT / "pyproject.toml", root / "pyproject.toml")
    return root


def _answers(**overrides: object) -> ProjectAnswers:
    raw = dict(default_answers())
    raw.update({k: str(v) for k, v in overrides.items()})
    return ProjectAnswers.from_raw(raw)


def test_runtime_and_dev_dependencies_are_read_from_pyproject(project: Path) -> None:
    read = manifests.read_dependencies(project)
    assert any(d.startswith("fastapi") for d in read.runtime)
    assert any(d.startswith("pytest") for d in read.dev)
    assert "docling" in read.extras
    assert any(d.startswith("mkdocs") for d in read.docs)


# --- pixi -------------------------------------------------------------------


def test_pixi_tables_are_appended_to_pyproject(project: Path) -> None:
    manifests.write_pixi(_answers(environment_manager="pixi"), project)
    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.pixi.workspace]" in text
    assert 'channels = ["conda-forge"]' in text
    assert "[tool.pixi.tasks]" in text


def test_pixi_pins_the_answered_python_version(project: Path) -> None:
    manifests.write_pixi(_answers(environment_manager="pixi", python_version="3.11"), project)
    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert 'python = "3.11.*"' in text


def test_pixi_tasks_mirror_the_make_targets(project: Path) -> None:
    manifests.write_pixi(_answers(environment_manager="pixi"), project)
    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    for task in ("db-upgrade", "test", "lint", "format", "typecheck", "serve", "doctor"):
        assert f'{task} = "' in text


def test_pixi_tables_parse_as_toml(project: Path) -> None:
    import tomllib

    manifests.write_pixi(_answers(environment_manager="pixi"), project)
    parsed = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert parsed["tool"]["pixi"]["workspace"]["channels"] == ["conda-forge"]
    assert "sci-rag doctor" in " ".join(parsed["tool"]["pixi"]["tasks"].values())


def test_pixi_can_write_a_standalone_manifest(project: Path) -> None:
    """`dependency_file = pixi.toml` keeps pyproject free of pixi tables."""
    manifests.write_pixi(_answers(environment_manager="pixi", dependency_file="pixi.toml"), project)
    assert (project / "pixi.toml").exists()
    assert "[tool.pixi" not in (project / "pyproject.toml").read_text(encoding="utf-8")


def test_pixi_selects_the_extras_the_answers_asked_for(project: Path) -> None:
    manifests.write_pixi(_answers(environment_manager="pixi", pdf_parser="docling"), project)
    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    pixi_section = text[text.index("[tool.pixi") :]
    assert "docling" in pixi_section


# --- conda ------------------------------------------------------------------


def test_environment_yml_is_named_after_the_project(project: Path) -> None:
    manifests.write_conda(_answers(environment_manager="conda", repo_name="membrane-kb"), project)
    parsed = yaml.safe_load((project / "environment.yml").read_text(encoding="utf-8"))
    assert parsed["name"] == "membrane-kb"
    assert parsed["channels"] == ["conda-forge"]


def test_environment_yml_pins_python_and_installs_the_project(project: Path) -> None:
    manifests.write_conda(_answers(environment_manager="conda", python_version="3.11"), project)
    parsed = yaml.safe_load((project / "environment.yml").read_text(encoding="utf-8"))
    assert "python=3.11" in parsed["dependencies"]
    pip_section = next(d for d in parsed["dependencies"] if isinstance(d, dict))
    assert any(entry.startswith("-e") or entry == "-e ." for entry in pip_section["pip"])


def test_environment_yml_carries_the_dev_dependencies(project: Path) -> None:
    manifests.write_conda(_answers(environment_manager="conda"), project)
    parsed = yaml.safe_load((project / "environment.yml").read_text(encoding="utf-8"))
    pip_section = next(d for d in parsed["dependencies"] if isinstance(d, dict))
    assert any(entry.startswith("pytest") for entry in pip_section["pip"])


# --- venv + pip -------------------------------------------------------------


def test_requirements_files_split_runtime_from_dev(project: Path) -> None:
    manifests.write_requirements(_answers(environment_manager="venv+pip"), project)
    runtime = (project / "requirements.txt").read_text(encoding="utf-8")
    dev = (project / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "fastapi>=0.115" in runtime
    assert "pytest>=8.2" in dev
    assert "pytest" not in runtime
    # The dev file pulls the runtime one in, so one install is enough.
    assert "-r requirements.txt" in dev


def test_requirements_include_the_selected_extras(project: Path) -> None:
    manifests.write_requirements(
        _answers(environment_manager="venv+pip", pdf_parser="docling"), project
    )
    runtime = (project / "requirements.txt").read_text(encoding="utf-8")
    assert "docling>=2.15" in runtime


def test_requirements_omit_extras_that_were_not_selected(project: Path) -> None:
    manifests.write_requirements(
        _answers(
            environment_manager="venv+pip",
            embedding_provider="local-hash",
            pdf_parser="pypdf",
            reranker="none",
        ),
        project,
    )
    runtime = (project / "requirements.txt").read_text(encoding="utf-8")
    assert "docling" not in runtime
    assert "sentence-transformers" not in runtime


def test_requirements_include_expected_default_provider_extras(project: Path) -> None:
    answers = _answers(environment_manager="venv+pip")
    assert answers.extras == ["modelscope-embedding", "openai"]

    manifests.write_requirements(answers, project)
    runtime = (project / "requirements.txt").read_text(encoding="utf-8")
    assert "sentence-transformers>=3.0" in runtime
    assert "openai>=1.40" in runtime


def test_pixi_lint_task_matches_what_pruning_left_behind(project: Path) -> None:
    """`ruff check` exits non-zero on a missing path, so these must agree."""
    manifests.write_pixi(_answers(environment_manager="pixi", include_demo_corpus="No"), project)
    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert 'lint = "ruff check src tests scripts"' in text

    kept = project / "kept"
    kept.mkdir()
    shutil.copy(REPO_ROOT / "pyproject.toml", kept / "pyproject.toml")
    manifests.write_pixi(_answers(environment_manager="pixi", include_demo_corpus="Yes"), kept)
    assert 'lint = "ruff check src tests examples scripts"' in (kept / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_pixi_has_no_setup_task(project: Path) -> None:
    """For pixi, `setup` is `pixi install`; a task by that name would confuse."""
    manifests.write_pixi(_answers(environment_manager="pixi"), project)
    assert 'setup = "' not in (project / "pyproject.toml").read_text(encoding="utf-8")


# --- the standalone pixi manifest has to resolve -----------------------------
#
# #215, found underneath F-010. The standalone `pixi.toml` declared
# `default = { features = ["dev"], ... }` and defined no such feature:
#
#   Error: The feature 'dev' is not defined in the manifest, at line 21 of
#   pixi.toml, where the default environment names it.
#
# The embedded shape works because pixi reads pyproject.toml as its own
# manifest and maps [dependency-groups] dev to a feature of the same name.
# A standalone pixi.toml gets no such mapping, so every feature it names has
# to be defined in it.


def _standalone(project: Path, **overrides: object) -> dict:
    import tomllib

    manifests.write_pixi(
        _answers(environment_manager="pixi", dependency_file="pixi.toml", **overrides), project
    )
    return tomllib.loads((project / "pixi.toml").read_text(encoding="utf-8"))


def _embedded(project: Path, **overrides: object) -> dict:
    import tomllib

    manifests.write_pixi(
        _answers(environment_manager="pixi", dependency_file="pyproject.toml", **overrides), project
    )
    return tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pixi"]


def test_every_feature_the_standalone_manifest_names_is_defined_in_it(project: Path) -> None:
    """The exact failure: a named feature with nowhere to look it up."""
    parsed = _standalone(project)

    referenced = {
        feature
        for environment in parsed.get("environments", {}).values()
        for feature in environment.get("features", [])
    }
    defined = set(parsed.get("feature", {}))

    assert referenced <= defined, (
        f"pixi.toml names features it does not define: {sorted(referenced - defined)}"
    )


def test_the_standalone_dev_feature_carries_the_dev_dependencies(project: Path) -> None:
    parsed = _standalone(project)

    dev = parsed["feature"]["dev"]["pypi-dependencies"]
    assert any(name == "pytest" for name in dev), dev
    assert any(name == "mypy" for name in dev), dev


def test_the_standalone_dev_feature_does_not_drift_from_pyproject(project: Path) -> None:
    """pixi cannot reference a PEP 735 group from a standalone manifest, so the
    list is written twice. This is what stops the two disagreeing."""
    declared = manifests.read_dependencies(project).dev
    parsed = _standalone(project)

    names = set(parsed["feature"]["dev"]["pypi-dependencies"])
    expected = {
        requirement.split(">=")[0].split("[")[0].split("==")[0].strip() for requirement in declared
    }

    assert names == expected, "pixi.toml dev feature differs from [dependency-groups] dev"


def test_a_selected_extra_becomes_a_defined_feature(project: Path) -> None:
    parsed = _standalone(project, reranker="local_cross_encoder")

    referenced = set(parsed["environments"]["default"]["features"])
    assert referenced - {"dev"}, "the extra was not carried into the environment"
    assert (referenced - {"dev"}) <= set(parsed["feature"])


def test_the_embedded_shape_still_defines_no_features_of_its_own(project: Path) -> None:
    """pixi maps them for free there, and writing them twice would be worse."""
    parsed = _embedded(project)
    answers = _answers(environment_manager="pixi")

    assert "feature" not in parsed
    assert answers.extras == ["modelscope-embedding", "openai"]
    assert parsed["environments"]["default"]["features"] == ["dev", *answers.extras]
