from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "docs-deploy.yml"


def test_docs_deploy_privileges_only_trusted_main_pushes() -> None:
    """The privileged Pages job must never execute a workflow-run checkout."""
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    build = workflow["jobs"]["build"]
    deploy = workflow["jobs"]["deploy"]

    condition = build["if"]
    assert "workflow_run.event == 'push'" in condition
    assert "workflow_run.head_repository.full_name == github.repository" in condition
    assert "workflow_run.head_branch == 'main'" in condition
    assert "workflow_run.head_sha == github.sha" in condition
    assert "workflow_run.conclusion == 'success'" in condition

    assert workflow["permissions"] == {"contents": "read"}
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}

    build_actions = [step.get("uses", "") for step in build["steps"]]
    deploy_actions = [step.get("uses", "") for step in deploy["steps"]]
    assert not any(action.startswith("actions/configure-pages@") for action in build_actions)
    assert not any(action.startswith("actions/checkout@") for action in deploy_actions)
    assert any(action.startswith("actions/configure-pages@") for action in deploy_actions)
    assert any(action.startswith("actions/deploy-pages@") for action in deploy_actions)
