"""The backup runbook, executed rather than read.

F-006 in the 2026-08-29 documentation route audit: the local backup procedure
ran `pg_dump "$SCI_RAG_DATABASE_URL_SYNC"`, but no setting, environment
example, helper, or earlier instruction ever defines that name. In a normal
shell it expanded to an empty first argument; under `bash -u` it aborted
before `pg_dump` could run.

A backup procedure is only correct if it runs, so these tests run it. The
documented commands are extracted from the page, a stub `pg_dump` on `PATH`
records what it was actually handed, and the assertions are about that
recording. Nothing here opens a socket or contacts a database.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from platform_checks import posix_shell

ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ROOT / "docs" / "operations.md"

LOCAL_BACKUP_HEADING = "### Local or self-hosted Postgres"

# What a workspace .env looks like. The password lives in a passfile, which is
# what the Cloud SQL helper writes, so a correct procedure never has to put one
# on a command line.
FIXTURE_ENV = (
    "# sci-rag-kit configuration\n"
    "SCI_RAG_DATABASE_URL=postgresql+asyncpg://sci_rag@127.0.0.1:55070/sci_rag_demo"
    "?passfile=%2Ftmp%2Fpgpass\n"
    "SCI_RAG_EMBEDDING_PROVIDER=local-hash\n"
)

STUB_PG_DUMP = '#!/bin/sh\nprintf "ARG1=[%s]\\n" "$1"\n'


def _section(heading: str) -> str:
    text = OPERATIONS.read_text(encoding="utf-8")
    after = text.partition(heading)[2]
    assert after, f"{OPERATIONS.name} no longer has the section {heading!r}"
    return after.partition("\n### ")[0].partition("\n## ")[0]


def _first_bash_block(section: str) -> str:
    match = re.search(r"^```bash\n(.*?)^```", section, re.DOTALL | re.MULTILINE)
    assert match, "the section no longer contains a bash block"
    return match.group(1)


def _run(script: str, workdir: Path, *, shell: str = "sh") -> subprocess.CompletedProcess[str]:
    """Run a documented snippet with a stub pg_dump ahead of any real one."""
    stub_dir = workdir / "stub-bin"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "pg_dump"
    stub.write_text(STUB_PG_DUMP, encoding="utf-8")
    stub.chmod(0o755)

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SCI_RAG_DATABASE_URL")
    }
    shell_path, shell_dir = posix_shell(shell)
    path_entries = [str(stub_dir)]
    if shell_dir is not None:
        path_entries.append(str(shell_dir))
    environment["PATH"] = os.pathsep.join([*path_entries, environment.get("PATH", "")]).rstrip(
        os.pathsep
    )
    return subprocess.run(
        [shell_path, "-c", script],
        cwd=workdir,
        env=environment,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text(FIXTURE_ENV, encoding="utf-8")
    return tmp_path


def _recorded_argument(result: subprocess.CompletedProcess[str]) -> str:
    match = re.search(r"ARG1=\[(.*)\]", result.stdout)
    assert match, f"pg_dump was never reached. stdout={result.stdout!r} stderr={result.stderr!r}"
    return match.group(1)


def test_the_documented_backup_hands_pg_dump_a_real_connection_string(project: Path) -> None:
    script = _first_bash_block(_section(LOCAL_BACKUP_HEADING))
    result = _run(script, project)

    argument = _recorded_argument(result)
    assert argument, "pg_dump received an empty first argument"
    assert argument.startswith("postgresql://"), (
        f"pg_dump needs a libpq connection string, got {argument!r}"
    )
    assert "+asyncpg" not in argument, "libpq does not understand the asyncpg driver marker"


def test_the_documented_backup_survives_unset_variable_checking(project: Path) -> None:
    """`bash -u` is a normal thing for a careful operator to have on."""
    script = _first_bash_block(_section(LOCAL_BACKUP_HEADING))
    result = _run("set -u\n" + script, project, shell="bash")

    assert "unbound variable" not in result.stderr, result.stderr
    assert _recorded_argument(result), "pg_dump received an empty first argument under set -u"


def test_the_procedure_keeps_the_password_off_the_command_line(project: Path) -> None:
    """A connection string that carries a passfile never has to carry a secret."""
    script = _first_bash_block(_section(LOCAL_BACKUP_HEADING))
    argument = _recorded_argument(_run(script, project))

    assert "passfile" in argument, "the derived URL dropped the passfile reference"
    # A libpq URL with a password looks like scheme://user:password@host.
    assert not re.match(r"^postgresql://[^/@]*:[^/@]*@", argument), (
        f"the procedure put a password on the command line: {argument!r}"
    )


def test_every_name_the_procedure_uses_is_defined_before_it_is_used() -> None:
    """The defect was a name nothing in the repository ever sets."""
    script = _first_bash_block(_section(LOCAL_BACKUP_HEADING))
    used = set(re.findall(r'"\$\{?([A-Z_][A-Z0-9_]*)\}?"', script))
    assigned = set(re.findall(r"^([A-Z_][A-Z0-9_]*)=", script, re.MULTILINE))

    undefined = sorted(used - assigned)
    assert undefined == [], (
        f"the backup snippet reads {undefined} without defining them, and nothing "
        "in the repository exports them"
    )


# --- where the dump lands ----------------------------------------------------
#
# F-008: the runbook wrote a whole-database dump into the repository root with
# a predictable name, and nothing ignored it. A private corpus backup showed up
# as an ordinary untracked project file, one `git add .` from being committed.

RESTORE_HEADING = "## Restore drill"


def _documented_dump_paths(section: str) -> list[str]:
    """Every .dump path the section names, with shell expansions collapsed."""
    block = _first_bash_block(section)
    paths = re.findall(r'"([^"]*\.dump)"', block)
    # `sci-rag-$(date +%Y%m%d).dump` is a real filename once a date exists.
    return [path.replace("$(date +%Y%m%d)", "20991231") for path in paths]


def test_the_documented_backup_destination_is_ignored_before_pg_dump_runs() -> None:
    paths = _documented_dump_paths(_section(LOCAL_BACKUP_HEADING))
    assert paths, "the backup snippet no longer names a .dump file"

    for path in paths:
        ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True)
        assert ignored.returncode == 0, (
            f"{path} is not ignored, so a whole-database dump lands in the "
            "repository as an ordinary untracked file"
        )


def test_the_restore_drill_reads_from_the_documented_backup_directory() -> None:
    """Two halves of one runbook must not name different places."""
    backup = _documented_dump_paths(_section(LOCAL_BACKUP_HEADING))
    restore = _documented_dump_paths(_section(RESTORE_HEADING))
    assert restore, "the restore drill no longer names a .dump file"

    backup_dirs = {path.rpartition("/")[0] for path in backup}
    restore_dirs = {path.rpartition("/")[0] for path in restore}
    assert backup_dirs == restore_dirs, (
        f"backup writes to {backup_dirs} and restore reads from {restore_dirs}"
    )
    assert backup_dirs != {""}, "the destination is still the current directory"


def test_the_backup_directory_exists_in_a_fresh_checkout() -> None:
    """A destination that only appears after a mkdir is a step nobody documented."""
    directory = next(
        iter(
            {
                path.rpartition("/")[0]
                for path in _documented_dump_paths(_section(LOCAL_BACKUP_HEADING))
            }
        )
    )
    assert (ROOT / directory).is_dir(), f"{directory}/ is missing from the repository"
    keep = ROOT / directory / ".gitkeep"
    assert keep.is_file(), f"{directory}/.gitkeep keeps the destination in a fresh checkout"


def test_the_runbook_says_what_a_dump_contains() -> None:
    """A reader deciding where to put this file needs to know what is in it."""
    section = _section(LOCAL_BACKUP_HEADING)
    lowered = section.lower()
    assert "private" in lowered or "every source" in lowered
    assert "encrypt" in lowered


# --- the archive format the reader is actually given -------------------------
#
# F-009: the snippet labelled its output a plain-format dump while passing
# --format=custom, and the restore drill used pg_restore, which reads custom
# archives and not plain SQL. Three signals, two of them agreeing and one of
# them wrong, is worse than none: a reader who believes the label reaches for
# psql and gets an unreadable file.

# What each pg_dump format is restored with. Plain output is SQL you replay.
RESTORE_TOOL_FOR_FORMAT = {"custom": "pg_restore", "directory": "pg_restore", "plain": "psql"}

FORMAT_WORDS = {"custom": "custom-format", "directory": "directory-format", "plain": "plain-format"}


def _selected_format() -> str:
    block = _first_bash_block(_section(LOCAL_BACKUP_HEADING))
    match = re.search(r"--format=(\w+)", block)
    assert match, "the backup snippet no longer selects a pg_dump format"
    return match.group(1)


def test_the_prose_names_the_format_the_command_selects() -> None:
    selected = _selected_format()
    assert selected in FORMAT_WORDS, f"unknown pg_dump format {selected!r}"

    section = _section(LOCAL_BACKUP_HEADING).lower()
    expected = FORMAT_WORDS[selected]
    assert expected in section, f"the command selects {selected} but the page never says {expected}"

    wrong = [word for name, word in FORMAT_WORDS.items() if name != selected and word in section]
    assert wrong == [], f"the page also calls it {wrong} while the command selects {selected}"


def test_the_restore_drill_uses_the_tool_that_reads_that_format() -> None:
    selected = _selected_format()
    restore = _first_bash_block(_section(RESTORE_HEADING))

    expected = RESTORE_TOOL_FOR_FORMAT[selected]
    assert expected in restore, f"a {selected}-format archive is restored with {expected}"

    wrong = [
        tool
        for form, tool in RESTORE_TOOL_FOR_FORMAT.items()
        if tool != expected and re.search(rf"\b{tool}\b", restore)
    ]
    assert wrong == [], f"the restore drill also reaches for {wrong}"
