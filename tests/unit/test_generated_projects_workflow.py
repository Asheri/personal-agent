"""What the generated-project matrix has to keep proving.

`doctor` was demoted to `continue-on-error` while it reported FAIL for an
offline project. Once that is fixed the demotion is a hole: a generated
project could regress into an unhealthy state and the matrix would still be
green. The Docker-free database has the same shape of risk in reverse, since
documenting a path the matrix does not exercise is how it rots. These tests
keep both from quietly slipping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sci_rag.scaffold.runners import get_runner

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "generated-projects.yml"
DOCKER_FREE = ROOT / ".github" / "workflows" / "docker-free-postgres.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CODEQL = ROOT / ".github" / "workflows" / "codeql.yml"
LINK_ROT = ROOT / ".github" / "workflows" / "link-rot.yml"


def _load_workflow(path: Path) -> dict[str, Any]:
    workflow: dict[str, Any] = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return workflow


def _generate_steps() -> list[dict[str, Any]]:
    workflow = _load_workflow(WORKFLOW)
    steps: list[dict[str, Any]] = workflow["jobs"]["generate"]["steps"]
    return steps


def test_the_conda_harness_matches_the_scaffold_profile() -> None:
    conda = get_runner("conda")
    matches = [
        step
        for step in _generate_steps()
        if str(step.get("uses", "")).startswith("conda-incubator/setup-miniconda@")
    ]

    assert len(matches) == 1, f"expected one conda setup step, found {len(matches)}"
    assert matches[0]["uses"] == conda.ci_setup_action
    assert matches[0]["with"] == {
        "auto-activate": "true",
        "activate-environment": "",
    }
    assert ("auto-activate", "false") in conda.ci_setup_inputs
    assert all(name != "auto-activate-base" for name, _ in conda.ci_setup_inputs)


def _doctor_step() -> dict[str, Any]:
    matches = [step for step in _generate_steps() if "sci-rag doctor" in step.get("run", "")]
    assert len(matches) == 1, f"expected exactly one doctor step, found {len(matches)}"
    return matches[0]


def test_the_generated_project_matrix_gates_on_doctor() -> None:
    step = _doctor_step()

    assert "continue-on-error" not in step
    assert "if" not in step, "an always() or conditional guard would soften the gate"


def test_the_matrix_stands_up_the_docker_free_database_for_pixi_and_conda() -> None:
    """Criterion: the Docker-free path is not advertised before it is tested."""
    steps = _generate_steps()
    matches = [s for s in steps if "local_postgres.py" in s.get("run", "")]

    assert matches, "no step brings up the generated project's own database"
    guards = " ".join(str(s.get("if", "")) for s in matches)
    assert "pixi" in guards and "conda" in guards, (
        "the Docker-free legs have to be the two managers whose channel ships a server"
    )


def test_the_docker_free_workflow_covers_both_required_platforms() -> None:
    """Criterion: passes the integration suite on osx-arm64 and linux-64.

    The matrix is a `fromJSON` expression, so the platform list lives in the
    selector's script rather than in the matrix block. Assert on where it is
    actually written, not on the indirection.
    """
    workflow = _load_workflow(DOCKER_FREE)

    chooser = " ".join(step.get("run", "") for step in workflow["jobs"]["select"]["steps"])
    assert "ubuntu-latest" in chooser and "linux-64" in chooser
    assert "macos-latest" in chooser and "osx-arm64" in chooser

    job = workflow["jobs"]["integration"]
    assert "needs.select.outputs.platforms" in job["strategy"]["matrix"]["include"]

    runs = " ".join(step.get("run", "") for step in job["steps"])
    assert "local_postgres.py start" in runs
    assert "tests/integration" in runs and "tests/server" in runs
    assert "docker" not in runs.lower(), "a Docker-free job must not reach for Docker"


def test_the_docker_free_workflow_refuses_a_skipped_suite() -> None:
    """A skipped integration suite looks identical to a passing one."""
    workflow = _load_workflow(DOCKER_FREE)
    runs = " ".join(step.get("run", "") for step in workflow["jobs"]["integration"]["steps"])

    assert "Postgres unavailable" in runs, "nothing detects the skip path"


def test_the_selector_contexts_are_unambiguous_and_their_matrices_have_gates() -> None:
    generated = _load_workflow(WORKFLOW)
    docker_free = _load_workflow(DOCKER_FREE)

    assert generated["jobs"]["select"]["name"] == "select-managers"
    assert docker_free["jobs"]["select"]["name"] == "select-platforms"

    for workflow, gate_name, dependency in (
        (generated, "generated-projects-gate", "generate"),
        (docker_free, "docker-free-postgres-gate", "integration"),
    ):
        gate = workflow["jobs"]["gate"]
        assert gate["name"] == gate_name
        assert gate["needs"] == ["select", dependency]
        assert gate["if"] == "always()"
        assert "continue-on-error" not in gate

        runs = " ".join(step.get("run", "") for step in gate["steps"])
        assert "needs.select.result" in runs
        assert f"needs.{dependency}.result" in runs
        assert runs.count('= "success"') == 2


def test_ci_checks_the_lock_before_sync_and_runs_every_pre_commit_hook() -> None:
    workflow = _load_workflow(CI)
    check_runs = [step.get("run", "") for step in workflow["jobs"]["checks"]["steps"]]

    lock_index = next(index for index, run in enumerate(check_runs) if "uv lock --check" in run)
    sync_index = next(index for index, run in enumerate(check_runs) if "uv sync" in run)
    assert lock_index < sync_index, "uv sync can repair a stale lock before the check sees it"

    pre_commit = workflow["jobs"]["pre-commit"]
    assert "continue-on-error" not in pre_commit
    runs = " ".join(step.get("run", "") for step in pre_commit["steps"])
    assert "pre-commit run --all-files --show-diff-on-failure" in runs


def test_ci_validates_the_dev_database_terraform_module() -> None:
    workflow = _load_workflow(CI)
    runs = " ".join(step.get("run", "") for step in workflow["jobs"]["terraform"]["steps"])

    assert "terraform -chdir=dev-database init -backend=false -input=false" in runs
    assert "terraform -chdir=dev-database validate" in runs


def test_generated_projects_cover_every_cloud_asset_shape_for_every_manager() -> None:
    workflow = _load_workflow(WORKFLOW)
    generate = workflow["jobs"]["generate"]
    runs = " ".join(step.get("run", "") for step in generate["steps"])

    assert set(generate["strategy"]["matrix"]) == {"manager"}, (
        "a second matrix axis would rename the required generate (uv) check"
    )
    assert "for cloud_case in pruned kept helper-only" in runs
    assert 'pruned) helper="No"; terraform="No"' in runs
    assert 'kept) helper="Yes"; terraform="Yes"' in runs
    assert 'helper-only) helper="Yes"; terraform="No"' in runs
    assert "include_cloud_database: $helper" in runs
    assert "include_terraform: $terraform" in runs
    assert "scripts/cloud_postgres.py" in runs
    assert "infra/terraform/dev-database" in runs
    assert "no live GCP call" in runs


def test_the_generated_project_runs_its_whole_demo_target() -> None:
    """F-004 hid here, because this leg stopped one command short of it.

    The step ingested and retrieved, then skipped `eval retrieval` under a
    comment calling the blanked seed questions "the point of the reset, not a
    regression". That was the command a reader's `make demo` failed on, so the
    matrix proved the demo worked while the demo did not. Running the target
    itself is the only version of this check that could have caught it: the
    target owns the sequence, and a leg that reimplements the sequence is free
    to leave out the part that breaks.
    """
    steps = _generate_steps()
    scripts = [step.get("run", "") for step in steps]

    assert any("make demo" in script for script in scripts), (
        "the generated project has to run its own demo target, not a subset of it"
    )
    for script in scripts:
        if "make demo" in script:
            continue
        assert "sci-rag retrieve" not in script, (
            "a hand-written copy of the demo sequence can drift from the target"
        )


def test_the_demo_leg_generates_the_corpus_source_whose_demo_can_pass() -> None:
    """A demo target scores retrieval, so this leg needs demo ground truth.

    `demo_only` is the corpus choice that keeps the bundled seed questions,
    because there the synthetic corpus is the corpus. Any other choice blanks
    them on purpose, so a green leg has to be generated with this one.
    """
    generate = next(
        script
        for script in (step.get("run", "") for step in _generate_steps())
        if "sci-rag init --answers-file" in script and "cloud-answers" not in script
    )
    assert "corpus_source: demo_only" in generate
    assert 'include_demo_corpus: "Yes"' in generate


def test_the_matrix_also_runs_the_corpus_source_a_reader_gets_by_default() -> None:
    """`demo_only` is not the shape most readers generate.

    `local_files` is the wizard default and the demo corpus defaults to Yes,
    so pressing Enter through Quick setup produces a project with its own
    corpus source that still keeps the demo. That project's `make demo` was
    the one that could not complete, and the matrix could not see it because
    every leg generated `demo_only`.
    """
    scripts = [step.get("run", "") for step in _generate_steps()]
    default_shape = [
        script
        for script in scripts
        if "corpus_source: local_files" in script and 'include_demo_corpus: "Yes"' in script
    ]

    assert default_shape, "no leg generates the shape a reader gets by default"
    assert any("make demo" in script for script in default_shape), (
        "and that shape has to run its own demo target"
    )


def test_codeql_has_security_permissions_and_all_three_triggers() -> None:
    workflow = _load_workflow(CODEQL)

    assert set(workflow["on"]) == {"pull_request", "push", "schedule"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["permissions"]["contents"] == "read"
    assert workflow["permissions"]["security-events"] == "write"

    uses = [step.get("uses", "") for step in workflow["jobs"]["analyze"]["steps"]]
    codeql_uses = [use for use in uses if use.startswith("github/codeql-action/")]
    assert codeql_uses == [
        "github/codeql-action/init@v4",
        "github/codeql-action/analyze@v4",
    ]


def test_external_link_checks_never_run_on_pull_requests() -> None:
    workflow = _load_workflow(LINK_ROT)

    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
    steps = workflow["jobs"]["external-links"]["steps"]
    runs = " ".join(step.get("run", "") for step in steps)
    assert "make docs" in runs

    lychee_steps = [step for step in steps if step.get("uses") == "lycheeverse/lychee-action@v2"]
    assert len(lychee_steps) == 2, "Markdown and built HTML need different URL bases"

    markdown = next(step for step in lychee_steps if "**/*.md" in step["with"]["args"])
    site = next(step for step in lychee_steps if "site/**/*.html" in step["with"]["args"])

    assert "--offline" not in markdown["with"]["args"]
    assert "--exclude-loopback" in markdown["with"]["args"]

    assert "--offline" not in site["with"]["args"]
    assert "--exclude-loopback" in site["with"]["args"]
    assert "--exclude-path" in site["with"]["args"]
    assert "site/overrides" in site["with"]["args"]
    assert "--exclude" in site["with"]["args"]
    assert "sustainability-software-lab[.]github[.]io" in site["with"]["args"]
    assert "--base-url" in site["with"]["args"]
    assert "https://sustainability-software-lab.github.io/sci-rag-kit/" in site["with"]["args"]
