"""Putting the template on disk before the appliers run.

`sci-rag-new` starts in a parent directory with nothing checked out, so it has
to bring the template down first. It fetches the real repository at the tag
matching its own installed version, which is what makes a given generator
release always produce the same project.

There is no git binary requirement and no template rendering: this downloads a
tarball with httpx, which is already a direct dependency, and extracts it.
What comes out is the runnable repository, byte for byte. The appliers then
rewrite its configuration in place (see ADR 0004).

The offline `--template-path` route copies from a checkout instead. A checkout
holds more than a template does, so the copy boundary is what the repository
tracks rather than what the working tree happens to contain (see ADR 0010).
"""

from __future__ import annotations

import fnmatch
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    import httpx

TEMPLATE_REPO = "sustainability-software-lab/sci-rag-kit"

# The dot-prefixed entries the template genuinely ships. Everything else that
# starts with a dot is local state: credentials, agent scratch, caches, a
# virtualenv, a database cluster. See ADR 0010.
_TEMPLATE_DOT_ENTRIES = frozenset(
    {
        ".devcontainer",
        ".dockerignore",
        ".env.example",
        ".gcloudignore",
        ".github",
        ".gitignore",
        ".gitkeep",
        ".pre-commit-config.yaml",
        ".python-version",
        ".terraform.lock.hcl",
    }
)

# Build output and caches that carry no dot and so need naming.
_NEVER_COPIED_NAMES = frozenset(
    {
        "__pycache__",
        "build",
        "dist",
        "eval_results",
        "htmlcov",
        "node_modules",
        "site",
    }
)

_NEVER_COPIED_GLOBS = ("*.pyc", "*.pyo", "*.egg-info", "*.tfstate", "*.tfstate.*")

# Directories whose contents are the user's corpus or evaluation output. Only
# the placeholder that keeps the directory in the tree may cross.
_PLACEHOLDER_ONLY_DIRS = frozenset(
    {
        Path("data") / "raw",
        Path("data") / "interim",
        Path("data") / "processed",
        Path("data") / "demo" / "downloads",
    }
)


class TemplateFetchError(RuntimeError):
    """The template could not be put in place."""


def template_ref(*, version: str | None = None) -> str:
    """The git ref this generator produces projects from.

    Pinned to the generator's own version so that upgrading the generator is
    the only way to change what a generated project contains.
    """
    if version is None:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as installed_version

        try:
            version = installed_version("sci-rag-kit")
        except PackageNotFoundError:  # pragma: no cover - only when run from a bare tree
            raise TemplateFetchError(
                "sci-rag-kit is not installed, so its version cannot be resolved. "
                "Pass --ref to name a tag, or --template-path to use a local checkout."
            ) from None
    return f"v{version}"


def tarball_url(ref: str, *, repo: str = TEMPLATE_REPO) -> str:
    """codeload serves tags and branches from different paths."""
    kind = "tags" if ref.startswith("v") else "heads"
    return f"https://codeload.github.com/{repo}/tar.gz/refs/{kind}/{ref}"


def _require_empty(target: Path) -> None:
    if target.exists() and any(target.iterdir()):
        raise TemplateFetchError(
            f"{target} is not empty. Choose a different project name, or move the "
            "existing directory out of the way."
        )


def _tracked_paths(source: Path) -> list[str] | None:
    """The repository-tracked files under ``source``, or None if git cannot say.

    A checkout is not the same thing as a distributable template. It also
    holds credentials, agent state, caches, and whatever corpus the user
    ingested last week. Asking git which paths are tracked draws the boundary
    from the repository itself rather than from a list of names somebody
    remembered to write down, and it is the same content the download route
    already produces. See ADR 0010.
    """
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=source,
            capture_output=True,
            check=False,
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull},
        )
    except OSError:
        # No git binary. The offline route still has to work.
        return None
    if listed.returncode != 0:
        return None
    return [name for name in listed.stdout.decode("utf-8", "surrogateescape").split("\0") if name]


def _copy_tracked(source: Path, target: Path, tracked: list[str]) -> None:
    """Copy exactly the named paths, preserving mode and symlinks."""
    for name in tracked:
        origin = source / name
        # A tracked path can be missing mid-edit, and a submodule gitlink is a
        # directory rather than a file. Neither is a reason to refuse to
        # generate, and neither can leak anything.
        if not origin.is_symlink() and not origin.is_file():
            continue
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination, follow_symlinks=False)


def _is_local_state(relative_dir: Path, name: str) -> bool:
    """True when this entry belongs to the template author and not to the template."""
    if name.startswith(".") and name not in _TEMPLATE_DOT_ENTRIES:
        return True
    if name in _NEVER_COPIED_NAMES:
        return True
    if any(fnmatch.fnmatch(name, pattern) for pattern in _NEVER_COPIED_GLOBS):
        return True
    return relative_dir in _PLACEHOLDER_ONLY_DIRS and name != ".gitkeep"


def _fallback_excludes(source: Path) -> Callable[[str, list[str]], set[str]]:
    """A fail-closed copy rule for a template directory git knows nothing about.

    An exported tarball or a hand-assembled directory has no tracking
    information to read, so the rule inverts: nothing hidden crosses unless
    the template genuinely ships it, and the corpus directories keep only
    their placeholder.
    """
    root = source.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        try:
            relative = Path(directory).resolve().relative_to(root)
        except ValueError:  # pragma: no cover - copytree never leaves the tree
            relative = Path(".")
        return {name for name in names if _is_local_state(relative, name)}

    return ignore


def _copy_local(source: Path, target: Path) -> str:
    if not source.is_dir():
        raise TemplateFetchError(f"No template checkout at {source}.")

    tracked = _tracked_paths(source)
    if tracked is not None:
        if not tracked:
            raise TemplateFetchError(
                f"{source} is a git repository with no tracked files, so there is no "
                "template to copy. Commit the template first, or point --template-path "
                "at a checkout that has content."
            )
        target.mkdir(parents=True, exist_ok=True)
        _copy_tracked(source, target, tracked)
        return f"local checkout at {source} (tracked content only)"

    shutil.copytree(source, target, ignore=_fallback_excludes(source), dirs_exist_ok=True)
    return f"local directory at {source}"


def _extract(archive_bytes: bytes, target: Path) -> None:
    """Extract the archive, stripping GitHub's top-level directory.

    ``filter="data"`` refuses absolute paths, parent traversal, links out of
    the tree, and device files. Extracting a downloaded archive without it is
    how a hostile tag writes outside the target directory.
    """
    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / "staged"
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
                archive.extractall(staged, filter="data")
        except (tarfile.TarError, OSError, ValueError) as exc:
            raise TemplateFetchError(f"The downloaded archive could not be read: {exc}") from exc

        roots = [path for path in staged.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise TemplateFetchError(
                f"Expected one top-level directory in the archive, found {len(roots)}."
            )
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(roots[0], target, dirs_exist_ok=True)


def fetch_template(
    target: Path,
    *,
    ref: str | None = None,
    template_path: Path | None = None,
    repo: str = TEMPLATE_REPO,
    client: httpx.Client | None = None,
) -> str:
    """Put the template at ``target``. Returns a description of where it came from.

    ``template_path`` uses a local checkout, which is what the tests and any
    offline user need. Otherwise the tarball comes from GitHub at ``ref``,
    defaulting to the tag matching this generator's version.
    """
    _require_empty(target)

    if template_path is not None:
        return _copy_local(template_path.expanduser(), target)

    resolved = ref or template_ref()
    url = tarball_url(resolved, repo=repo)

    import httpx as _httpx

    owned = client is None
    http = client or _httpx.Client(follow_redirects=True, timeout=60.0)
    try:
        response = http.get(url)
        if response.status_code == 404:
            # A 404 here has two very different causes and codeload cannot
            # tell them apart: the tag does not exist, or the repository is
            # not readable anonymously. The second one looks like a broken
            # generator to every user who is not a collaborator, so name it.
            raise TemplateFetchError(
                f"Could not fetch the template at {resolved} ({url}). Either that tag "
                f"does not exist, or {repo} is not publicly readable. Pass --ref to "
                "name another tag, or --template-path to generate from a local checkout."
            )
        response.raise_for_status()
        payload = response.content
    except _httpx.HTTPError as exc:
        raise TemplateFetchError(f"Could not download {url}: {exc}") from exc
    finally:
        if owned:
            http.close()

    _extract(payload, target)
    return f"{repo} at {resolved}"
