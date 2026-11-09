"""The credential guard: it must catch a real key and allow a fixture.

A scanner that never fires is worse than none, because it is quoted as
protection. These tests drive both directions with strings that are built at
test time, so this file is not itself a finding.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_no_secrets.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_no_secrets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_long_openai_style_key_is_flagged(tmp_path: Path) -> None:
    module = _module()
    key = "sk-" + "a1b2c3d4" * 6
    path = _write(tmp_path, "config.py", f'KEY = "{key}"\n')

    problems = module.findings([path])

    assert len(problems) == 1
    assert "openai-style key" in problems[0]
    assert key not in problems[0], "the finding must not echo the secret"


def test_the_short_test_fixture_is_allowed(tmp_path: Path) -> None:
    module = _module()
    path = _write(tmp_path, "test_doctor_offline.py", 'api_key = "sk-topsecret1234567890"\n')

    assert module.findings([path]) == []


def test_a_committed_dotenv_is_flagged_by_name(tmp_path: Path) -> None:
    module = _module()
    path = _write(tmp_path, ".env", "SCI_RAG_OPENAI_API_KEY=anything\n")

    problems = module.findings([path])

    assert problems and "never be committed" in problems[0]


def test_an_explicit_allow_comment_passes(tmp_path: Path) -> None:
    module = _module()
    key = "ghp_" + "b" * 36
    path = _write(tmp_path, "notes.md", f"token {key}  # allow-secret: documentation example\n")

    assert module.findings([path]) == []


@pytest.mark.parametrize(
    "body, label",
    [
        ("aws = 'AKIAIOSFODNN7EXAMPLE'\n", "aws access key"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\n", "private key block"),
        ("cookie: SESSDATA=abcdef1234567890abcdef;\n", "bilibili session"),
    ],
)
def test_other_provider_shapes_are_flagged(tmp_path: Path, body: str, label: str) -> None:
    module = _module()

    problems = module.findings([_write(tmp_path, "leak.txt", body)])

    assert problems and label in problems[0]


def test_binary_and_lockfile_paths_are_skipped(tmp_path: Path) -> None:
    module = _module()
    lock = _write(tmp_path, "uv.lock", 'KEY = "sk-' + "c" * 40 + '"\n')

    assert module.findings([lock]) == []
