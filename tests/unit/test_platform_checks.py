"""Contracts for helpers shared by platform-sensitive unit tests."""

from __future__ import annotations

import pytest
from platform_checks import posix_shell


def test_missing_windows_posix_shell_skips_with_a_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import shutil
    from pathlib import Path

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(Path, "is_file", lambda _path: False)

    with pytest.raises(pytest.skip.Exception, match="Git for Windows"):
        posix_shell("sh")
