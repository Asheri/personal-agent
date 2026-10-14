"""Generate a project per environment manager and look for a sibling's commands.

This is the cheap test that catches the whole class of "the five uv-wired
surfaces disagree" bugs. A pixi project that still says `uv run` in its
Makefile, workflow, Dockerfile, README, or docs is broken on its first run,
and the failure shows up in the user's terminal rather than here unless
something asserts it.

It runs against a real copy of the template, not a fixture, so a new surface
added to the repository is covered the moment it is listed in
``apply.COHERENCE_SURFACES``.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from sci_rag.scaffold import apply
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.questions import default_answers
from sci_rag.scaffold.runners import PROFILES, get_runner, runner_keys

REPO_ROOT = Path(__file__).parents[2]
SLUG = "membrane-materials-kb"

# Everything an applier reads or rewrites. Copied rather than symlinked so a
# generation cannot touch the working tree.
_COPY_FILES = (
    "pyproject.toml",
    "Makefile",
    "Dockerfile",
    ".env.example",
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "uv.lock",
    ".python-version",
    ".dockerignore",
    ".gcloudignore",
)
_COPY_TREES = ("domain", "docs", "scripts", ".github", ".devcontainer", "src", "infra")


def _template(tmp_path: Path) -> Path:
    root = tmp_path / "template"
    root.mkdir(parents=True)
    for name in _COPY_FILES:
        shutil.copy(REPO_ROOT / name, root / name)
    for tree in _COPY_TREES:
        ignored = (
            shutil.ignore_patterns("__pycache__", "full-stack-development", "superpowers")
            if tree == "docs"
            else shutil.ignore_patterns("__pycache__")
        )
        shutil.copytree(REPO_ROOT / tree, root / tree, ignore=ignored)
    for workspace in ("full-stack-development", "superpowers"):
        sentinel = root / "docs" / workspace / "sentinel.md"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("# agent workspace\n", encoding="utf-8")
    (root / "data" / "demo").mkdir(parents=True)
    (root / "data" / "demo" / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "examples").mkdir()
    (root / "examples" / "library_quickstart.py").write_text("# example\n", encoding="utf-8")
    return root


def _generate(tmp_path: Path, manager: str, **overrides: str) -> Path:
    root = _template(tmp_path)
    raw = dict(default_answers())
    raw.update(
        {
            "project_name": "Membrane Materials KB",
            "repo_name": SLUG,
            "environment_manager": manager,
            "initialize_git": "No",
        }
    )
    raw.update(overrides)
    apply.apply_all(ProjectAnswers.from_raw(raw), root, year=2026)
    return root


@pytest.mark.parametrize("manager", runner_keys())
def test_no_other_managers_commands_survive(tmp_path: Path, manager: str) -> None:
    root = _generate(tmp_path, manager)
    chosen = get_runner(manager)
    siblings = [profile for profile in PROFILES.values() if profile.key != manager]

    offenders: list[str] = []
    for path in apply.coherence_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for sibling in siblings:
            for token in sibling.command_tokens():
                # A token another manager also legitimately uses is not
                # evidence of a leak (venv+pip and uv both build venvs).
                if token in chosen.command_tokens():
                    continue
                if token in text:
                    offenders.append(f"{path.relative_to(root)}: {sibling.key} token {token!r}")

    assert not offenders, "\n".join(sorted(set(offenders)))


@pytest.mark.parametrize("manager", runner_keys())
def test_the_chosen_manager_actually_reaches_the_five_surfaces(
    tmp_path: Path, manager: str
) -> None:
    root = _generate(tmp_path, manager)
    profile = get_runner(manager)

    makefile = (root / "Makefile").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    devcontainer = json.loads(
        (root / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
    )
    quickstart = (root / "docs" / "quickstart.md").read_text(encoding="utf-8")

    assert profile.sync() in makefile
    assert profile.ci_setup_action in workflow
    assert profile.sync() in workflow
    prefix = profile.run("", project_slug=SLUG)
    if prefix:
        assert prefix in makefile
        assert prefix in quickstart
    if profile.devcontainer_feature:
        assert profile.devcontainer_feature in devcontainer["features"]
    assert profile.sync() in devcontainer["postCreateCommand"]
    # The Dockerfile is rendered whole from the profile rather than patched.
    assert dockerfile == profile.dockerfile(python_version="3.12", project_slug=SLUG)


@pytest.mark.parametrize("manager", runner_keys())
def test_only_the_chosen_managers_lockfile_is_present(tmp_path: Path, manager: str) -> None:
    root = _generate(tmp_path, manager)
    profile = get_runner(manager)
    for other in PROFILES.values():
        if other.lockfile and other.lockfile != profile.lockfile:
            assert not (root / other.lockfile).exists(), other.lockfile


@pytest.mark.parametrize("manager", runner_keys())
def test_the_chosen_managers_manifest_exists(tmp_path: Path, manager: str) -> None:
    root = _generate(tmp_path, manager)
    assert (root / get_runner(manager).manifest).exists()


def test_generated_workflows_are_valid_yaml(tmp_path: Path) -> None:
    """A rewritten setup block that broke indentation would fail here first."""
    import yaml

    for manager in runner_keys():
        root = _generate(tmp_path / manager, manager)
        for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
            parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
            assert parsed["jobs"], f"{manager}: {workflow.name}"


@pytest.mark.parametrize("manager", runner_keys())
def test_the_kits_own_workflows_do_not_ship(tmp_path: Path, manager: str) -> None:
    """One generates projects; the other publishes under the kit's own name."""
    from sci_rag.scaffold.apply import KIT_ONLY_WORKFLOWS

    root = _generate(tmp_path, manager)
    for workflow in KIT_ONLY_WORKFLOWS:
        assert not (root / ".github" / "workflows" / workflow).exists(), workflow
    # The ones a project does want are still there.
    assert (root / ".github" / "workflows" / "ci.yml").exists()


@pytest.mark.parametrize("manager", runner_keys())
def test_the_kits_planning_documents_do_not_ship(tmp_path: Path, manager: str) -> None:
    """They are the template's development history, and they name every manager."""
    root = _generate(tmp_path, manager)
    assert not (root / "docs" / "planning").exists()
    assert not (root / "docs" / "full-stack-development").exists()
    assert not (root / "docs" / "superpowers").exists()
    assert not (root / "docs" / "aegis").exists()


@pytest.mark.parametrize("manager", runner_keys())
@pytest.mark.parametrize(
    ("include_cloud_database", "include_terraform"),
    (("No", "No"), ("No", "Yes"), ("Yes", "No"), ("Yes", "Yes")),
)
def test_generated_docs_only_name_retained_cloud_assets(
    tmp_path: Path,
    manager: str,
    include_cloud_database: str,
    include_terraform: str,
) -> None:
    root = _generate(
        tmp_path,
        manager,
        include_cloud_database=include_cloud_database,
        include_terraform=include_terraform,
    )
    docs = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((root / "docs").rglob("*.md"))
    )
    helper = root / "scripts" / "cloud_postgres.py"
    module = root / "infra" / "terraform" / "dev-database"
    profile = get_runner(manager)

    assert "BEGIN GENERATED PROJECT FEATURE" not in docs
    assert "END GENERATED PROJECT FEATURE" not in docs
    assert "/Users/" not in docs
    assert "tylerhuntington" not in docs.casefold()

    if include_cloud_database == "Yes":
        assert helper.exists()
        command = profile.run("python scripts/cloud_postgres.py", project_slug=SLUG)
        assert command in docs
        assert "Use Cloud SQL in Conductor workspaces" in docs
    else:
        assert not helper.exists()
        assert "scripts/cloud_postgres.py" not in docs
        assert "SCI_RAG_CLOUD_PG_" not in docs
        assert "Use Cloud SQL in Conductor workspaces" not in docs

    if include_cloud_database == "Yes" and include_terraform == "Yes":
        assert module.exists()
        assert "infra/terraform/dev-database" in docs
    else:
        assert not module.exists()
        assert "infra/terraform/dev-database" not in docs


# --- every pin says the same Python ------------------------------------------
#
# F-011 in the 2026-08-29 documentation route audit: selecting 3.11 updated the
# package metadata, the CI matrix, and both Docker stages, and left
# `.python-version` at 3.12. Three pins agreed with the answer and one did not,
# which is worse than none agreeing: a reader who trusts pyenv or `uv python`
# gets a different interpreter from the one their CI and their image use.
#
# The point of reading every pin in one test is that the next pin somebody adds
# is covered by naming it here, rather than by remembering to write another
# test for it.

SUPPORTED_PYTHON = ("3.11", "3.12")


def _generated_python_pins(root: Path) -> dict[str, str]:
    """Every place a generated project states which Python it runs on."""
    pins: dict[str, str] = {}

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    pins["pyproject requires-python"] = re.search(
        r'(?m)^requires-python = ">=([0-9.]+)"$', pyproject
    ).group(1)

    pins[".python-version"] = (root / ".python-version").read_text(encoding="utf-8").strip()

    pins["pyproject mypy"] = re.search(r'(?m)^python_version = "([0-9.]+)"$', pyproject).group(1)

    # pixi pins its interpreter in pyproject; the pixi and conda base images
    # take theirs from the manifest, so their Dockerfile names no Python.
    pixi = re.search(r'(?m)^python = "([0-9.]+)\.\*"$', pyproject)
    if pixi:
        pins["pyproject pixi"] = pixi.group(1)

    environment = root / "environment.yml"
    if environment.exists():
        conda = re.search(r"python=([0-9.]+)", environment.read_text(encoding="utf-8"))
        if conda:
            pins["environment.yml"] = conda.group(1)

    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    docker_versions = set(re.findall(r"python:?3\.(\d+)", dockerfile))
    if docker_versions:
        assert len(docker_versions) == 1, f"Dockerfile names several Pythons: {docker_versions}"
        pins["Dockerfile"] = f"3.{docker_versions.pop()}"

    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pins["ci matrix"] = re.search(r'python-version: \["([0-9.]+)"\]', workflow).group(1)

    return pins


@pytest.mark.parametrize("python_version", SUPPORTED_PYTHON)
@pytest.mark.parametrize("manager", runner_keys())
def test_every_generated_python_pin_matches_the_selected_version(
    tmp_path: Path, manager: str, python_version: str
) -> None:
    root = _generate(tmp_path, manager, python_version=python_version)

    pins = _generated_python_pins(root)
    disagreeing = {where: pin for where, pin in pins.items() if pin != python_version}

    assert disagreeing == {}, f"selected Python {python_version}, but {disagreeing} says otherwise"


@pytest.mark.parametrize("python_version", SUPPORTED_PYTHON)
@pytest.mark.parametrize("manager", runner_keys())
def test_the_pins_agree_with_each_other(tmp_path: Path, manager: str, python_version: str) -> None:
    """Stated separately from the answer: a uniformly wrong set is still wrong."""
    pins = _generated_python_pins(_generate(tmp_path, manager, python_version=python_version))

    assert len(set(pins.values())) == 1, pins


@pytest.mark.parametrize("manager", runner_keys())
def test_the_pin_set_is_not_quietly_empty(tmp_path: Path, manager: str) -> None:
    """A reader of the test above should know it is checking something."""
    pins = _generated_python_pins(_generate(tmp_path, manager, python_version="3.12"))

    assert len(pins) >= 4, pins
    assert ".python-version" in pins
    assert "pyproject requires-python" in pins


# --- no unresolved scaffold placeholder survives generation ------------------
#
# F-014 in the 2026-08-29 documentation route audit. ADR 0004 refuses template
# placeholders, and the documentation claimed a test proved a generated project
# contains no bare double brace anywhere. A real generated project contains
# seven, four of which are the claim describing itself, one is valid BibTeX,
# and one is a deliberate illustration of the syntax ADR 0004 refuses.
#
# The guard that was supposed to prove it lived in test_scaffold_apply.py and
# ran against a five-file fixture with nothing under docs/, so it could not
# have seen any of them. The invariant was not merely misstated, it was
# untested against anything capable of violating it.
#
# The real invariant is about unresolved placeholders, not about a character
# pair. Contexts are accepted by content rather than by path, so a genuine leak
# cannot hide in a file that happens to be on an allowlist.

PLACEHOLDER = re.compile(r"\{\{")
PLACEHOLDER_SUFFIXES = {".md", ".toml", ".yaml", ".yml", ".jsonl", ".json", ".txt"}

ACCEPTED_PLACEHOLDER_CONTEXTS = (
    (
        re.compile(r"\$\{\{"),
        "a GitHub Actions expression, which is real workflow syntax",
    ),
    (
        re.compile(r"^\s*\w+\s*=\s*\{\{.*\}\},?\s*$"),
        "BibTeX brace protection, which stops a renderer lowercasing a name",
    ),
    (
        re.compile(r"\{\{\s*cookiecutter\."),
        "a named illustration of the syntax ADR 0004 refuses",
    ),
)


def _unresolved_placeholders(root: Path) -> list[str]:
    """Placeholder-looking tokens that no accepted context explains."""
    offenders = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in PLACEHOLDER_SUFFIXES:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if not PLACEHOLDER.search(line):
                continue
            if any(pattern.search(line) for pattern, _ in ACCEPTED_PLACEHOLDER_CONTEXTS):
                continue
            offenders.append(f"{path.relative_to(root)}:{number}: {line.strip()[:90]}")
    return offenders


@pytest.mark.parametrize("manager", runner_keys())
def test_a_generated_project_carries_no_unresolved_placeholder(
    tmp_path: Path, manager: str
) -> None:
    root = _generate(tmp_path, manager)

    offenders = _unresolved_placeholders(root)

    assert offenders == [], "unresolved placeholders in a generated project:\n" + "\n".join(
        offenders
    )


def test_the_guard_still_catches_a_leaked_placeholder(tmp_path: Path) -> None:
    """An allowlist that explains everything proves nothing."""
    root = _generate(tmp_path, "uv")
    (root / "docs" / "leaked.md").write_text(
        "# Leaked\n\nname: {{ project_name }}\n", encoding="utf-8"
    )

    offenders = _unresolved_placeholders(root)

    assert any("leaked.md" in offender for offender in offenders), offenders


@pytest.mark.parametrize(
    "pattern,reason", ACCEPTED_PLACEHOLDER_CONTEXTS, ids=lambda value: str(value)[:20]
)
def test_every_accepted_context_still_occurs(tmp_path: Path, pattern: object, reason: str) -> None:
    """An exception nothing uses any more is an exception nobody is checking."""
    root = _generate(tmp_path, "uv")

    found = any(
        pattern.search(line)  # type: ignore[attr-defined]
        for path in root.rglob("*")
        if path.is_file() and path.suffix in PLACEHOLDER_SUFFIXES
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
    )

    assert found, f"nothing in a generated project still needs this exception: {reason}"


# --- a generated project can build its own Dockerfile ------------------------
#
# #179 gave the kit a fail-closed .dockerignore: exclude everything, re-admit
# the build inputs. Those inputs are uv's. A generated project keeps the
# manifest, so pixi, conda, and venv+pip inherited an allowlist that excludes
# the very manifest their own Dockerfile copies:
#
#   pixi      COPY pyproject.toml pixi.toml README.md ./   pixi.toml excluded
#   conda     COPY environment.yml README.md ./            environment.yml excluded
#   venv+pip  COPY requirements.txt pyproject.toml ...     requirements.txt excluded
#
# CI found the pixi case while building both manifest shapes for #162. The
# other two were never built anywhere, so nothing would have said so.


def _dockerignore_allowlist(root: Path) -> list[str]:
    return [
        line.strip().lstrip("!").strip("/")
        for line in (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("!")
    ]


def _dockerfile_context_sources(root: Path) -> list[str]:
    sources = []
    for line in (root / "Dockerfile").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("COPY ") or "--from=" in stripped:
            continue
        sources.extend(part for part in stripped.split()[1:-1] if not part.startswith("--"))
    return sources


def test_a_standalone_pixi_manifest_reaches_the_build_context(tmp_path: Path) -> None:
    """The shape CI caught: pixi.toml is copied and was excluded. See #162."""
    root = _generate(tmp_path, "pixi", dependency_file="pixi.toml")

    assert "pixi.toml" in _dockerfile_context_sources(root)
    assert "pixi.toml" in _dockerignore_allowlist(root)


@pytest.mark.parametrize("manager", runner_keys())
def test_a_generated_project_admits_every_source_its_dockerfile_copies(
    tmp_path: Path, manager: str
) -> None:
    root = _generate(tmp_path, manager)

    allowed = _dockerignore_allowlist(root)
    missing = [
        source
        for source in _dockerfile_context_sources(root)
        if source.split("/", 1)[0] not in allowed
    ]

    assert missing == [], (
        f"the {manager} Dockerfile copies {missing}, which its own .dockerignore excludes"
    )


@pytest.mark.parametrize("manager", runner_keys())
def test_a_generated_project_still_keeps_local_state_out_of_its_build(
    tmp_path: Path, manager: str
) -> None:
    """Rewriting the allowlist must not reopen what #179 closed."""
    root = _generate(tmp_path, manager)
    allowed = _dockerignore_allowlist(root)

    for local in (".env", ".cloudsql", ".context", "data", "infra", ".venv"):
        assert local not in allowed, f"{manager} readmitted {local} to its build context"


@pytest.mark.parametrize("manager", runner_keys())
def test_the_two_generated_manifests_agree(tmp_path: Path, manager: str) -> None:
    root = _generate(tmp_path, manager)

    gcloud = [
        line.strip().lstrip("!").strip("/")
        for line in (root / ".gcloudignore").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("!")
    ]

    assert sorted(_dockerignore_allowlist(root)) == sorted(gcloud)
