---
title: Deploy on Google Cloud
description: Provision Cloud SQL and Cloud Run from the included Terraform, stage a corpus through a read-only bucket mount, then verify the deployed service and remove it.
---

# Deploy on Google Cloud

Provision a Cloud Run service backed by Cloud SQL with pgvector, stage a corpus
outside the image through a read-only bucket mount, verify the deployed service,
and remove it through reviewed protection-update and destroy plans.

<div class="srag-meta-strip">
  <div><strong>You'll build</strong>One Cloud Run service and one Cloud SQL instance</div>
  <div><strong>You'll need</strong>A Google Cloud project and billing enabled</div>
  <div><strong>Time</strong>Depends on provisioning and organization policy</div>
  <div><strong>Cost</strong>Varies by region and selected resource tiers; charges continue until teardown</div>
  <div><strong>Tested with</strong>v0.5</div>
</div>

!!! note "Terraform is optional"

    Generated projects include the production Terraform module by default. To
    change that choice, run `sci-rag new --advanced` for a new project or
    `sci-rag init --advanced` in an existing checkout. Choosing `No` for
    `include_terraform` removes `infra/terraform/` and its CI job. You can
    restore both from
    [the template](https://github.com/sustainability-software-lab/sci-rag-kit/tree/main/infra/terraform)
    later.

The kit ships Terraform under `infra/terraform/` for Cloud SQL with pgvector, one
Cloud Run service for REST and MCP, an operations job, a corpus bucket, secrets, and a
least-privilege service account.

<!-- BEGIN GENERATED PROJECT FEATURE: cloud-provisioning -->
!!! warning "The development database is a different module"

    `infra/terraform/dev-database/` provisions a shared, pausable development
    instance for laptop access through the Cloud SQL Auth Proxy. The
    `scripts/cloud_postgres.py` creates workspace-scoped databases dynamically.
    The development module disables backups and deletion
    protection by default. Never point a deployment at it. This page uses the production-shaped path.
<!-- END GENERATED PROJECT FEATURE: cloud-provisioning -->

These resources accrue charges while they run. Review the selected tiers and region in the saved
Terraform plan, and tear down experiments through the reviewed teardown in Step 5.

## Before you start

* A Google Cloud project with billing enabled and `gcloud` authenticated
  (`gcloud auth login` plus `gcloud auth application-default login`).
* APIs enabled once per project:

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com cloudbuild.googleapis.com \
  storage.googleapis.com iam.googleapis.com --project=YOUR_PROJECT
```

* Terraform 1.5+ and Google provider 7.0 or newer. Provider 7 is the first
  supported major where the Cloud Run job GCS volume is generally available,
  so the module does not need a preview launch stage.

## Step 1: build and push the image

```bash
gcloud artifacts repositories create sci-rag --repository-format=docker \
  --location=us-central1 --project=YOUR_PROJECT   # once

gcloud builds submit --project=YOUR_PROJECT \
  --tag us-central1-docker.pkg.dev/YOUR_PROJECT/sci-rag/sci-rag:v1 .
```

The Dockerfile packages the kit, the `domain/` folder, and migrations, so the
same image serves the API and runs schema upgrades.
Rebuild and repush when package code, migrations, or your domain profile
changes. Upload corpus changes to the bucket after deployment; they do not
require a new image.

!!! warning "The trailing dot uploads the directory"

    `gcloud builds submit ... .` sends the current directory to Cloud Build. `.gcloudignore` and `.dockerignore` control what is sent. Both allow only: `pyproject.toml`, `uv.lock`, `README.md`, `alembic.ini`, `src/`, `domain/`, `migrations/`, and `Dockerfile`.

    Credentials, `.env` files, Terraform state, and restricted papers stay safe by default. The corpus in `data/raw/` is excluded. If you add a `COPY` to the Dockerfile, add its source to both manifests. `tests/unit/test_build_context.py` enforces this.

    Do not delete `.gcloudignore` to upload everything. Without it, gcloud falls back to `.gitignore`, which misses entries in `.git/info/exclude`.

## Step 2: terraform apply

```bash
cd infra/terraform
terraform init
terraform apply \
  -var project_id=YOUR_PROJECT \
  -var image=us-central1-docker.pkg.dev/YOUR_PROJECT/sci-rag/sci-rag:v1
```

The tracked lockfile already pins a provider that satisfies the declared range,
so plain `terraform init` is enough. Run `terraform init -upgrade` only if your
local lock still points at provider 5 or 6, and review the provider selection
before applying. Treat a lockfile update as its own dependency change, not as an
automatic part of this deployment procedure.

What you get, and the security posture you get it with:

* The database is reachable only through the Cloud SQL connector (mounted as a Unix socket), never via open TCP.
* The runtime service account holds the project roles `roles/cloudsql.client` and
  `roles/aiplatform.user`, read access to two secrets, and bucket-scoped
  `roles/storage.objectViewer` for the corpus.
* Send API keys as `X-API-Key: <key>`. Cloud Run's frontend claims `Authorization: Bearer` for its own identity tokens, so use the alternate header.
* The Cloud Run service is private by default. Pass `-var allow_unauthenticated=true` to make API keys the only gate.

## Step 3: stage the corpus and populate the database

```bash
CORPUS_BUCKET="$(terraform output -raw corpus_bucket)"

# Preview an additive upload of the tracked, synthetic CC0 demo:
gcloud storage rsync --recursive --dry-run \
  data/demo "gs://${CORPUS_BUCKET}" --project=YOUR_PROJECT

# Apply the same additive upload after reviewing the preview:
gcloud storage rsync --recursive \
  data/demo "gs://${CORPUS_BUCKET}" --project=YOUR_PROJECT

# Create the schema (terraform output prints this exact command):
gcloud run jobs execute sci-rag-ops --region=us-central1 --project=YOUR_PROJECT --wait

# Ingest through the bucket mounted read-only in the ops job:
gcloud run jobs execute sci-rag-ops --region=us-central1 --project=YOUR_PROJECT \
  --args='ingest,--manifest,/corpus/manifest.jsonl' --wait

# Build the graph:
gcloud run jobs execute sci-rag-ops --region=us-central1 --project=YOUR_PROJECT \
  --args='graph,extract' --wait
gcloud run jobs execute sci-rag-ops --region=us-central1 --project=YOUR_PROJECT \
  --args='graph,communities' --wait
gcloud run jobs execute sci-rag-ops --region=us-central1 --project=YOUR_PROJECT \
  --args='stats' --wait
```

The upload copies everything under `data/demo` to the bucket root, so
`manifest.jsonl`, `fixture/`, and the `graph-replay/` evaluation fixture all
land there. Ingest reads only the manifest and the paths it names. Every
document path stays relative to `manifest.jsonl`, so `fixture/example.md`
appears as `/corpus/fixture/example.md` in the ops job. The command is additive:
it copies new and changed objects without deleting unmatched objects already in
the bucket. Do not add `--delete-unmatched-destination-objects` unless a separate
review has approved those deletions.

Cloud Run supplies the read-only `/corpus` mount. The runtime service account
can view objects but cannot create or delete them, and the REST/MCP service has
no corpus mount. Keep the build-context exclusions above; a private corpus never
needs to enter the image or writable container storage.

## Step 4: set API keys and verify

```bash
echo '{"team-key": {"scopes": ["retrieval:query", "retrieval:answer", "corpus:read"]}}' | \
  gcloud secrets versions add sci-rag-api-keys --data-file=- --project=YOUR_PROJECT
# New secret versions are picked up on the next Cloud Run revision or restart.

URL=$(terraform output -raw service_url)
curl -s $URL/health
curl -s $URL/v1/corpus-manifest -H "X-API-Key: team-key"
curl -s -X POST $URL/v1/query -H "X-API-Key: team-key" \
  -H 'Content-Type: application/json' -d '{"query": "rice straw availability"}'
```

Run the query only after the corpus upload and operations jobs have succeeded.
Remote agents connect to `$URL/mcp/` with the same application key in
`X-API-Key`.

## Step 5: review and apply teardown

Three independent controls protect data and running resources:

* `deletion_protection` defaults to `true` for the database, service, and ops
  job.
* `force_destroy_corpus` defaults to `false`, so Terraform refuses to remove a
  bucket that still has live or noncurrent object generations.
* `corpus_soft_delete_retention_seconds` defaults to `604800`, which keeps
  deleted objects recoverable for seven days. It accepts `0` only as an
  explicit choice, or a value from 7 through 90 days.

!!! danger "Permanent corpus deletion needs its own review"

    Have a verified backup before changing either corpus protection to its
    destructive value. A disposable run that requires final, unrecoverable
    absence sets soft delete to `0` before its first upload. Disabling soft
    delete later does not purge objects already soft-deleted under the earlier
    policy.

Save and inspect an update plan before changing the protections. The image
value must match the deployed revision even though this plan does not replace
it.

```bash
terraform plan -out=teardown-update.tfplan \
  -var project_id=YOUR_PROJECT \
  -var image=us-central1-docker.pkg.dev/YOUR_PROJECT/sci-rag/sci-rag:v1 \
  -var deletion_protection=false \
  -var force_destroy_corpus=true \
  -var corpus_soft_delete_retention_seconds=0
terraform show teardown-update.tfplan

# Apply only after the update plan has been reviewed:
terraform apply teardown-update.tfplan
```

Then save and inspect a separate destroy plan with the same explicit inputs.

```bash
terraform plan -destroy -out=destroy.tfplan \
  -var project_id=YOUR_PROJECT \
  -var image=us-central1-docker.pkg.dev/YOUR_PROJECT/sci-rag/sci-rag:v1 \
  -var deletion_protection=false \
  -var force_destroy_corpus=true \
  -var corpus_soft_delete_retention_seconds=0
terraform show destroy.tfplan

# Apply only after the destroy plan has been reviewed separately:
terraform apply destroy.tfplan
```

The update plan is not optional, and not only for review. Terraform reads
`deletion_protection`, `force_destroy`, and the database `deletion_policy` from
the state it already has, not from the variables you pass to a destroy. Passing
them for the first time on the destroy leaves the stored values in force and the
destroy stops partway. The update plan is what writes them into state.

The database and its role use `deletion_policy = "ABANDON"`, so a destroy does
not issue its own `DROP DATABASE`. Deleting the instance removes the databases
and roles inside it, and the separate drop raced Cloud Run instances that were
still closing their Postgres sessions. Removing only the database block from
your configuration therefore leaves the database in place rather than dropping
it.

If either apply fails, keep the Terraform state and saved plans, then inventory
every surviving resource. Do not delete the Cloud SQL instance directly or
discard state to make the next plan look clean. Correct the configuration,
save a new reviewed plan, and resume from the recorded survivors.

## Operating notes

* **Scale to zero** is on (`min_instance_count = 0`). The first request after
  idle pays a cold start. Set to 1 for an always-warm instance.
* **Schema changes**: rebuild the image, run `terraform apply` for the new
  revision, then run the ops job once. Migrations are additive Alembic
  revisions; follow the pattern in `migrations/versions/0001_initial.py`.
* **External license posture**: if the service is public-facing, require
  clients to pin `license_classes` to `["public", "open_commercial"]`. Create
  keys whose scope omits `corpus:read` for outsiders.
* **Teardown**: use the two reviewed saved plans in Step 5. A bare
  `terraform destroy` cannot show whether every protection change was reviewed.

<div class="srag-checkpoint" markdown>
**Checkpoint: the deployed service answers**

A `POST /v1/query` against the Cloud Run URL returns scoped results with
citations, `/v1/corpus-manifest` lists the documents you ingested, and
the update and destroy plans account for every protected resource before you
apply either one.
</div>

## Next steps

- Lock down what an external caller can reach: [Scope precedes ranking](methodology.md#7-scope-precedes-ranking)
- Back up the Cloud SQL instance before the first migration: [Operate a live corpus](operations.md)
- Wire a client to the deployed endpoints: [REST, MCP, and Python API](api.md)
