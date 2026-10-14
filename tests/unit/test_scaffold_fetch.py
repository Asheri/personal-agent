"""Getting the template onto disk before the appliers run.

`sci-rag-new` starts in a parent directory with nothing checked out, so it has
to fetch the real repository at a pinned tag. Everything here runs offline: the
network path is exercised against a stub transport rather than GitHub.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import tarfile
from pathlib import Path

import httpx
import pytest

from sci_rag.scaffold.fetch import (
    TemplateFetchError,
    fetch_template,
    tarball_url,
    template_ref,
)


def _tarball(*, top: str = "sci-rag-kit-0.2.0") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, body in (
            ("pyproject.toml", b'[project]\nname = "sci-rag-kit"\n'),
            ("domain/domain.yaml", b'name: "Demo"\n'),
        ):
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def _client(payload: bytes, *, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- ref and url ------------------------------------------------------------


def test_the_default_ref_is_the_installed_version() -> None:
    assert template_ref(version="0.2.0") == "v0.2.0"


def test_the_installed_version_is_used_when_none_is_given() -> None:
    """A given generator release always produces the same project."""
    assert template_ref().startswith("v")


def test_the_url_points_at_the_tag() -> None:
    assert tarball_url("v0.2.0").endswith("/tar.gz/refs/tags/v0.2.0")


def test_a_branch_ref_resolves_to_a_head_url() -> None:
    assert tarball_url("main").endswith("/tar.gz/refs/heads/main")


# --- local checkout ---------------------------------------------------------


def test_a_local_checkout_is_copied(tmp_path: Path) -> None:
    source = tmp_path / "checkout"
    (source / "domain").mkdir(parents=True)
    (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (source / "domain" / "domain.yaml").write_text("name: x\n", encoding="utf-8")
    target = tmp_path / "new-project"

    described = fetch_template(target, template_path=source)

    assert (target / "pyproject.toml").exists()
    assert (target / "domain" / "domain.yaml").exists()
    assert str(source) in described


def test_a_local_checkout_copy_leaves_out_git_and_build_state(tmp_path: Path) -> None:
    source = tmp_path / "checkout"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    target = tmp_path / "new-project"

    fetch_template(target, template_path=source)

    assert not (target / ".git").exists()
    assert not (target / ".venv").exists()


def test_a_missing_local_checkout_is_reported(tmp_path: Path) -> None:
    with pytest.raises(TemplateFetchError, match="nowhere"):
        fetch_template(tmp_path / "out", template_path=tmp_path / "nowhere")


# --- the local copy boundary ------------------------------------------------
#
# F-001 in the 2026-08-29 documentation route audit: a local checkout holds
# credentials, agent state, caches, and a private corpus, and every one of them
# used to cross into the generated project. The boundary is now what the
# repository tracks, so the tests below seed the sensitive classes explicitly
# and assert absence rather than trusting a list of remembered names.


def _git(source: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=source,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        },
    )


def _checkout_with_ignored_state(tmp_path: Path) -> Path:
    """A tracked template that also holds every class of ignored local state."""
    source = tmp_path / "checkout"
    (source / "domain").mkdir(parents=True)
    (source / "src" / "sci_rag").mkdir(parents=True)
    (source / "data" / "raw").mkdir(parents=True)
    (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (source / "domain" / "domain.yaml").write_text("name: x\n", encoding="utf-8")
    (source / "src" / "sci_rag" / "__init__.py").write_text("", encoding="utf-8")
    (source / "data" / "raw" / ".gitkeep").write_text("", encoding="utf-8")
    (source / ".env.example").write_text("SCI_RAG_DATABASE_URL=\n", encoding="utf-8")
    (source / ".gitignore").write_text(
        ".env\n.cloudsql/\ndata/raw/*\n!data/raw/.gitkeep\n.venv/\n",
        encoding="utf-8",
    )

    _git(source, "init", "--quiet", "--initial-branch=main")
    _git(source, "add", "--all")
    _git(source, "commit", "--quiet", "--message", "template")

    # Ignored local state, created after the commit so none of it is tracked.
    (source / ".cloudsql").mkdir()
    (source / ".cloudsql" / "password").write_text("synthetic-not-a-secret\n", encoding="utf-8")
    (source / ".cloudsql" / "pgpass").write_text("synthetic-not-a-secret\n", encoding="utf-8")
    (source / ".context").mkdir()
    (source / ".context" / "sentinel.txt").write_text("agent state\n", encoding="utf-8")
    (source / ".env").write_text("SCI_RAG_DATABASE_URL=postgresql://x\n", encoding="utf-8")
    (source / "data" / "raw" / "private.pdf").write_text("private corpus\n", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (source / "untracked-scratch.md").write_text("scratch\n", encoding="utf-8")
    return source


def test_a_local_checkout_leaves_every_class_of_ignored_state_behind(tmp_path: Path) -> None:
    """The generated project carries distributable content and nothing else."""
    source = _checkout_with_ignored_state(tmp_path)
    target = tmp_path / "new-project"

    fetch_template(target, template_path=source)

    for leaked in (
        ".cloudsql/password",
        ".cloudsql/pgpass",
        ".context/sentinel.txt",
        ".env",
        "data/raw/private.pdf",
        ".venv/pyvenv.cfg",
        "untracked-scratch.md",
    ):
        assert not (target / leaked).exists(), f"{leaked} crossed the template boundary"


def test_a_local_checkout_still_carries_the_tracked_template(tmp_path: Path) -> None:
    """Closing the boundary must not empty the generated project."""
    source = _checkout_with_ignored_state(tmp_path)
    target = tmp_path / "new-project"

    fetch_template(target, template_path=source)

    for kept in (
        "pyproject.toml",
        "domain/domain.yaml",
        "src/sci_rag/__init__.py",
        ".env.example",
        ".gitignore",
        "data/raw/.gitkeep",
    ):
        assert (target / kept).exists(), f"{kept} should have been generated"


def test_a_tracked_file_is_copied_from_the_working_tree_not_from_the_commit(
    tmp_path: Path,
) -> None:
    """Generating from a checkout means generating what is on disk right now."""
    source = _checkout_with_ignored_state(tmp_path)
    (source / "domain" / "domain.yaml").write_text("name: edited\n", encoding="utf-8")
    target = tmp_path / "new-project"

    fetch_template(target, template_path=source)

    assert (target / "domain" / "domain.yaml").read_text(encoding="utf-8") == "name: edited\n"


def test_an_executable_bit_survives_the_copy(tmp_path: Path) -> None:
    source = _checkout_with_ignored_state(tmp_path)
    script = source / "scripts" / "run.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    script.chmod(0o755)
    _git(source, "add", "--all")
    _git(source, "commit", "--quiet", "--message", "script")
    target = tmp_path / "new-project"

    fetch_template(target, template_path=source)

    assert os.access(target / "scripts" / "run.sh", os.X_OK)


def test_a_deleted_but_still_tracked_file_does_not_break_generation(tmp_path: Path) -> None:
    """A checkout mid-edit still generates, minus the file that is not there."""
    source = _checkout_with_ignored_state(tmp_path)
    (source / "domain" / "domain.yaml").unlink()
    target = tmp_path / "new-project"

    fetch_template(target, template_path=source)

    assert (target / "pyproject.toml").exists()
    assert not (target / "domain" / "domain.yaml").exists()


def test_a_plain_directory_template_still_refuses_sensitive_local_state(tmp_path: Path) -> None:
    """The offline route allows a directory that is not a checkout.

    Without git there is no ignore list to read, so the fallback is fail
    closed: nothing hidden crosses unless the template genuinely ships it.
    """
    source = tmp_path / "exported"
    (source / "domain").mkdir(parents=True)
    (source / ".cloudsql").mkdir()
    (source / ".context").mkdir()
    (source / "data" / "raw").mkdir(parents=True)
    (source / ".github" / "workflows").mkdir(parents=True)
    (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (source / "domain" / "domain.yaml").write_text("name: x\n", encoding="utf-8")
    (source / ".env.example").write_text("SCI_RAG_DATABASE_URL=\n", encoding="utf-8")
    (source / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (source / "data" / "raw" / ".gitkeep").write_text("", encoding="utf-8")
    (source / ".cloudsql" / "password").write_text("synthetic\n", encoding="utf-8")
    (source / ".context" / "sentinel.txt").write_text("agent state\n", encoding="utf-8")
    (source / ".env").write_text("SCI_RAG_DATABASE_URL=postgresql://x\n", encoding="utf-8")
    (source / "data" / "raw" / "private.pdf").write_text("private corpus\n", encoding="utf-8")
    target = tmp_path / "new-project"

    fetch_template(target, template_path=source)

    assert not (target / ".cloudsql").exists()
    assert not (target / ".context").exists()
    assert not (target / ".env").exists()
    assert not (target / "data" / "raw" / "private.pdf").exists()
    assert (target / "pyproject.toml").exists()
    assert (target / "domain" / "domain.yaml").exists()
    assert (target / ".env.example").exists()
    assert (target / ".github" / "workflows" / "ci.yml").exists()
    assert (target / "data" / "raw" / ".gitkeep").exists()


def test_the_description_names_the_boundary_that_was_used(tmp_path: Path) -> None:
    """A user who generated from a checkout should be able to tell which rule ran."""
    tracked = _checkout_with_ignored_state(tmp_path)
    plain = tmp_path / "exported"
    plain.mkdir()
    (plain / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    from_checkout = fetch_template(tmp_path / "a", template_path=tracked)
    from_plain = fetch_template(tmp_path / "b", template_path=plain)

    assert "tracked" in from_checkout
    assert "tracked" not in from_plain


# --- network ----------------------------------------------------------------


def test_the_tarball_is_extracted_with_its_top_level_directory_stripped(tmp_path: Path) -> None:
    target = tmp_path / "new-project"

    fetch_template(target, ref="v0.2.0", client=_client(_tarball()))

    assert (target / "pyproject.toml").exists()
    assert (target / "domain" / "domain.yaml").exists()
    assert not (target / "sci-rag-kit-0.2.0").exists()


def test_a_404_names_both_causes(tmp_path: Path) -> None:
    """codeload returns 404 for a missing tag and for a private repository.

    The second one looks like a broken generator to every user who is not a
    collaborator, so the message has to name it.
    """
    with pytest.raises(TemplateFetchError, match=re.escape("v9.9.9")) as caught:
        fetch_template(tmp_path / "out", ref="v9.9.9", client=_client(b"", status=404))
    message = str(caught.value)
    assert "does not exist" in message
    assert "publicly readable" in message


def test_a_corrupt_tarball_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TemplateFetchError, match="archive"):
        fetch_template(tmp_path / "out", ref="v0.2.0", client=_client(b"not a tarball"))


def test_a_path_traversing_member_is_refused(tmp_path: Path) -> None:
    """Model the hostile-archive case explicitly rather than trusting the default."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("sci-rag-kit-0.2.0/../../escaped.txt")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bad"))
    with pytest.raises(TemplateFetchError):
        fetch_template(tmp_path / "out", ref="v0.2.0", client=_client(buffer.getvalue()))
    assert not (tmp_path / "escaped.txt").exists()


# --- target directory -------------------------------------------------------


def test_a_non_empty_target_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "new-project"
    target.mkdir()
    (target / "something.txt").write_text("mine\n", encoding="utf-8")

    with pytest.raises(TemplateFetchError, match="not empty"):
        fetch_template(target, ref="v0.2.0", client=_client(_tarball()))

    assert (target / "something.txt").read_text(encoding="utf-8") == "mine\n"


def test_an_empty_target_directory_is_fine(tmp_path: Path) -> None:
    target = tmp_path / "new-project"
    target.mkdir()
    fetch_template(target, ref="v0.2.0", client=_client(_tarball()))
    assert (target / "pyproject.toml").exists()
