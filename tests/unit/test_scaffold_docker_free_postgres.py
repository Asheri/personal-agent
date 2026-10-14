"""The Docker-free database reaches exactly the managers that can offer it.

conda-forge ships the PostgreSQL server and the pgvector extension as
ordinary packages, so pixi and conda projects can run the database without a
container runtime. PyPI ships neither, so uv and venv+pip projects cannot,
and a generated project must not advertise a path its own manager cannot
take. One capability on the runner profile decides that for every surface.

That capability chooses a default, not a menu. `SCI_RAG_DB_BACKEND` is a
public contract, so every generated project keeps all of its retained
backends reachable and dispatches each one to the server the reader named.
The dispatch assertions below read the effective command out of `make -n`
rather than looking for a string in the file, because the recipe a reader
gets is the product of the Makefile writer and the later runner rewrite, and
only the two together decide what runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from sci_rag.scaffold import apply
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.questions import default_answers
from sci_rag.scaffold.runners import PROFILES, get_runner, runner_keys

REPO_ROOT = Path(__file__).parents[2]
SLUG = "membrane-materials-kb"

_COPY_FILES = (
    "pyproject.toml",
    "Makefile",
    "docker-compose.yml",
    "Dockerfile",
    ".env.example",
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "uv.lock",
)
_COPY_TREES = ("domain", "docs", "scripts", ".github", ".devcontainer", "src")

_LOCAL_DB = "scripts/local_postgres.py"
_CLOUD_DB = "scripts/cloud_postgres.py"


def _generate(tmp_path: Path, manager: str, *, include_cloud: str = "No") -> Path:
    root = tmp_path / "template"
    root.mkdir(parents=True)
    for name in _COPY_FILES:
        shutil.copy(REPO_ROOT / name, root / name)
    for tree in _COPY_TREES:
        shutil.copytree(REPO_ROOT / tree, root / tree, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "infra" / "terraform").mkdir(parents=True)
    (root / "infra" / "terraform" / "main.tf").write_text("# terraform\n", encoding="utf-8")
    shutil.copytree(
        REPO_ROOT / "infra" / "terraform" / "dev-database",
        root / "infra" / "terraform" / "dev-database",
    )
    (root / "data" / "demo").mkdir(parents=True)
    (root / "data" / "demo" / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "examples").mkdir()
    (root / "examples" / "library_quickstart.py").write_text("# example\n", encoding="utf-8")

    raw = dict(default_answers())
    raw.update(
        {
            "project_name": "Membrane Materials KB",
            "repo_name": SLUG,
            "environment_manager": manager,
            "include_cloud_database": include_cloud,
            "initialize_git": "No",
        }
    )
    apply.apply_all(ProjectAnswers.from_raw(raw), root, year=2026)
    return root


_MAKE = shutil.which("make")
_NEEDS_MAKE = pytest.mark.skipif(
    _MAKE is None,
    reason="the dispatch contract is read out of `make -n`, and make is not installed",
)

# What each manager's generated project starts when the reader sets nothing.
_DEFAULT_BACKEND = {"uv": "docker", "venv+pip": "docker", "pixi": "local", "conda": "local"}


def _make_dry_run(root: Path, target: str, *, backend: str | None = None) -> str:
    """The commands `make <target>` would run with `backend` selected.

    `make -n` prints a recipe without running it, which is the only way to
    read a conditional dispatch the way a reader experiences it. Asserting on
    the file text instead would miss the defect this guards, because the
    recipe a reader gets is the product of the Makefile writer and the later
    runner rewrite, and neither one alone decides it.

    `SCI_RAG_DB_BACKEND` is stripped from the inherited environment first. An
    exported value outranks the Makefile's own `?=` default, and that default
    is one of the things under test.
    """
    assert _MAKE is not None
    env = {key: value for key, value in os.environ.items() if key != "SCI_RAG_DB_BACKEND"}
    if backend is not None:
        env["SCI_RAG_DB_BACKEND"] = backend
    completed = subprocess.run(
        [_MAKE, "-n", target],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Callable[..., Path]:
    """Generate each project once and share it across the dispatch cases.

    The dispatch tests only read a generated project, never write to one, and
    there are twenty of them across four managers. Generating per case would
    copy the template twenty times to prove nothing extra.
    """
    cache: dict[tuple[str, str], Path] = {}

    def factory(manager: str, include_cloud: str = "No") -> Path:
        key = (manager, include_cloud)
        if key not in cache:
            slug = f"{manager}-{include_cloud}".replace("+", "-")
            cache[key] = _generate(
                tmp_path_factory.mktemp(slug), manager, include_cloud=include_cloud
            )
        return cache[key]

    return factory


# --- the capability ---------------------------------------------------------


def test_only_the_conda_forge_managers_offer_a_local_database() -> None:
    offering = {key for key, profile in PROFILES.items() if profile.offers_local_postgres}

    assert offering == {"pixi", "conda"}


@pytest.mark.parametrize("manager", ["pixi", "conda"])
def test_the_offering_managers_name_both_packages(manager: str) -> None:
    packages = get_runner(manager).conda_forge_packages

    assert [name for name, _ in packages] == ["postgresql", "pgvector"]


def test_the_postgresql_bound_is_the_tested_range() -> None:
    """ADR 0008 supports 16 through 18; the manifests have to say the same."""
    packages = dict(get_runner("pixi").conda_forge_packages)

    assert packages["postgresql"] == ">=16,<19"


# --- the generated manifests ------------------------------------------------


def test_a_pixi_project_gets_the_server_in_its_manifest(generated: Callable[..., Path]) -> None:
    root = generated("pixi")

    manifest = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert 'postgresql = ">=16,<19"' in manifest
    assert "pgvector = " in manifest


def test_a_conda_project_gets_the_server_in_its_environment_file(
    generated: Callable[..., Path],
) -> None:
    root = generated("conda")

    document = yaml.safe_load((root / "environment.yml").read_text(encoding="utf-8"))
    named = [d for d in document["dependencies"] if isinstance(d, str)]

    assert "postgresql>=16,<19" in named
    assert any(d.startswith("pgvector") for d in named)


@pytest.mark.parametrize("manager", ["uv", "venv+pip"])
def test_the_pypi_managers_bundle_no_server_but_allow_a_system_one(
    generated: Callable[..., Path], manager: str
) -> None:
    """PyPI has no server package, but Postgres.app can still drive the helper."""
    root = generated(manager)

    for name in ("pyproject.toml", "Makefile", "requirements.txt"):
        path = root / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "postgresql>=16" not in text
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    run = get_runner(manager).run("python scripts/local_postgres.py", project_slug=SLUG)
    assert f"{run} start" in makefile
    assert "SCI_RAG_DB_BACKEND ?= docker" in makefile


# --- the generated task commands --------------------------------------------


@_NEEDS_MAKE
@pytest.mark.parametrize("manager", ["pixi", "conda"])
def test_the_offering_managers_bring_up_the_database_without_docker(
    generated: Callable[..., Path], manager: str
) -> None:
    """No override, no container runtime. Docker stays available, not required."""
    root = generated(manager)
    run = get_runner(manager).run("python scripts/local_postgres.py", project_slug=SLUG)

    assert _make_dry_run(root, "db-up").strip() == f"{run} start"
    assert _make_dry_run(root, "db-down").strip() == f"{run} stop"


@pytest.mark.parametrize("manager", runner_keys())
def test_every_manager_keeps_the_compose_service(
    generated: Callable[..., Path], manager: str
) -> None:
    """Docker dispatch is only honest if the service it names survives."""
    root = generated(manager)

    assert (root / "docker-compose.yml").exists()


# --- the backend dispatch contract ------------------------------------------


@_NEEDS_MAKE
@pytest.mark.parametrize("manager", runner_keys())
def test_every_manager_dispatches_docker_to_compose(
    generated: Callable[..., Path], manager: str
) -> None:
    """An explicit Docker selection starts the isolated Compose service.

    The bundled server is a loopback cluster with trust authentication. A
    reader who asked for Docker and silently got that one was told something
    untrue about their own machine, which is why this is asserted for the two
    managers that bundle a server as well as the two that do not.
    """
    root = generated(manager)

    assert _make_dry_run(root, "db-up", backend="docker").strip() == "docker compose up -d --wait"
    assert _make_dry_run(root, "db-down", backend="docker").strip() == "docker compose down"


@_NEEDS_MAKE
@pytest.mark.parametrize("manager", runner_keys())
def test_every_manager_dispatches_local_to_the_helper_script(
    generated: Callable[..., Path], manager: str
) -> None:
    """`local` is one backend everywhere; only the server source differs."""
    root = generated(manager)
    run = get_runner(manager).run("python scripts/local_postgres.py", project_slug=SLUG)

    assert _make_dry_run(root, "db-up", backend="local").strip() == f"{run} start"
    assert _make_dry_run(root, "db-down", backend="local").strip() == f"{run} stop"


@_NEEDS_MAKE
@pytest.mark.parametrize("manager", runner_keys())
def test_a_retained_cloud_helper_dispatches_only_to_itself(
    generated: Callable[..., Path], manager: str
) -> None:
    root = generated(manager, "Yes")
    run = get_runner(manager).run("python scripts/cloud_postgres.py", project_slug=SLUG)

    started = _make_dry_run(root, "db-up", backend="cloud").strip()
    stopped = _make_dry_run(root, "db-down", backend="cloud").strip()

    assert started == f"{run} start"
    assert stopped == f"{run} stop"
    assert _LOCAL_DB not in started
    assert "docker compose" not in started


@_NEEDS_MAKE
@pytest.mark.parametrize("manager", runner_keys())
def test_a_pruned_cloud_helper_leaves_no_cloud_backend(
    generated: Callable[..., Path], manager: str
) -> None:
    """Declining the helper has to take its branch with it, not orphan it."""
    root = generated(manager)

    dispatched = _make_dry_run(root, "db-up", backend="cloud")

    assert _CLOUD_DB not in dispatched
    assert "Unknown SCI_RAG_DB_BACKEND=cloud" in dispatched


@_NEEDS_MAKE
@pytest.mark.parametrize("manager", runner_keys())
def test_the_unknown_backend_message_offers_only_backends_the_project_has(
    generated: Callable[..., Path], manager: str
) -> None:
    """A menu that lists a choice the project cannot make is worse than none.

    Pruning the Cloud helper removed the `cloud` branch from `db-up` and
    `db-down` but left the fallback message offering `cloud` as one of three
    choices. A reader who took it got exit 2 from the same recipe that had
    just recommended it.
    """
    pruned = _make_dry_run(generated(manager), "db-up", backend="nonsense")

    assert "choose docker or local." in pruned
    assert "cloud" not in pruned

    kept = _make_dry_run(generated(manager, include_cloud="Yes"), "db-up", backend="nonsense")

    assert "choose docker, local, or cloud." in kept


@_NEEDS_MAKE
@pytest.mark.parametrize("manager", runner_keys())
def test_the_declared_default_is_the_server_that_actually_starts(
    generated: Callable[..., Path], manager: str
) -> None:
    """The visible `?=` value and the recipe with no override must agree.

    A Makefile that says `docker` and starts a conda-forge cluster is wrong in
    a way no single dispatch assertion catches, because each backend can be
    individually correct while the advertised default names the other one.
    """
    root = generated(manager)
    expected = _DEFAULT_BACKEND[manager]

    makefile = (root / "Makefile").read_text(encoding="utf-8")

    assert f"SCI_RAG_DB_BACKEND ?= {expected}" in makefile
    assert _make_dry_run(root, "db-up") == _make_dry_run(root, "db-up", backend=expected)
    # `make setup` reaches the same recipe through `$(MAKE) db-up`.
    assert _make_dry_run(root, "db-up").strip() in _make_dry_run(root, "setup")


@pytest.mark.parametrize("manager", runner_keys())
def test_the_local_database_script_survives_generation(
    generated: Callable[..., Path], manager: str
) -> None:
    """Every manager keeps the script; only two select it by default."""
    root = generated(manager)

    assert (root / "scripts" / "local_postgres.py").exists()


@pytest.mark.parametrize("manager", runner_keys())
def test_cloud_database_assets_are_pruned_by_default(
    generated: Callable[..., Path], manager: str
) -> None:
    root = generated(manager)

    assert not (root / _CLOUD_DB).exists()
    assert not (root / "infra" / "terraform" / "dev-database").exists()
    assert _CLOUD_DB not in (root / "Makefile").read_text(encoding="utf-8")


@pytest.mark.parametrize("manager", runner_keys())
def test_every_manager_can_keep_the_cloud_database_assets(
    generated: Callable[..., Path], manager: str
) -> None:
    root = generated(manager, "Yes")

    assert (root / _CLOUD_DB).exists()
    assert (root / "infra" / "terraform" / "dev-database").exists()
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    command = get_runner(manager).run("python scripts/cloud_postgres.py", project_slug=SLUG)
    assert f"{command} start" in makefile
    assert f"{command} stop" in makefile


def test_the_template_carries_the_literals_generation_depends_on() -> None:
    """The default line is rewritten by literal substitution; keep it exact.

    The two compose recipes are no longer rewritten, but they are what an
    explicit Docker selection dispatches to in every generated project, so
    they have to survive here byte for byte as well.
    """
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "SCI_RAG_DB_BACKEND ?= docker" in makefile
    assert "docker compose up -d --wait" in makefile
    assert "docker compose down" in makefile


def test_cloud_helper_contains_no_environment_manager_commands() -> None:
    script = (REPO_ROOT / _CLOUD_DB).read_text(encoding="utf-8")

    for profile in PROFILES.values():
        for token in profile.command_tokens():
            assert token not in script


def test_the_data_directory_is_ignored() -> None:
    """A cluster under the project root is a corpus waiting to be committed."""
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".pgdata/" in ignored
    assert ".pgdata.log" in ignored
    assert ".cloudsql/" in ignored
