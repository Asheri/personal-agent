"""What a builder is allowed to see.

`docker build .` and `gcloud builds submit .` both hand a directory to a
builder. A checkout is not that directory: it also holds credentials under
`.cloudsql/`, agent working files under `.context/`, a filled in `.env`, a
local PostgreSQL cluster under `.pgdata/`, Terraform state that contains a
generated database password, and whatever corpus was last ingested under
`data/raw/`. F-027 in the 2026-08-29 documentation route audit proved all
four classes crossed: a synthetic `COPY .` stage admitted them, and
`gcloud meta list-files-for-upload` listed `.context/sentinel.txt`.

`.dockerignore` and `.gcloudignore` answer that, and they answer it fail
closed: exclude everything, then re-admit exactly the documented build
inputs. These tests hold that shape in place. They check the manifests
rather than a live build because Docker and gcloud are not available in the
Python test job; the `docker` CI job runs the real `COPY .` proof against
Docker's own context resolution.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERIGNORE = ROOT / ".dockerignore"
GCLOUDIGNORE = ROOT / ".gcloudignore"
DOCKERFILE = ROOT / "Dockerfile"

# The exclude-everything line each manifest has to open with. Docker matches
# top-level names, gcloud uses gitignore syntax and anchors with a slash.
_EXCLUDE_ALL = {".dockerignore": "*", ".gcloudignore": "/*"}

# Local state that must never reach a builder. Every entry is a real class
# named in the audit or in .gitignore, not a hypothetical.
SENSITIVE_PATHS = (
    ".env",
    ".cloudsql/password",
    ".cloudsql/pgpass",
    ".context/sentinel.txt",
    ".pgdata/postgresql.conf",
    ".venv/pyvenv.cfg",
    "data/raw/private.pdf",
    "data/interim/staged.jsonl",
    "data/processed/chunks.jsonl",
    "eval_results/run-1/report.json",
    "infra/terraform/terraform.tfstate",
    "infra/terraform/terraform.tfvars",
    ".pytest_cache/CACHEDIR.TAG",
    ".mypy_cache/cache.db",
    ".ruff_cache/content",
    "site/index.html",
    ".git/config",
    # Bytecode sits inside the admitted directories, so it is the one class
    # the allowlist alone cannot exclude. See #196.
    "src/sci_rag/__pycache__/config.cpython-312.pyc",
    "migrations/versions/__pycache__/0001_initial.cpython-312.pyc",
    "domain/__pycache__/anything.pyc",
    "src/sci_rag/__pycache__",
)

# What the image documents as its runtime inputs.
RUNTIME_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "alembic.ini",
    "src/sci_rag/__init__.py",
    "domain/domain.yaml",
    "migrations/env.py",
)


def _patterns(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _manifest(path: Path) -> tuple[str, list[str], list[str]]:
    """Split a manifest into exclude-all, allowlist, and re-excluded names.

    Both files have the same three-part shape: one line that excludes
    everything, a block of `!` re-admissions, and a short trailing block that
    takes bytecode back out because it lives inside the admitted directories.
    """
    lines = _patterns(path)
    assert lines, f"{path.name} has no patterns"
    allowed = [line.lstrip("!").strip("/") for line in lines[1:] if line.startswith("!")]
    reexcluded = [line for line in lines[1:] if not line.startswith("!")]
    return lines[0], allowed, reexcluded


def _reexcludes(patterns: list[str], candidate: str) -> bool:
    """Whether a trailing re-exclusion matches any segment of ``candidate``.

    Docker spells these `**/__pycache__` and gitignore spells them
    `__pycache__/`, and both mean "at any depth", so the comparison is done
    on the bare name.
    """
    for pattern in patterns:
        bare = pattern.removeprefix("**/").rstrip("/")
        if any(fnmatch(segment, bare) for segment in candidate.split("/")):
            return True
    return False


def _admits(path: Path, candidate: str) -> bool:
    """Whether ``candidate``, a repository-relative path, survives the manifest.

    Admission is decided by the first path segment, because the allowlist
    re-admits whole top-level entries by name. The trailing block then takes
    a few names back out at any depth. The form test below is what keeps
    that simplification true.
    """
    _, allowed, reexcluded = _manifest(path)
    if candidate.split("/", 1)[0] not in allowed:
        return False
    return not _reexcludes(reexcluded, candidate)


@pytest.mark.parametrize("manifest", [DOCKERIGNORE, GCLOUDIGNORE], ids=lambda p: p.name)
def test_the_manifest_exists(manifest: Path) -> None:
    """Without the file, gcloud falls back to .gitignore and Docker to nothing."""
    assert manifest.is_file(), f"{manifest.name} is missing, so the build context is unbounded"


@pytest.mark.parametrize("manifest", [DOCKERIGNORE, GCLOUDIGNORE], ids=lambda p: p.name)
def test_the_manifest_is_an_allowlist_not_a_denylist(manifest: Path) -> None:
    """A denylist fails open. This is the shape the whole fix depends on."""
    first, allowed, reexcluded = _manifest(manifest)
    assert first == _EXCLUDE_ALL[manifest.name], (
        f"{manifest.name} must open by excluding everything, found {first!r}"
    )
    assert allowed, f"{manifest.name} admits nothing, so no build could succeed"

    rest = _patterns(manifest)[1:]
    admissions_end = len(rest) - len(reexcluded)
    assert all(line.startswith("!") for line in rest[:admissions_end]), (
        f"{manifest.name} interleaves exclusions with its allowlist: {rest}"
    )
    unnamed = [
        line
        for line in reexcluded
        if line.removeprefix("**/").rstrip("/") not in {"__pycache__", "*.pyc", "*.pyo"}
    ]
    assert unnamed == [], (
        f"{manifest.name} re-excludes something other than bytecode, which turns the "
        f"allowlist back into a denylist: {unnamed}"
    )


@pytest.mark.parametrize("manifest", [DOCKERIGNORE, GCLOUDIGNORE], ids=lambda p: p.name)
@pytest.mark.parametrize("sensitive", SENSITIVE_PATHS)
def test_local_state_never_reaches_a_builder(manifest: Path, sensitive: str) -> None:
    assert not _admits(manifest, sensitive), (
        f"{manifest.name} admits {sensitive} into the build context"
    )


@pytest.mark.parametrize("manifest", [DOCKERIGNORE, GCLOUDIGNORE], ids=lambda p: p.name)
@pytest.mark.parametrize("runtime_input", RUNTIME_INPUTS)
def test_the_documented_runtime_inputs_still_reach_the_builder(
    manifest: Path, runtime_input: str
) -> None:
    """Fail closed is only correct if the image still builds."""
    assert _admits(manifest, runtime_input), (
        f"{manifest.name} excludes {runtime_input}, which the image needs"
    )


def _dockerfile_context_sources() -> list[str]:
    """The paths the Dockerfile copies out of the build context.

    ``COPY --from=<stage>`` reads from an earlier stage rather than from the
    context, so it is not a context source.
    """
    sources: list[str] = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("COPY "):
            continue
        parts = stripped.split()[1:]
        if any(part.startswith("--from=") for part in parts):
            continue
        parts = [part for part in parts if not part.startswith("--")]
        sources.extend(parts[:-1])
    return sources


def test_every_dockerfile_copy_source_is_admitted() -> None:
    """A COPY of an excluded path builds a quietly incomplete image.

    This is the test that catches the next person who adds a COPY without
    adding its source to the manifests.
    """
    sources = _dockerfile_context_sources()
    assert sources, "no context COPY sources found; the Dockerfile parse is wrong"
    for manifest in (DOCKERIGNORE, GCLOUDIGNORE):
        missing = [source for source in sources if not _admits(manifest, source)]
        assert missing == [], f"{manifest.name} excludes Dockerfile COPY sources: {missing}"


def test_both_manifests_admit_exactly_the_same_set() -> None:
    """A local build and a Cloud Build submission must see the same directory.

    If they diverge, an image that builds on a laptop can fail in Cloud Build
    for a reason nobody can see from either file alone.
    """
    _, docker_allowed, _ = _manifest(DOCKERIGNORE)
    _, gcloud_allowed, _ = _manifest(GCLOUDIGNORE)
    assert sorted(docker_allowed) == sorted(gcloud_allowed)


def test_the_build_definition_is_uploaded_with_the_source() -> None:
    """`gcloud builds submit` has to upload the Dockerfile or the build has none.

    `.dockerignore` admits the same two files for symmetry, though Docker
    itself never copies either one into an image: it excludes them from
    every `COPY` regardless of what the manifest says.
    """
    for manifest in (DOCKERIGNORE, GCLOUDIGNORE):
        assert _admits(manifest, "Dockerfile")
        assert _admits(manifest, ".dockerignore")


def test_the_deployment_guide_warns_about_admitted_paths() -> None:
    """A reader putting a private corpus in src/ deserves to be told."""
    guide = (ROOT / "docs" / "deploy-gcp.md").read_text(encoding="utf-8")
    assert ".gcloudignore" in guide
    assert ".dockerignore" in guide
    assert re.search(r"upload|build context", guide, re.IGNORECASE)


def test_source_next_to_excluded_bytecode_is_still_admitted() -> None:
    """Re-excluding bytecode must not take its neighbours with it."""
    for manifest in (DOCKERIGNORE, GCLOUDIGNORE):
        assert _admits(manifest, "src/sci_rag/config.py")
        assert _admits(manifest, "migrations/versions/0001_initial.py")
        assert _admits(manifest, "domain/domain.yaml")
