"""Contracts for dependency updates that cross supported runtime boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEPENDABOT = Path(__file__).resolve().parents[2] / ".github" / "dependabot.yml"


def test_docker_updates_keep_python_on_the_supported_minor_line() -> None:
    """Python feature releases require a coordinated compatibility change."""
    config: dict[str, Any] = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    docker_updates = [
        update for update in config["updates"] if update["package-ecosystem"] == "docker"
    ]

    assert len(docker_updates) == 1
    python_ignores = [
        rule for rule in docker_updates[0].get("ignore", []) if rule["dependency-name"] == "python"
    ]

    assert len(python_ignores) == 1
    assert set(python_ignores[0]["update-types"]) == {
        "version-update:semver-minor",
        "version-update:semver-major",
    }
