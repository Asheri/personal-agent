"""Contracts for helpers shared by platform-sensitive unit tests."""

from __future__ import annotations

import os

import pytest
from platform_checks import posix_shell


@pytest.mark.skipif(
    os.name != "nt",
    reason="the helper builds a WindowsPath once os.name is patched to nt, and "
    "pathlib refuses to construct one on a POSIX host",
)
def test_missing_windows_posix_shell_skips_with_a_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil
    from pathlib import Path

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(Path, "is_file", lambda _path: False)

    with pytest.raises(pytest.skip.Exception, match="Git for Windows"):
        posix_shell("sh")
