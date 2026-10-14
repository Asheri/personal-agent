"""RunnerProfile is the single place an environment manager's strings live.

The wizard renders task commands, CI, the container, and the docs from one
profile. If any other module learns a manager's name, the five surfaces can
disagree and the generated project breaks on first run.
"""

from __future__ import annotations

import pytest

from sci_rag.scaffold.runners import detect_environment_manager, get_runner, runner_keys


def test_uv_profile_is_registered() -> None:
    assert "uv" in runner_keys()


def test_uv_profile_matches_the_repository_as_it_ships() -> None:
    uv = get_runner("uv")
    assert uv.run_prefix == "uv run"
    assert uv.sync_command == "uv sync"
    assert uv.manifest == "pyproject.toml"
    assert uv.lockfile == "uv.lock"
    assert uv.ci_setup_action == "astral-sh/setup-uv@v7"


def test_run_joins_the_prefix_to_a_command() -> None:
    assert get_runner("uv").run("sci-rag doctor") == "uv run sci-rag doctor"


def test_run_with_an_empty_prefix_leaves_no_leading_space() -> None:
    """venv+pip has no prefix; the seam must not emit ' sci-rag doctor'."""
    from sci_rag.scaffold.runners import RunnerProfile

    bare = RunnerProfile(
        key="bare",
        label="bare",
        run_prefix="",
        sync_command="pip install -e .",
        manifest="requirements.txt",
        lockfile=None,
        ci_setup_action="actions/setup-python@v5",
    )
    assert bare.run("sci-rag doctor") == "sci-rag doctor"


def test_unknown_runner_is_rejected_by_name() -> None:
    with pytest.raises(KeyError, match="poetry"):
        get_runner("poetry")


def test_environment_detection_prefers_profiles_in_runner_order(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    installed = {"pixi", "micromamba"}
    monkeypatch.setattr(
        "sci_rag.scaffold.runners.shutil.which",
        lambda executable: f"/bin/{executable}" if executable in installed else None,
    )

    assert detect_environment_manager() == "pixi"
