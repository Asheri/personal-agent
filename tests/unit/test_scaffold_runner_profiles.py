"""Every environment manager the wizard offers, as a profile.

The five uv-wired surfaces (task commands, CI, container, dev container,
docs) are rendered from one profile each, so these tests pin the profile
itself. The cross-surface check that nothing else hardcodes a manager lives
in test_scaffold_runner_coherence.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_rag.scaffold.runners import PROFILES, get_runner, runner_keys

EXPECTED = ["uv", "pixi", "conda", "venv+pip"]


def test_the_four_supported_managers_are_registered() -> None:
    assert runner_keys() == EXPECTED


@pytest.mark.parametrize("key", EXPECTED)
def test_every_profile_can_render_every_surface(key: str) -> None:
    profile = get_runner(key)
    assert profile.run("sci-rag doctor")
    assert profile.sync()
    assert profile.ci_setup_yaml(python_version="3.12")
    assert profile.dockerfile(python_version="3.12", project_slug="demo-kb")
    assert profile.devcontainer_post_create()


@pytest.mark.parametrize("key", EXPECTED)
def test_no_profile_leaks_another_managers_name(key: str) -> None:
    """A profile that mentions a sibling would poison every surface it renders."""
    profile = get_runner(key)
    rendered = "\n".join(
        [
            profile.run("sci-rag doctor"),
            profile.sync(extras=("docling",)),
            profile.ci_setup_yaml(python_version="3.12"),
            profile.dockerfile(python_version="3.12", project_slug="demo-kb"),
            profile.devcontainer_post_create(),
            profile.tool_run("pre-commit run --all-files"),
        ]
    )
    for other in PROFILES.values():
        if other.key == key:
            continue
        for token in other.command_tokens():
            assert token not in rendered, f"{key} profile leaks {other.key}: {token}"


def test_pixi_runs_through_pixi_run() -> None:
    pixi = get_runner("pixi")
    assert pixi.run("sci-rag doctor") == "pixi run sci-rag doctor"
    assert pixi.sync() == "pixi install"
    assert pixi.lockfile == "pixi.lock"
    assert pixi.ci_setup_action == "prefix-dev/setup-pixi@v0"


def test_conda_names_the_environment_after_the_project() -> None:
    conda = get_runner("conda")
    assert conda.run("sci-rag doctor", project_slug="membrane-kb") == (
        "conda run -n membrane-kb sci-rag doctor"
    )
    assert conda.manifest == "environment.yml"
    assert conda.lockfile is None


def test_venv_pip_expects_an_activated_environment() -> None:
    venv = get_runner("venv+pip")
    assert venv.run("sci-rag doctor") == "sci-rag doctor"
    assert venv.lockfile is None
    assert "pip install" in venv.sync()


def test_extras_go_where_each_manager_expects_them() -> None:
    """docling has to actually get installed, whichever manager is chosen.

    uv resolves extras on the install command line. The other three read them
    from a manifest, so their sync command stays constant and the manifest
    writer carries the selection.
    """
    assert "docling" in get_runner("uv").sync(extras=("docling",))
    assert get_runner("pixi").sync(extras=("docling",)) == "pixi install"
    assert "docling" not in get_runner("conda").sync(extras=("docling",))
    assert "docling" not in get_runner("venv+pip").sync(extras=("docling",))
    assert "requirements-dev.txt" in get_runner("venv+pip").sync()


def test_ci_setup_yaml_is_indented_for_a_workflow_step_list() -> None:
    block = get_runner("pixi").ci_setup_yaml(python_version="3.12")
    assert block.startswith("      - uses: prefix-dev/setup-pixi@v0")


def test_no_dockerfile_pins_a_python_other_than_the_answer() -> None:
    for key in EXPECTED:
        rendered = get_runner(key).dockerfile(python_version="3.11", project_slug="demo-kb")
        assert "3.12" not in rendered, key


def test_images_carrying_the_interpreter_pin_the_answered_version() -> None:
    """pixi and conda pin Python in their manifest instead, so they are exempt."""
    for key in ("uv", "venv+pip"):
        rendered = get_runner(key).dockerfile(python_version="3.11", project_slug="demo-kb")
        assert "3.11" in rendered, key


def test_every_dockerfile_ends_at_the_same_entrypoint() -> None:
    for key in EXPECTED:
        rendered = get_runner(key).dockerfile(python_version="3.12", project_slug="demo-kb")
        assert 'CMD ["sci-rag", "serve"]' in rendered
        assert "COPY domain ./domain" in rendered


# --- the builder gets the manifest it is about to resolve --------------------
#
# F-010 in the 2026-08-29 documentation route audit: the Advanced wizard can
# put the pixi tables in a standalone `pixi.toml`, and the Dockerfile copied
# only `pyproject.toml` and `README.md` before running `pixi install`. The
# manifest that defines the workspace stayed on the host, so the generated
# container route could not resolve it.

PIXI_MANIFEST_SHAPES = ("pyproject.toml", "pixi.toml")


def _copy_targets(dockerfile: str) -> list[str]:
    """Everything COPYed into the builder stage, in order."""
    targets = []
    for line in dockerfile.splitlines():
        if line.startswith("RUN pixi install"):
            break
        if line.startswith("COPY "):
            targets.extend(line.split()[1:-1])
    return targets


@pytest.mark.parametrize("dependency_file", PIXI_MANIFEST_SHAPES)
def test_the_pixi_builder_copies_the_selected_manifest(dependency_file: str) -> None:
    rendered = get_runner("pixi").dockerfile(
        python_version="3.12", project_slug="demo-kb", dependency_file=dependency_file
    )

    copied = _copy_targets(rendered)
    assert dependency_file in copied, (
        f"pixi install resolves {dependency_file}, which the builder never receives: {copied}"
    )
    assert "pyproject.toml" in copied, "the dependency lists live in pyproject.toml either way"


@pytest.mark.parametrize("dependency_file", PIXI_MANIFEST_SHAPES)
def test_manifests_are_copied_before_source_so_the_layer_caches(
    dependency_file: str,
) -> None:
    rendered = get_runner("pixi").dockerfile(
        python_version="3.12", project_slug="demo-kb", dependency_file=dependency_file
    )
    copied = _copy_targets(rendered)

    assert copied.index(dependency_file) < copied.index("src"), (
        "a source edit would invalidate the dependency layer"
    )


def test_the_embedded_shape_does_not_copy_a_file_that_does_not_exist() -> None:
    """An embedded project has no pixi.toml, and COPY of a missing path fails."""
    rendered = get_runner("pixi").dockerfile(
        python_version="3.12", project_slug="demo-kb", dependency_file="pyproject.toml"
    )

    assert "pixi.toml" not in _copy_targets(rendered)


@pytest.mark.parametrize("key", EXPECTED)
def test_every_manager_still_renders_without_naming_a_manifest(key: str) -> None:
    """The argument is pixi-specific; nothing else may start depending on it."""
    assert get_runner(key).dockerfile(python_version="3.12", project_slug="demo-kb")


def test_container_ci_builds_both_pixi_manifest_shapes() -> None:
    """The unit tests above check the rendered text. Only a build proves it."""
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "generated-projects.yml"
    ).read_text(encoding="utf-8")

    assert "Both pixi manifest shapes build their builder stage" in workflow
    assert "for shape in pyproject.toml pixi.toml" in workflow
    assert "docker build --target builder" in workflow
