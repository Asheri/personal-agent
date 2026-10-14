"""Static security and isolation contract for the dev-only Cloud SQL module.

F-019 in the 2026-08-29 documentation route audit found this module shipping
the maintainer's Google Cloud project and the live shared instance name as
defaults, so a reader who followed it without both overrides would have
planned mutations against maintained infrastructure. The identifiers a
mutation is aimed at are now required inputs with no defaults.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
TERRAFORM_ROOT = REPO_ROOT / "infra" / "terraform"
MODULE = TERRAFORM_ROOT / "dev-database"

# The identifiers that name real infrastructure somebody else maintains lived
# here, guarded across this module's own files. #200 found the same two
# strings shipped in `scripts/cloud_postgres.py`, so the guard moved to
# `test_maintained_identifiers.py` and now covers every tracked file. Naming
# them here as well would put them back in a tracked file.

# Inputs that decide what a mutation is aimed at. Cost and shape inputs such
# as region, tier, and database user may keep defaults; these may not.
TARGETING_INPUTS = ("project_id", "instance_name")


def _terraform_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(MODULE.glob("*.tf")))


def _variable_block(name: str) -> str:
    text = (MODULE / "variables.tf").read_text(encoding="utf-8")
    match = re.search(rf'variable "{name}" \{{(.*?)\n\}}', text, re.DOTALL)
    assert match, f"no variable block for {name}"
    return match.group(1)


def test_dev_module_is_separate_and_keeps_its_development_shape() -> None:
    assert (MODULE / "main.tf").exists()
    assert (MODULE / "variables.tf").exists()
    assert (MODULE / "outputs.tf").exists()
    text = _terraform_text()

    assert 'default     = "us-west1"' in text
    assert 'default     = "db-g1-small"' in text
    assert 'edition           = "ENTERPRISE"' in text
    assert "deletion_protection = var.deletion_protection" in text
    assert "default     = false" in text
    assert "ignore_changes = [settings[0].activation_policy]" in text


@pytest.mark.parametrize("name", TARGETING_INPUTS)
def test_an_input_that_aims_a_mutation_has_no_default(name: str) -> None:
    """Omitting it must select nothing, rather than selecting somebody else's."""
    block = _variable_block(name)
    # An assignment, not the word: the error messages say "there is no default".
    assert not re.search(r"^\s*default\s*=", block, re.MULTILINE), (
        f"{name} has a default, so terraform plan can target infrastructure the reader never named"
    )


@pytest.mark.parametrize("name", TARGETING_INPUTS)
def test_an_input_that_aims_a_mutation_validates_what_it_is_given(name: str) -> None:
    """A required variable stops the run. Validation says why in one line."""
    assert "validation" in _variable_block(name)


def test_dev_instance_uses_proxy_only_public_connectivity() -> None:
    text = _terraform_text()

    assert "ipv4_enabled = true" in text
    assert "authorized_networks" not in text
    assert 'database_version = "POSTGRES_16"' in text


def test_developer_access_is_limited_to_the_dev_instance_and_secret() -> None:
    text = _terraform_text()

    assert 'role    = "roles/cloudsql.editor"' in text
    assert "resource.name.startsWith" in text
    assert 'role      = "roles/secretmanager.secretAccessor"' in text
    assert "google_secret_manager_secret.password.id" in text


def test_module_outputs_the_helper_configuration_without_the_password() -> None:
    outputs = (MODULE / "outputs.tf").read_text(encoding="utf-8")

    assert 'output "connection_name"' in outputs
    assert 'output "instance_name"' in outputs
    assert 'output "sci_rag_cloud_pg_config"' in outputs
    assert "SCI_RAG_CLOUD_PG_PROJECT" in outputs
    assert "SCI_RAG_CLOUD_PG_INSTANCE" in outputs
    assert "SCI_RAG_CLOUD_PG_REGION" in outputs
    assert "random_password" not in outputs
