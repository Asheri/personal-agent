"""The deploy module has to apply on a project that has never seen Cloud SQL.

`terraform apply` with this module's own defaults failed on a fresh project:

    Error 400: Invalid request: Invalid Tier (db-g1-small) for
    (ENTERPRISE_PLUS) Edition. Use a predefined Tier like
    db-perf-optimized-N-* instead.

The module names a tier and never names an edition, so it inherits whatever
Cloud SQL defaults new instances to. That default moved to `ENTERPRISE_PLUS`,
which rejects the shared-core tiers this module deliberately chooses.

The sibling `dev-database` module already pins `edition = "ENTERPRISE"` and
has a test saying so. This is the same lesson, arriving at the module a
reader of `docs/deploy-gcp.md` actually runs.

Why it went unnoticed: a project with an existing Cloud SQL instance often
resolves differently, so the defaults work nearly everywhere except on the
empty project the deploy guide is written for.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
MAIN = REPO_ROOT / "infra" / "terraform" / "main.tf"
VARIABLES = REPO_ROOT / "infra" / "terraform" / "variables.tf"
OUTPUTS = REPO_ROOT / "infra" / "terraform" / "outputs.tf"
GUIDE = REPO_ROOT / "docs" / "deploy-gcp.md"

# Tiers Cloud SQL will not accept under ENTERPRISE_PLUS. Named from the
# provider's own rejection rather than from a docs page.
SHARED_CORE_TIERS = ("db-f1-micro", "db-g1-small")


def test_the_deploy_instance_pins_its_edition() -> None:
    """Inheriting the edition means inheriting a default that moves.

    Pinning it is what keeps the cheap tier below valid, and keeps a reader
    from being silently placed on the much more expensive edition.
    """
    text = MAIN.read_text(encoding="utf-8")

    assert re.search(r'edition\s*=\s*"ENTERPRISE"', text), (
        "infra/terraform/main.tf must pin edition, or a moving Cloud SQL "
        "default decides it and rejects the tier this module ships"
    )


def test_the_default_tier_is_one_the_pinned_edition_accepts() -> None:
    """The two settings only make sense together.

    A shared-core tier is correct for a deploy guide's default, and it is
    only valid on ENTERPRISE. If someone raises the edition later, this
    fails rather than letting the pair drift into a 400 at apply time.
    """
    default = re.search(
        r'variable "db_tier".*?default\s*=\s*"([^"]+)"',
        VARIABLES.read_text(encoding="utf-8"),
        re.S,
    )
    assert default, "db_tier must declare a default"

    if default.group(1) in SHARED_CORE_TIERS:
        assert re.search(r'edition\s*=\s*"ENTERPRISE"', MAIN.read_text(encoding="utf-8")), (
            f"{default.group(1)} is a shared-core tier, valid only on ENTERPRISE"
        )


def test_the_seeded_api_keys_value_is_one_the_server_can_boot_on() -> None:
    """The module seeds this secret and the server parses it. They must agree.

    `terraform apply` created every resource and then failed, because the
    seed was `"{}"` and `auth.py` refuses an empty allowlist:

        RuntimeError: SCI_RAG_API_KEYS must be a non-empty JSON object
        Container called exit(1).

    Neither side was individually wrong. The server is right to refuse an
    empty allowlist rather than serve open, and the module is right to want
    a first version so the service has something to mount. Nothing tested
    them together, and `terraform validate` cannot: it is a runtime contract
    between a seeded string and a parser.
    """
    text = MAIN.read_text(encoding="utf-8")

    seed = re.search(
        r'resource "google_secret_manager_secret_version" "api_keys_seed"\s*\{(.*?)\n\}',
        text,
        re.S,
    )
    assert seed, "the module must seed a first api_keys version"

    value = seed.group(1)
    assert value not in ('"{}"', "'{}'"), (
        "seeding an empty object deploys a service that cannot start; "
        "seed a generated key so the deploy comes up secured"
    )
    assert "random_password" in value, (
        "seed a generated key, the way the database password already is, "
        f"rather than a literal: {value}"
    )


def test_every_protectable_resource_honours_the_deletion_protection_input() -> None:
    """A deploy you cannot tear down is not a deploy you should ship.

    `deletion_protection` was written for the database, and reads that way:
    "Protect the database from accidental terraform destroy." The Cloud Run
    provider later grew its own `deletion_protection`, defaulting to true, and
    the service resource never opted in. So a `terraform destroy` with the
    documented `-var deletion_protection=false` removed the database and
    refused the service:

        cannot destroy service without setting deletion_protection=false

    An operator who follows the teardown instructions is left with a running
    service and no documented way to remove it, which matters most for anyone
    evaluating the kit on a project they intend to delete afterwards.
    """
    text = MAIN.read_text(encoding="utf-8")

    missing = []
    for kind, label in (
        ("google_cloud_run_v2_service", "api"),
        ("google_cloud_run_v2_job", "ops"),
    ):
        block = re.search(rf'resource "{kind}" "{label}"\s*\{{(.*?)\n\}}', text, re.S)
        assert block, f"the module must define {kind}.{label}"
        if not re.search(r"deletion_protection\s*=\s*var\.deletion_protection", block.group(1)):
            missing.append(f"{kind}.{label}")

    assert missing == [], (
        f"these must honour var.deletion_protection or terraform destroy cannot "
        f"remove them: {missing}"
    )


# APIs the documented deploy steps call, beyond the ones the module declares.
# `gcloud builds submit` needs both, and neither was listed, so Step 1 failed
# on a project where they were genuinely off:
#   PERMISSION_DENIED: Identity and Access Management (IAM) API has not been
#   used in project <project> before or it is disabled.
REQUIRED_DEPLOY_APIS = (
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
)


def test_the_deploy_guide_enables_every_api_its_own_steps_need() -> None:
    """The prerequisite list has to cover the commands that follow it.

    This is only reachable on a project where the APIs start disabled. Most
    projects have `iam` and `cloudbuild` on incidentally, so the documented
    list worked nearly everywhere and failed for exactly the reader the page
    is written for: someone starting from an empty project.
    """
    guide = (REPO_ROOT / "docs" / "deploy-gcp.md").read_text(encoding="utf-8")

    missing = [api for api in REQUIRED_DEPLOY_APIS if api not in guide]

    assert missing == [], (
        f"docs/deploy-gcp.md must enable every API its steps call; missing: {missing}"
    )


def test_the_ops_job_example_names_a_path_the_image_contains() -> None:
    """An ops example must not name a path excluded from every image.

    `run_ingest_example` printed
    `--args='ingest,--manifest,data/demo/manifest.jsonl'`, and `data/` is
    deliberately excluded from the build context so a private corpus cannot
    be uploaded into an image. Running it verbatim gave:

        FileNotFoundError: 'data/demo/manifest.jsonl'

    `load_manifest` takes a `Path` and calls `read_text`. The supported deployed
    path is therefore the read-only bucket mount, not an image path or a
    product-level `gs://` URI.
    """
    raw = (REPO_ROOT / "infra" / "terraform" / "outputs.tf").read_text(encoding="utf-8")
    # Comments may name the bad path while explaining it. What Terraform
    # actually prints is what a reader copies, so judge only that.
    emitted = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))

    assert "data/demo/manifest.jsonl" not in emitted, (
        "the image has no data/ directory; an example naming it always fails"
    )
    assert "corpus" in emitted.lower(), "the corpus bucket's purpose must be documented somewhere"


def test_the_ops_job_mounts_the_corpus_bucket_read_only() -> None:
    """The ops job can read a staged corpus without widening runtime access."""
    text = MAIN.read_text(encoding="utf-8")
    job = re.search(r'resource "google_cloud_run_v2_job" "ops"\s*\{(.*?)\n\}', text, re.S)
    service = re.search(r'resource "google_cloud_run_v2_service" "api"\s*\{(.*?)\n\}', text, re.S)

    assert job, "the module must define google_cloud_run_v2_job.ops"
    assert service, "the module must define google_cloud_run_v2_service.api"
    assert re.search(
        r'volume_mounts\s*\{\s*name\s*=\s*"corpus"\s*mount_path\s*=\s*"/corpus"\s*\}',
        job.group(1),
        re.S,
    ), "the ops container must mount the corpus volume at /corpus"
    assert re.search(
        r'volumes\s*\{\s*name\s*=\s*"corpus"\s*gcs\s*\{\s*'
        r"bucket\s*=\s*google_storage_bucket\.corpus\.name\s*"
        r"read_only\s*=\s*true\s*\}\s*\}",
        job.group(1),
        re.S,
    ), "the ops job must mount the Terraform corpus bucket read-only"
    assert "/corpus" not in service.group(1), "the REST and MCP service must not mount the corpus"
    assert re.search(r'google\s*=\s*\{.*?version\s*=\s*">= 7\.0"', text, re.S), (
        "the GA Cloud Run job GCS volume needs Google provider 7 or newer"
    )
    assert "launch_stage" not in job.group(1), "the GA volume must not use a preview launch stage"

    storage_roles = set(re.findall(r'role\s*=\s*"(roles/storage\.[^"]+)"', text))
    assert storage_roles == {"roles/storage.objectViewer"}, (
        "the runtime identity may only read corpus objects; "
        f"found storage roles: {sorted(storage_roles)}"
    )

    guide = GUIDE.read_text(encoding="utf-8")
    assert "Google provider 7.0 or newer" in guide
    assert "terraform init -upgrade" in guide, (
        "operators with an older local lock must be told how to select the GA volume schema"
    )
    assert "bucket-scoped\n  `roles/storage.objectViewer` for the corpus" in guide, (
        "the guide must include the runtime identity's read-only bucket grant"
    )


def test_the_ingest_example_uses_the_mounted_manifest() -> None:
    """The emitted ops command points at the path Cloud Run now mounts."""
    text = OUTPUTS.read_text(encoding="utf-8")
    output = re.search(r'output "run_ops_job_example"\s*\{(.*?)\n\}', text, re.S)

    assert output, "infra/terraform/outputs.tf must keep run_ops_job_example"
    value = output.group(1)
    assert "--args='ingest,--manifest,/corpus/manifest.jsonl'" in value, (
        "run_ops_job_example must ingest the manifest mounted at /corpus"
    )
    assert "data/demo" not in value, "the emitted command must not name an image-only path"
    assert "gs://" not in value, "the package contract remains a local filesystem path"

    purpose = re.search(r'output "corpus_bucket_purpose"\s*\{(.*?)\n\}', text, re.S)
    assert purpose, "infra/terraform/outputs.tf must describe the corpus bucket"
    assert "mounted read-only at /corpus in the ops job" in purpose.group(1), (
        "the bucket output must describe the path and its read-only runtime boundary"
    )


def test_corpus_deletion_is_explicit_and_safe_by_default() -> None:
    """Deleting live or recoverable corpus objects requires explicit inputs."""
    variables = VARIABLES.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    force = re.search(r'variable "force_destroy_corpus"\s*\{(.*?)\n\}', variables, re.S)
    retention = re.search(
        r'variable "corpus_soft_delete_retention_seconds"\s*\{(.*?)\n\}',
        variables,
        re.S,
    )

    assert force, "force_destroy_corpus must be an explicit module input"
    assert re.search(r"default\s*=\s*false", force.group(1)), (
        "a normal destroy must refuse to erase a populated corpus bucket"
    )
    assert retention, "corpus_soft_delete_retention_seconds must be an explicit input"
    assert re.search(r"default\s*=\s*604800", retention.group(1)), (
        "normal deployments must retain seven days of soft-delete recovery"
    )
    assert re.search(
        r"condition\s*=\s*var\.corpus_soft_delete_retention_seconds\s*==\s*0\s*"
        r"\|\|\s*\(\s*var\.corpus_soft_delete_retention_seconds\s*>=\s*604800\s*"
        r"&&\s*var\.corpus_soft_delete_retention_seconds\s*<=\s*7776000\s*\)",
        retention.group(1),
        re.S,
    ), "soft delete must allow only disabled or the supported 7-to-90-day range"

    bucket = re.search(r'resource "google_storage_bucket" "corpus"\s*\{(.*?)\n\}', main, re.S)
    assert bucket, "the module must define google_storage_bucket.corpus"
    assert re.search(r"force_destroy\s*=\s*var\.force_destroy_corpus", bucket.group(1))
    assert re.search(
        r"soft_delete_policy\s*\{\s*retention_duration_seconds\s*=\s*"
        r"var\.corpus_soft_delete_retention_seconds\s*\}",
        bucket.group(1),
        re.S,
    )
    assert re.search(r"versioning\s*\{\s*enabled\s*=\s*true\s*\}", bucket.group(1), re.S)

    guide = GUIDE.read_text(encoding="utf-8")
    bash_blocks = "\n".join(re.findall(r"```bash\n(.*?)```", guide, re.S))
    for setting in (
        "deletion_protection=false",
        "force_destroy_corpus=true",
        "corpus_soft_delete_retention_seconds=0",
    ):
        assert setting in bash_blocks, f"the reviewed teardown update must set {setting}"
    update_plan = guide.index("terraform plan -out=teardown-update.tfplan")
    update_apply = guide.index("terraform apply teardown-update.tfplan")
    destroy_plan = guide.index("terraform plan -destroy -out=destroy.tfplan")
    destroy_apply = guide.index("terraform apply destroy.tfplan")
    assert update_plan < update_apply < destroy_plan < destroy_apply, (
        "protection changes and destruction need separate reviewed saved plans"
    )
    assert "verified backup" in guide.lower()
    assert "does not purge objects already soft-deleted" in guide


def test_populated_database_destroy_order_is_deterministic() -> None:
    """Terraform removes active consumers, the database, and then its owner."""
    text = MAIN.read_text(encoding="utf-8")
    database = re.search(r'resource "google_sql_database" "sci_rag"\s*\{(.*?)\n\}', text, re.S)
    database_url = re.search(r'database_url\s*=\s*"([^"]+)"', text)

    assert database, "the module must define google_sql_database.sci_rag"
    assert re.search(
        r"depends_on\s*=\s*\[\s*google_sql_user\.sci_rag\s*\]", database.group(1), re.S
    ), "the database must be destroyed before the role that owns its migrated objects"
    assert database_url, "the module must construct the async database URL"
    assert "${google_sql_user.sci_rag.name}" in database_url.group(1), (
        "the URL must depend on the concrete Terraform user resource"
    )
    assert "${google_sql_database.sci_rag.name}" in database_url.group(1), (
        "the URL must depend on the concrete Terraform database resource"
    )

    for kind, label in (
        ("google_cloud_run_v2_service", "api"),
        ("google_cloud_run_v2_job", "ops"),
    ):
        consumer = re.search(rf'resource "{kind}" "{label}"\s*\{{(.*?)\n\}}', text, re.S)
        assert consumer, f"the module must define {kind}.{label}"
        # Membership, not an exact list. This asserted a single-element
        # `depends_on` and so failed when the #284 drain window was added
        # alongside it, even though the ordering it cares about was unchanged.
        # The contract is that this edge exists, not that it is the only one.
        depends_on = re.search(r"depends_on\s*=\s*\[(.*?)\]", consumer.group(1), re.S)
        assert depends_on, f"{kind}.{label} must declare its destroy-order edges"
        assert "google_secret_manager_secret_version.database_url" in depends_on.group(1), (
            f"{kind}.{label} must close before the database URL secret version is removed"
        )


def test_the_deploy_guide_stages_the_path_its_ingest_command_reads() -> None:
    """The upload layout and mounted manifest path form one executable procedure."""
    guide = GUIDE.read_text(encoding="utf-8")
    bash_blocks = "\n".join(re.findall(r"```bash\n(.*?)```", guide, re.S))

    assert 'CORPUS_BUCKET="$(terraform output -raw corpus_bucket)"' in bash_blocks
    assert re.search(
        r"gcloud storage rsync --recursive --dry-run\s*\\?\s*data/demo\s+"
        r'"gs://\$\{CORPUS_BUCKET\}"',
        bash_blocks,
    ), "the guide must preview the additive demo-corpus upload"
    assert re.search(
        r"gcloud storage rsync --recursive\s*\\?\s*data/demo\s+"
        r'"gs://\$\{CORPUS_BUCKET\}"',
        bash_blocks,
    ), "the guide must preserve manifest.jsonl and fixture/ at the bucket root"
    assert "--delete-unmatched-destination-objects" not in bash_blocks, (
        "the upload procedure must not delete unmatched corpus objects"
    )
    assert "--args='ingest,--manifest,/corpus/manifest.jsonl'" in bash_blocks
    assert "--args='ingest,--manifest,data/demo/manifest.jsonl'" not in bash_blocks
    assert "relative to `manifest.jsonl`" in guide
    assert ".gcloudignore" in guide and ".dockerignore" in guide and "data/raw/" in guide
    assert "Rebuild and repush whenever your domain or corpus manifest changes." not in guide


def test_cloud_run_examples_use_the_platform_safe_api_key_header() -> None:
    """Application keys reach the kit without Cloud Run consuming them."""
    guide = GUIDE.read_text(encoding="utf-8")
    bash_blocks = "\n".join(re.findall(r"```bash\n(.*?)```", guide, re.S))

    assert '-H "X-API-Key: team-key"' in bash_blocks, (
        "the deployed authenticated request must use the application-key header"
    )
    assert "Authorization: Bearer team-key" not in bash_blocks, (
        "Cloud Run consumes Authorization before the request reaches the kit"
    )
    assert "same bearer key" not in guide, "remote MCP clients use the same application key"


def test_model_calls_do_not_inherit_the_infrastructure_region() -> None:
    """Where resources live and where models are served are different questions.

    The module set `SCI_RAG_GCP_LOCATION` to `var.region`, so a deployment in
    `us-central1` asked Vertex for the default generation model there. That
    model is served from `global`, so every graph extraction batch failed:

        404 NOT_FOUND. Publisher model `.../locations/us-central1/publishers/
        google/models/gemini-3.6-flash` was not found

    The job still exited before the failure surfaced as a stats change, so a
    deployed graph build reported success and wrote nothing. Reproduced live
    in the issue #189 qualification: the same model id answered 200 from
    `global` and 404 from `us-central1` in the same project.
    """
    text = MAIN.read_text(encoding="utf-8")

    for match in re.finditer(
        r'name\s*=\s*"SCI_RAG_GCP_LOCATION"\s*\n\s*value\s*=\s*([^\s]+)', text
    ):
        assert match.group(1) != "var.region", (
            "model calls must not inherit var.region; a region does not serve "
            "every model, and the default generation model is served from global"
        )

    default = re.search(
        r'variable "model_location".*?default\s*=\s*"([^"]+)"',
        VARIABLES.read_text(encoding="utf-8"),
        re.S,
    )
    assert default, "the module must expose a model_location input"
    assert default.group(1) == "global", (
        "default to the location that serves the kit's default model"
    )


def test_a_full_destroy_does_not_issue_a_racing_drop_database() -> None:
    """The DROP was the only thing standing between a destroy and success.

    A `terraform destroy` on a deployment that had served traffic failed:

        Error 400: failed to delete database sci_rag.
        Detail: pq: database "sci_rag" is being accessed by other users.

    Deleting a Cloud Run service returns before its instances stop dialling
    Postgres, so the DROP that followed raced them. Terraform had already
    removed the service, job, bucket, secrets, and service account, leaving a
    running Cloud SQL instance the error never mentions. Filed as #284.

    A destroy-time wait was tried first and rejected on evidence. Any fixed
    window is a guess, and a service stuck in a startup-probe retry loop keeps
    opening sessions for as long as it exists: a 90 second window cleared a
    healthy deployment and then lost to a crash-looping one on the very next
    destroy.

    Deleting the instance deletes the databases and roles it contains, so the
    separate DROP is redundant during a full destroy and contributes only a
    failure mode. ABANDON removes the call, and with it the race, by
    construction rather than by timing. The instance deletion is still
    Terraform's, so nothing here bypasses Terraform to reach the data.
    """
    text = MAIN.read_text(encoding="utf-8")

    for kind, label in (
        ("google_sql_database", "sci_rag"),
        ("google_sql_user", "sci_rag"),
    ):
        block = re.search(rf'resource "{kind}" "{label}"\s*\{{(.*?)\n\}}', text, re.S)
        assert block, f"the module must define {kind}.{label}"
        assert re.search(r'deletion_policy\s*=\s*"ABANDON"', block.group(1)), (
            f"{kind}.{label} must not issue its own delete during a full destroy; "
            "the instance deletion removes it, and the separate call races "
            "draining consumers"
        )

    assert re.search(
        r'resource "google_sql_database_instance" "db"[\s\S]*?deletion_protection\s*=\s*var\.deletion_protection',
        text,
    ), "the instance deletion is what actually removes the data, so it stays guarded"
