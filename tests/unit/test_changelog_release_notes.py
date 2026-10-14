"""The release page's notes come from the changelog, so the parse has to hold.

This runs unattended, once, after the package is already on PyPI and the
version number is spent. There is no second attempt at that point, so the
failure modes below are the interesting part: an absent section, an empty one,
and the `[Unreleased]` heading, which shares the shape of a version heading and
must never be published as if it were a release.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import pytest
from scripts.changelog_release_notes import NotesNotFound, main, release_notes

CHANGELOG = """\
# Changelog

Notable changes to the kit.

## [Unreleased]

### Changed

- Something still cooking.

## [0.5.0] - 2026-09-03

A release with a lede.

### Fixed

- A thing that was broken.

## [0.4.1] - 2026-08-31

### Fixed

- An earlier thing.

## [0.3.0a1] - 2026-08-28

- A prerelease.
"""


def test_it_returns_only_the_requested_version() -> None:
    notes = release_notes(CHANGELOG, "0.5.0")

    assert "A release with a lede." in notes
    assert "A thing that was broken." in notes
    assert "An earlier thing." not in notes, "the next version's section leaked in"
    assert "Something still cooking." not in notes, "the Unreleased section leaked in"


def test_the_heading_itself_is_dropped() -> None:
    """A GitHub Release already displays its tag above the body."""
    assert "## [0.5.0]" not in release_notes(CHANGELOG, "0.5.0")


def test_the_last_section_runs_to_the_end_of_the_file() -> None:
    """Nothing follows it, so an off-by-one here would return nothing."""
    assert "A prerelease." in release_notes(CHANGELOG, "0.3.0a1")


def test_a_middle_section_stops_at_the_next_heading() -> None:
    notes = release_notes(CHANGELOG, "0.4.1")

    assert "An earlier thing." in notes
    assert "A prerelease." not in notes


def test_asking_for_unreleased_by_name_is_still_refused_as_a_version() -> None:
    """`Unreleased` parses as a heading, so it has to be unreachable by tag.

    A tag is always a version, so this can only happen if someone passes the
    literal string. Publishing in-progress notes as a release is the failure
    this guards, and it is silent: the page looks plausible.
    """
    with pytest.raises(NotesNotFound):
        release_notes(CHANGELOG, "0.9.9")


def test_a_missing_version_names_what_is_present() -> None:
    """The operator is mid-release; the error has to say what to do."""
    with pytest.raises(NotesNotFound) as caught:
        release_notes(CHANGELOG, "9.9.9")

    message = str(caught.value)
    assert "0.5.0" in message, "the error should list the sections it did find"
    assert "Unreleased" in message


def test_an_empty_section_fails_rather_than_publishing_nothing() -> None:
    empty = "# Changelog\n\n## [1.0.0] - 2026-01-01\n\n## [0.9.0] - 2025-12-01\n\n- Old.\n"

    with pytest.raises(NotesNotFound, match="empty"):
        release_notes(empty, "1.0.0")


def test_a_heading_without_a_date_still_parses() -> None:
    """Keep a Changelog allows it, and a release should not fail on style."""
    assert "Undated." in release_notes("## [2.0.0]\n\n- Undated.\n", "2.0.0")


def test_the_cli_prints_the_section(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")

    assert main(["--version", "0.5.0", "--changelog", str(path)]) == 0
    assert "A release with a lede." in capsys.readouterr().out


def test_the_cli_accepts_a_tag_shaped_version(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    """The workflow has a tag in hand; making it strip the v is one more step."""
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")

    assert main(["--version", "v0.5.0", "--changelog", str(path)]) == 0
    assert "A release with a lede." in capsys.readouterr().out


def test_the_cli_fails_loudly_on_a_missing_section(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")

    assert main(["--version", "9.9.9", "--changelog", str(path)]) == 1
    assert "no [9.9.9] section" in capsys.readouterr().err


def test_the_cli_fails_on_a_missing_file(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--version", "0.5.0", "--changelog", str(tmp_path / "nope.md")]) == 2
    assert "no changelog" in capsys.readouterr().err


def test_every_released_version_in_this_repository_has_notes() -> None:
    """The parser and the real changelog have to agree, not just the fixture.

    The repository's own file is the one the workflow will read.
    """
    text = (Path(__file__).parents[2] / "CHANGELOG.md").read_text(encoding="utf-8")

    for version in ("0.5.0", "0.4.1", "0.4.0", "0.3.0"):
        assert release_notes(text, version).strip(), f"[{version}] produced no notes"


def test_every_released_section_opens_with_a_lede() -> None:
    """The release page shows this paragraph directly under the tag.

    Six of the seven released sections already did this; 0.5.0 shipped without
    one because it was cut straight from `## [Unreleased]`, which accumulates
    entries and has no summary to inherit. Its release page opened on a bare
    `### Added`, so the first thing a reader saw was a category rather than
    what the release was for.

    `[Unreleased]` is exempt on purpose. The lede is written when the release
    is cut, which is the moment its headline is finally known.
    """
    text = (Path(__file__).parents[2] / "CHANGELOG.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if (match := re.match(r"^## \[([^\]]+)\]", line))
    ]

    missing = []
    for position, (line_index, version) in enumerate(headings):
        if version == "Unreleased":
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = [line for line in lines[line_index + 1 : end] if line.strip()]
        if not body or body[0].startswith(("###", "-", "*")):
            missing.append(version)

    assert missing == [], (
        "these released sections open on a category or a bullet rather than a "
        f"sentence saying what the release is for: {missing}"
    )
