"""Canonical paths are identities; content hashes are not identities."""

from pathlib import Path

import pytest

from sci_rag.versions import canonical_source_path, identity_key_for


def test_relative_and_absolute_paths_share_one_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert identity_key_for(Path("notes.txt")) == identity_key_for(tmp_path / "notes.txt")
    assert canonical_source_path(tmp_path / "folder" / ".." / "notes.txt") == canonical_source_path(
        tmp_path / "notes.txt"
    )


def test_paths_and_members_are_independent_identity_components(tmp_path: Path) -> None:
    path = tmp_path / "mail.mbox"
    assert identity_key_for(path, "one") != identity_key_for(path, "two")
    assert identity_key_for(path) != identity_key_for(tmp_path / "copy.mbox")


def test_non_string_member_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stable string"):
        identity_key_for(tmp_path / "mail.mbox", None)  # type: ignore[arg-type]
