#!/usr/bin/env python3
"""Print the CHANGELOG section for one released version.

The release workflow uses this to give a GitHub Release the notes that already
exist, rather than a generated commit list. The changelog is written for people
and the release page is read by people, so the same prose serves both.

Why a script with tests rather than `sed` inside the workflow: this runs once
per release, after the package is already on PyPI and the version number is
spent. A quoting mistake in unattended YAML would be found at exactly the
moment nothing can be re-cut. The parsing is small, but it is worth being able
to run it.

It fails rather than guessing. An empty release page is recoverable by hand; a
release page confidently showing the wrong version's notes is not obviously
wrong to anyone reading it.

    $ python scripts/changelog_release_notes.py --version 0.5.0
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# `## [0.5.0] - 2026-09-03`, and tolerant of a missing date. The literal
# `[Unreleased]` heading uses the same shape, so callers ask for a version and
# never match it by accident.
_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?:\s*-\s*(?P<date>\S+))?\s*$")


class NotesNotFound(Exception):
    """The changelog has no usable section for the requested version."""


def _headings(text: str) -> list[tuple[int, str]]:
    """Line index and version for every version heading, in file order."""
    found = []
    for index, line in enumerate(text.splitlines()):
        match = _HEADING.match(line)
        if match:
            found.append((index, match.group("version")))
    return found


def release_notes(text: str, version: str) -> str:
    """The body under `## [version]`, up to the next version heading.

    The heading itself is dropped. A GitHub Release already shows its tag, so
    repeating `## [0.5.0]` inside the body renders a redundant title.
    """
    lines = text.splitlines()
    headings = _headings(text)

    for position, (line_index, heading_version) in enumerate(headings):
        if heading_version != version:
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = "\n".join(lines[line_index + 1 : end]).strip()
        if not body:
            raise NotesNotFound(
                f"the [{version}] section of the changelog is empty; "
                "a release page with no notes is worse than no release page"
            )
        return body + "\n"

    known = ", ".join(v for _, v in headings) or "none"
    raise NotesNotFound(
        f"the changelog has no [{version}] section. Sections present: {known}. "
        "Move the Unreleased entries under a version heading before tagging."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        required=True,
        help="the released version, without a leading v (for example 0.5.0)",
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=DEFAULT_CHANGELOG,
        help="path to the changelog (defaults to the repository's own)",
    )
    args = parser.parse_args(argv)

    version = args.version.removeprefix("v")

    try:
        notes = release_notes(args.changelog.read_text(encoding="utf-8"), version)
    except FileNotFoundError:
        print(f"error: no changelog at {args.changelog}", file=sys.stderr)
        return 2
    except NotesNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
