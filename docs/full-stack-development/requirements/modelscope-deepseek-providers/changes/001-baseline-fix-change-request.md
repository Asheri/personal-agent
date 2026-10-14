# Change 001: Fix the Windows Unit-Test Baseline

## User Change Request

Fix the 28 failures observed on the unmodified unit-test baseline before
continuing with ModelScope and DeepSeek provider work.

## Impacted Layers

- Engineering contract: the baseline must be green on the current host before
  feature implementation starts.
- Acceptance contract: final verification includes the full unit suite, not
  only provider-focused tests.
- Product, API, data, retrieval, scope, and answer contracts are unchanged.

## Artifacts to Update

- `00-stage.json`: block implementation and record the baseline-debugging stage.
- Implementation plan: keep provider tasks blocked until the baseline is green.
- Provider feature files are tracked by the implementation plan, not this
  baseline repair map.
- Tests and platform adapters affected by the repairs recorded in the failure
  group mapping below.

The existing `docs/planning/` exclusion in the public-page structure test is
pre-existing repository behavior and is out of scope for this baseline fix.
The only new exclusions allowed are the agent-owned
`docs/full-stack-development/` and `docs/superpowers/` workspaces.

## Failure Group Mapping

| Failure group | Root cause | Modified files | Verification |
| --- | --- | --- | --- |
| GNU make | The Windows host has no GNU make, so direct Makefile execution raised `FileNotFoundError`. | `tests/unit/test_database_backends.py` | `uv run pytest tests/unit/test_database_backends.py -q` |
| extensionless Windows shims | `shutil.which()` and subprocess could not resolve extensionless fake `gcloud`, `cloud-sql-proxy`, and `psql` files. | `tests/unit/test_cloud_postgres_script.py`, `scripts/cloud_postgres.py` | `uv run pytest tests/unit/test_cloud_postgres_script.py -q` |
| POSIX shell lookup | The available `sh`/`bash` resolved to WSL and could not run Git for Windows paths or `/bin/bash`. | `tests/unit/test_docs_backup_runbook.py`, `tests/unit/test_docs_onboarding.py`, `tests/unit/platform_checks.py`, `tests/unit/test_platform_checks.py` | `uv run pytest tests/unit/test_docs_backup_runbook.py tests/unit/test_docs_onboarding.py -q` |
| UTF-8 decoding | Documentation tests called `Path.read_text()` without an encoding and inherited Windows GBK. | `tests/unit/test_docs_code_snippets.py`, `tests/unit/test_docs_comparison_page.py`, `tests/unit/test_docs_deploy_workflow.py`, `tests/unit/test_docs_faq.py`, `tests/unit/test_docs_page_head.py`, `tests/unit/test_docs_site_copy.py` | `uv run pytest tests/unit/test_docs_page_head.py tests/unit/test_docs_site_copy.py -q` |
| internal workspace pages | Agent-owned documentation entered public-page scans and the MkDocs source tree. | `mkdocs.yml`, `tests/unit/test_docs_page_head.py`, `tests/unit/test_scaffold_runner_coherence.py`, `tests/unit/test_baseline_fix_change_request.py` | `uv run --group docs pytest tests/unit/test_docs_page_head.py -q -rs` |
| native Windows paths | Generated transcript snapshots rendered `data\\demo\\...`; the committed snapshot uses `/`. | `src/sci_rag/scaffold/apply.py` | `uv run pytest tests/unit/test_docs_transcript.py -q` |
| absolute fallback path | `draft questions` printed the absolute Windows `data/raw` path; project-root output uses a relative POSIX path. | `src/sci_rag/cli/draft.py` | `uv run pytest tests/unit/test_draft_cli.py -q` |
| Windows mode bits | `Path.chmod(0o600)` reported `0666` and a mock could not prove owner-only security. | `README.md`, `docs/quickstart.md`, `src/sci_rag/scaffold/apply.py`, `src/sci_rag/scaffold/permissions.py`, `tests/unit/test_scaffold_apply.py` | `uv run pytest tests/unit/test_scaffold_apply.py -q` |

## Invalidated Approvals

- `approvals.implementationApproved` remains false.
- Requirements approval remains true because provider behavior is unchanged.

## Stage Regression Target

`implementation-plan-ready` to `baseline-debugging`.

## Required Re-Verification

```bash
uv run pytest tests/unit -q
```

Required result: zero failures. Skips must remain diagnostic and must not be
introduced to hide the existing failures.
