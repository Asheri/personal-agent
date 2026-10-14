"""Contracts for the supported development database documentation.

The database backend is selected independently from the environment manager,
and generated projects can retain or prune the optional Cloud helper. These
guards keep the public setup path, the lifecycle safety boundary, and the
machine-local Conductor recipe aligned with those shipped seams.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _one_line(path: str) -> str:
    return re.sub(r"\s+", " ", _read(path))


def test_setup_starts_the_selected_backend_with_docker_as_the_template_default() -> None:
    for path in ("README.md", "docs/quickstart.md"):
        page = _one_line(path)
        assert "`make setup` starts the selected database backend" in page, path
        assert "Docker is the template default" in page, path
        assert "`make setup` starts the compose Postgres" not in page, path

    readme = _read("README.md")
    assert "[Configure Postgres backend](docs/run-postgres.md)" in readme


def test_1536_upgrade_changes_environment_before_running_migration() -> None:
    """The migration reads the configured width, so 1536 must leave .env first."""
    for path in ("README.md", "docs/configuration.md", "docs/extend.md"):
        page = _one_line(path)
        order_section = page.partition("Upgrade in this order:")[2]
        assert order_section, f"{path} must publish an explicit upgrade order"
        ordered_contract = (
            "Back up the database",
            "Change `SCI_RAG_EMBEDDING_DIM` from 1536 to 1024 in `.env`",
            "`uv run sci-rag db upgrade`",
            "`uv run sci-rag embed reindex --dry-run`",
            "`--apply`",
        )
        positions = [order_section.find(anchor) for anchor in ordered_contract]
        missing = [
            anchor
            for anchor, position in zip(ordered_contract, positions, strict=True)
            if position < 0
        ]
        assert not missing, f"{path} is missing upgrade steps: {missing}"
        assert positions == sorted(positions), f"{path} changes the upgrade order: {positions}"

        fail_fast_match = re.search(r"fail(?:s)? fast", page)
        assert fail_fast_match is not None, f"{path} must explain the dimension fail-fast"
        fail_fast = fail_fast_match.start()
        assert fail_fast < page.find("Upgrade in this order:"), (
            f"{path} must warn before publishing the upgrade order"
        )
        required_claims = (
            "Settings restricts ModelScope embeddings to 32 through 1024",
            "migration `0007` requires the current configuration to be between 32 and 1024",
            "Old Google 1536 `.env` must be changed to 1024 before `uv run sci-rag db upgrade`",
        )
        missing_claims = [claim for claim in required_claims if claim not in page]
        assert not missing_claims, f"{path} conflates validation boundaries: {missing_claims}"


def test_setup_docs_use_one_install_command_path() -> None:
    for path in ("README.md", "docs/quickstart.md"):
        text = _read(path)
        assert "make setup\nuv sync --extra" not in text, path
        assert "$ make setup\n$ uv sync --extra" not in text, path
        assert "`uv sync --extra modelscope-embedding --extra openai`" in text, path


def test_compose_service_claims_no_process_global_container_name() -> None:
    """Two copies of this template have to be able to start their own database.

    Docker reserves the name of a stopped container too, so a fixed
    ``container_name`` made a second generated project fail before Compose
    reached port binding, on a machine where nothing was running and port
    5433 was free. Without one, Compose derives the container name from the
    project directory, which is what already scopes the network and the
    named volume.
    """
    compose = yaml.safe_load(_read("docker-compose.yml"))

    for name, service in compose["services"].items():
        assert "container_name" not in service, name

    for name, volume in compose["volumes"].items():
        assert not (volume or {}).get("external"), name


def test_docker_docs_say_how_to_move_a_host_port_another_project_holds() -> None:
    """The published host port is the one thing Compose cannot namespace.

    Removing the global container name lets two projects coexist while only
    one database runs. Running both at once still needs a free port, and a
    reader who is not told that reads the collision as a broken template.
    """
    quickstart = _one_line("docs/quickstart.md")
    assert "port `5433` is already taken" in quickstart
    assert "docker-compose.yml" in quickstart
    assert "SCI_RAG_DATABASE_URL" in quickstart

    docker = re.sub(
        r"\s+",
        " ",
        _read("docs/troubleshooting.md").partition("### Docker")[2].partition("### ")[0],
    )
    assert "Compose scopes the container, network, and volume" in docker
    assert "already allocated" in docker
    # The two edits have to agree, so the page shows both and the same port.
    assert '- "5434:5432"' in docker
    assert "SCI_RAG_DATABASE_URL=postgresql+asyncpg://sci_rag:sci_rag@localhost:5434/sci_rag" in (
        docker
    )


def test_postgres_guide_publishes_the_backend_matrix_and_cloud_stages() -> None:
    page = _read("docs/run-postgres.md")
    normalized = re.sub(r"\s+", " ", page)

    for heading in (
        "## Recommended defaults",
        "## One-time Cloud SQL provisioning",
        "## Start a Cloud SQL workspace",
        "## Manage the Cloud SQL lifecycle",
        "## Use Cloud SQL in Conductor workspaces",
    ):
        assert heading in page

    for manager in ("uv", "pixi", "conda", "venv + pip"):
        assert manager in page
    for backend in ("Docker", "conda-forge", "system PostgreSQL", "Cloud SQL"):
        assert backend in page

    for name in (
        "SCI_RAG_CLOUD_PG_PROJECT",
        "SCI_RAG_CLOUD_PG_INSTANCE",
        "SCI_RAG_CLOUD_PG_REGION",
        "SCI_RAG_CLOUD_PG_DIR",
        "SCI_RAG_CLOUD_PG_PORT",
        "SCI_RAG_CLOUD_PG_WORKSPACE",
        "SCI_RAG_CLOUD_PG_USER",
    ):
        assert f"`{name}`" in page

    assert '-var "project_id=YOUR_PROJECT"' in page
    assert "Terraform state contains the generated database password" in normalized
    assert "first start can take several minutes" in normalized
    assert "Every database shares the same PostgreSQL role" in normalized
    assert "Treat the separation as workspace isolation only" in normalized
    assert "must not hold the only copy of a valuable corpus" in normalized


def test_cloud_lifecycle_table_preserves_workspace_and_shared_boundaries() -> None:
    page = _read("docs/run-postgres.md")
    lifecycle = re.sub(
        r"\s+",
        " ",
        page.partition("## Manage the Cloud SQL lifecycle")[2].partition("## ")[0],
    ).casefold()

    for action in ("`config`", "`start`", "`status`", "`stop`", "`pause`", "`resume`"):
        assert action in lifecycle
    assert "stops only the current workspace proxy" in lifecycle
    assert "affects every workspace" in lifecycle
    assert "do not delete" in lifecycle


def test_conductor_recipe_is_explicitly_user_installed_and_machine_local() -> None:
    page = _read("docs/run-postgres.md")
    recipe = re.sub(
        r"\s+",
        " ",
        page.partition("## Use Cloud SQL in Conductor workspaces")[2].partition("## ")[0],
    )

    assert "user-installed" in recipe
    assert "machine-local" in recipe
    assert "Conductor root clone" in recipe
    assert ".conductor/settings.local.toml" in recipe
    assert ".conductor/setup-cloud-workspace.sh" in recipe
    assert ".conductor/run-cloud-tests.sh" in recipe
    assert "make db-down" in recipe
    assert "must not pause" in recipe
    assert "does not ship" in recipe
    assert "/Users/" not in recipe
    assert "tylerhuntington" not in recipe.casefold()


def test_cloud_troubleshooting_uses_dynamic_ports_and_start_resumes() -> None:
    page = _read("docs/troubleshooting.md")
    cloud = page.partition("### Cloud SQL")[2].partition("## ")[0]

    assert "dynamic port" in cloud
    assert "`start` resumes" in cloud
    assert "`resume` changes the instance activation policy" in cloud
    assert "run `resume`, then `start`" not in cloud


def test_database_decisions_and_benchmark_reproduction_show_current_contract() -> None:
    adr8 = _read("docs/adr/0008-supported-postgresql-versions.md")
    adr9 = _read("docs/adr/0009-cloud-dev-database.md")
    benchmark_generator = _read("scripts/render_benchmarks.py")
    benchmarks = _read("docs/benchmarks.md")
    makefile = _read("Makefile")

    assert "Partially superseded by [ADR 0009]" in adr8
    assert "Cloud SQL was 3.65 times slower" in adr9
    assert "## Reversal conditions" in adr9
    assert "## Revisit if" not in adr9
    assert "selected PostgreSQL backend" in benchmark_generator
    assert "selected PostgreSQL backend" in benchmarks
    assert "Needs the selected PostgreSQL backend" in makefile
