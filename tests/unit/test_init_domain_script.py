"""scripts/init_domain.py, exercised as a real subprocess on a throwaway copy."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]


def _make_copy(tmp_path: Path) -> Path:
    copy = tmp_path / "repo"
    (copy / "scripts").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "scripts" / "init_domain.py", copy / "scripts" / "init_domain.py")
    shutil.copy(REPO_ROOT / "pyproject.toml", copy / "pyproject.toml")
    shutil.copytree(REPO_ROOT / "domain", copy / "domain")
    return copy


def _run(copy: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/init_domain.py", *args],
        cwd=copy,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    copy = _make_copy(tmp_path)
    before = (copy / "domain" / "domain.yaml").read_text(encoding="utf-8")
    result = _run(copy, "--name", "Battery KB", "--description", "Battery materials")
    assert result.returncode == 0, result.stderr
    assert "Dry run" in result.stdout
    assert (copy / "domain" / "domain.yaml").read_text(encoding="utf-8") == before


def test_apply_rebrands_and_resets_seeds(tmp_path: Path) -> None:
    copy = _make_copy(tmp_path)
    result = _run(copy, "--name", "Battery KB", "--description", "Battery materials", "--apply")
    assert result.returncode == 0, result.stderr

    assert 'name = "battery-kb"' in (copy / "pyproject.toml").read_text(encoding="utf-8")
    domain_yaml = (copy / "domain" / "domain.yaml").read_text(encoding="utf-8")
    assert 'name: "Battery KB"' in domain_yaml
    assert "Battery materials" in domain_yaml
    seeds = (copy / "domain" / "eval_seed_questions.jsonl").read_text(encoding="utf-8")
    assert seeds.startswith("# Ground-truth questions")
    assert "rice straw" not in seeds

    # Running again reports nothing left to do.
    again = _run(copy, "--name", "Battery KB", "--description", "Battery materials", "--apply")
    assert again.returncode == 0
    assert "Nothing to change" in again.stdout
