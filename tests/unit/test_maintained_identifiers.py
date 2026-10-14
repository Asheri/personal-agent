"""No tracked file may name infrastructure somebody else maintains.

F-019 found the Terraform module shipping the maintainer's Google Cloud
project and the live shared instance as defaults, and #171 removed them there.
The same two strings were still in `scripts/cloud_postgres.py`, which this
template also ships and a generated project can retain. That helper has `pause`
and `resume` verbs, and ADR 0009 says plainly that they affect every workspace
using the instance, so a default there aimed a lifecycle change at somebody
else's database.

A downstream reader's credentials would refuse, so the blast radius was
smaller than the Terraform case. The rule is the same either way: a public
template does not name another organization's project as the thing its verbs
act on, and it does not disclose an internal project id at all.

This guard is repository-wide, which is what the Terraform-scoped version in
`test_dev_database_terraform.py` grew into. Everything is in scope, including
planning notes: the disclosure does not care whether a file gives
instructions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]

# Real infrastructure somebody else maintains. No tracked file may contain
# these, and no test may assert their presence.
MAINTAINED_IDENTIFIERS = ("pisces-476117", "sci-rag-dev")

# This file has to name them to forbid them.
EXEMPT = frozenset({Path(__file__).relative_to(REPO_ROOT).as_posix()})


def _tracked_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        REPO_ROOT / name
        for name in listed.stdout.decode().split("\0")
        if name and name not in EXEMPT
    ]


@pytest.mark.parametrize("identifier", MAINTAINED_IDENTIFIERS)
def test_no_tracked_file_names_maintained_infrastructure(identifier: str) -> None:
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _tracked_files()
        if identifier in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], f"{identifier} appears in tracked files: {offenders}"
