"""The baseline change request must explain how each failure was repaired."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGE_REQUEST = (
    ROOT
    / "docs"
    / "full-stack-development"
    / "requirements"
    / "modelscope-deepseek-providers"
    / "changes"
    / "001-baseline-fix-change-request.md"
)


def _changed_paths() -> set[str]:
    commands = (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    paths: set[str] = set()
    for command in commands:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        paths.update(line for line in result.stdout.splitlines() if line)
    return paths


def _mapping_rows(text: str) -> list[tuple[str, str, str, str]]:
    mapping = text.partition("## Failure Group Mapping")[2].partition("## ")[0]
    rows: list[tuple[str, str, str, str]] = []
    for line in mapping.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == "Failure group" or set(cells[0]) <= {"-", ":"}:
            continue
        assert len(cells) == 4, f"malformed mapping row: {line}"
        rows.append((cells[0], cells[1], cells[2], cells[3]))
    return rows


def test_the_change_request_maps_failures_to_repairs_and_verification() -> None:
    text = CHANGE_REQUEST.read_text(encoding="utf-8")

    assert "root causes listed below" not in text
    assert "## Failure Group Mapping" in text
    assert "| Failure group | Root cause | Modified files | Verification |" in text
    assert "Provider feature files are tracked by the implementation plan" in text

    rows = _mapping_rows(text)
    groups = {row[0] for row in rows}
    expected_groups = {
        "GNU make",
        "extensionless Windows shims",
        "POSIX shell lookup",
        "UTF-8 decoding",
        "internal workspace pages",
        "native Windows paths",
        "absolute fallback path",
        "Windows mode bits",
    }
    assert groups == expected_groups
    assert all(row[1] and row[2] and row[3] for row in rows)
    assert "uv run pytest tests/unit -q" in text

    expected_modified = {
        "README.md",
        "docs/quickstart.md",
        "mkdocs.yml",
        "scripts/cloud_postgres.py",
        "src/sci_rag/cli/draft.py",
        "src/sci_rag/scaffold/apply.py",
        "src/sci_rag/scaffold/permissions.py",
        "tests/unit/platform_checks.py",
        "tests/unit/test_baseline_fix_change_request.py",
        "tests/unit/test_cloud_postgres_script.py",
        "tests/unit/test_database_backends.py",
        "tests/unit/test_docs_backup_runbook.py",
        "tests/unit/test_docs_code_snippets.py",
        "tests/unit/test_docs_comparison_page.py",
        "tests/unit/test_docs_deploy_workflow.py",
        "tests/unit/test_docs_faq.py",
        "tests/unit/test_docs_onboarding.py",
        "tests/unit/test_docs_page_head.py",
        "tests/unit/test_docs_site_copy.py",
        "tests/unit/test_platform_checks.py",
        "tests/unit/test_scaffold_apply.py",
        "tests/unit/test_scaffold_runner_coherence.py",
    }
    listed = {
        path
        for row in rows
        for path in re.findall(r"`([^`]+)`", row[2])
        if "/" in path or path.endswith((".md", ".py", ".yml"))
    }
    missing = sorted(expected_modified - listed)
    assert missing == [], f"the repair map is missing {missing}"

    nonexistent = sorted(path for path in listed if not (ROOT / path).is_file())
    assert nonexistent == [], f"the repair map names nonexistent files {nonexistent}"

    changed = _changed_paths()
    if changed:
        unmapped_changes = sorted(listed - changed)
        assert unmapped_changes == [], (
            f"the repair map lists files outside the current change {unmapped_changes}"
        )
