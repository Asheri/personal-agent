---
title: Configure Postgres backend
description: Choose and operate a supported PostgreSQL server with pgvector for Sci RAG Kit.
---

# Configure Postgres backend

Choose Docker, a local server, or Cloud SQL, then connect Sci RAG Kit to PostgreSQL with pgvector.
Use a disposable database for destructive tests.

<div class="srag-meta-strip">
  <div><strong>You'll build</strong>A running PostgreSQL 16 to 18 with pgvector</div>
  <div><strong>You'll need</strong>A project checkout and one server source</div>
  <div><strong>Time</strong>About 5 minutes locally, longer for first Cloud startup</div>
  <div><strong>Tested with</strong>v0.5</div>
</div>

## Before you start

| Requirement | Why | Check |
|---|---|---|
| A Sci RAG Kit checkout or generated project | `make setup` and the helper scripts live in it | `ls Makefile` |
| One supported environment manager | It supplies the command runner | uv, pixi, conda, or venv + pip was selected during setup |
| PostgreSQL 16 through 18 with pgvector | The application, migrations, and tests all need it | `psql --version` and `CREATE EXTENSION vector` |

`SCI_RAG_DB_BACKEND` selects the backend used by `make db-up`, `make db-down`, and `make setup`. Set it to `docker` for the Compose service or `local` for `scripts/local_postgres.py`.
<!-- BEGIN GENERATED PROJECT FEATURE: cloud-helper -->
Set it to `cloud` for the optional `scripts/cloud_postgres.py`.
<!-- END GENERATED PROJECT FEATURE: cloud-helper -->
Every project retains its supported backends, with one default selected by the environment manager. `SCI_RAG_DATABASE_URL` controls the application. `SCI_RAG_TEST_DATABASE_URL` controls the destructive test suite. Selecting a backend does not rewrite either URL.

## Recommended defaults

Docker is the template default and matches the PostgreSQL 16 service in CI. Generated pixi and conda projects default to `local` because their manifests bundle PostgreSQL and pgvector from conda-forge.

Any environment manager can select `local` when PostgreSQL 16 through 18 and pgvector are on `PATH`, including through Postgres.app. Advanced setup can retain the optional Cloud helper. Quick keeps the default and removes the helper.

| Environment manager | Default value | What launches | Also selectable |
|---|---|---|---|
| uv | `docker` | the Compose service | `local`, `cloud` |
| pixi | `local` | the bundled conda-forge server | `docker`, `cloud` |
| conda | `local` | the bundled conda-forge server | `docker`, `cloud` |
| venv + pip | `docker` | the Compose service | `local`, `cloud` |

`cloud` is selectable only in projects that retained the Cloud helper.

## Run Postgres in Docker

If you use the template checkout with no backend override, run:

```console title="Terminal"
$ make setup
```

This synchronizes dependencies, starts the selected backend, and applies migrations. With the default backend, Compose starts on port `5433`.

Generated pixi or conda projects default to the bundled server. To use Compose instead:

```console title="Terminal"
$ SCI_RAG_DB_BACKEND=docker make setup
```

Stop the backend when finished:

```console title="Terminal"
$ make db-down
```

<div class="srag-checkpoint" markdown>
**Checkpoint: the database is reachable**

Run `uv run sci-rag doctor`. The database and schema checks should report
healthy. An empty corpus is fine at this point.
</div>

## Run Postgres from conda-forge

Generated pixi and conda projects declare `postgresql` and `pgvector` in the manifest. Their Makefile sets `SCI_RAG_DB_BACKEND=local`, so `make setup` starts `scripts/local_postgres.py`:

```console title="Terminal"
$ make setup
```

The helper keeps data under `.pgdata/`, listens on loopback, and uses trust authentication. This is the machine-local development server. Do not use it for deployment.

```console title="Terminal"
$ make db-down
```

<div class="srag-checkpoint" markdown>
**Checkpoint: the server came from the selected manager**

`ls .pgdata` should show the data directory. `uv run sci-rag doctor` should
report a healthy database and current schema.
</div>

## Point at a system PostgreSQL

`local` runs `scripts/local_postgres.py` with the PostgreSQL installation on `PATH`, either the bundled conda-forge build or a user-installed system server. Any environment manager can use it when `initdb`, `pg_ctl`, and `psql` from PostgreSQL 16 through 18 are available.

Postgres.app is supported on macOS. Add its versioned `bin` directory to `PATH`, then run:

```console title="Terminal"
$ SCI_RAG_DB_BACKEND=local make setup
```

The helper creates the `sci_rag` database and enables pgvector. To use an existing compatible server, set the application URL and apply migrations:

```dotenv title="~/.env"
SCI_RAG_DATABASE_URL=postgresql+asyncpg://user:password@host:5432/sci_rag
```

```console title="Terminal"
$ uv sync
$ uv run sci-rag db upgrade
```

<div class="srag-checkpoint" markdown>
**Checkpoint: the schema is on the intended server**

`uv run sci-rag doctor` should report the expected host and a current schema.
An exported URL takes precedence over the value in `.env`.
</div>

<!-- BEGIN GENERATED PROJECT FEATURE: cloud-helper -->
## Share a Cloud SQL development instance

The optional Cloud helper isolates each workspace with its own development database, disposable test database, proxy process, and dynamic loopback port on one shared instance. Retain it with `sci-rag new --advanced` for a new project or `sci-rag init --advanced` for a checkout. Quick setup keeps Terraform and removes the helper.

Use this helper only for development. Follow [Deploy on Google Cloud](deploy-gcp.md) for a production-shaped deployment.
<!-- END GENERATED PROJECT FEATURE: cloud-helper -->

<!-- BEGIN GENERATED PROJECT FEATURE: cloud-provisioning -->
## One-time Cloud SQL provisioning

An operator performs this step once. It requires billing, `gcloud`, Application Default Credentials, Terraform, the Cloud SQL Auth Proxy, and `psql`.

The operator needs permission to create and update the Cloud SQL instance, create databases, connect through the proxy, read the password secret, and manage IAM bindings. Cloud SQL Editor plus access to one Secret Manager secret covers these operations.

Authenticate, then apply the development-only module with an explicit project:

```console title="Terminal"
$ gcloud auth login
$ gcloud auth application-default login
$ cd infra/terraform/dev-database
$ terraform init
$ terraform plan -out=dev-database.tfplan \
    -var "project_id=YOUR_PROJECT" \
    -var "instance_name=YOUR_INSTANCE" \
    -var "developer_principal=user:YOUR_EMAIL"
$ terraform show dev-database.tfplan     # read it before you apply it
$ terraform apply dev-database.tfplan
$ terraform output -raw sci_rag_cloud_pg_config
$ cd ../../..
```

Replace all three placeholders. `project_id` and `instance_name` have no defaults. If you omit either, Terraform stops at input validation before reading state, preventing the module from targeting an unnamed instance.

Read the saved plan before applying it. Every line should be a create. If it
changes or destroys an unexpected instance, stop and correct the inputs.

Terraform prints only non-secret helper settings, but Terraform state contains
the generated database password. Store the state as a credential and never
commit or paste it into an issue.

Advanced setup can retain the helper without the Terraform tree. Such a project
has no provisioning module. Connect it to an existing compatible instance, or
copy the development module from the upstream template before provisioning.

Save the printed settings where the helper reads them. The output is already
`KEY=VALUE` lines, so this is the whole configuration step:

```console title="Terminal"
$ terraform -chdir=infra/terraform/dev-database output -raw sci_rag_cloud_pg_config > .cloudsql/config.env
```

<div class="srag-checkpoint" markdown>
**Checkpoint: provisioning returned helper configuration**

The output names the project, instance, region, and database user. It contains
no database password.
</div>
<!-- END GENERATED PROJECT FEATURE: cloud-provisioning -->

<!-- BEGIN GENERATED PROJECT FEATURE: cloud-helper -->
## Start a Cloud SQL workspace

Configure the helper with the inputs below. The project and instance have no
defaults because `pause` and `resume` act on the named instance.

| Variable | Default | Purpose |
|---|---|---|
| `SCI_RAG_CLOUD_PG_PROJECT` | none; required | Google Cloud project containing the instance |
| `SCI_RAG_CLOUD_PG_INSTANCE` | none; required | Cloud SQL instance name |
| `SCI_RAG_CLOUD_PG_REGION` | `us-west1` | Instance region |
| `SCI_RAG_CLOUD_PG_DIR` | `.cloudsql` | Ignored workspace-local proxy and credential state |
| `SCI_RAG_CLOUD_PG_PORT` | `5433` | First loopback port to try; the helper chooses the next free port |
| `SCI_RAG_CLOUD_PG_WORKSPACE` | current directory name | Suffix for same-basename collision avoidance |
| `SCI_RAG_CLOUD_PG_USER` | `sci_rag` | Shared PostgreSQL role |
| `SCI_RAG_CLOUD_PG_CONFIG` | `.cloudsql/config.env` | File holding any of the above as `KEY=VALUE` lines |

The configuration file holds one `KEY=VALUE` line per setting, which is the
format provisioning prints:

```dotenv title="~/.cloudsql/config.env"
SCI_RAG_CLOUD_PG_PROJECT=your-project
SCI_RAG_CLOUD_PG_INSTANCE=your-instance
SCI_RAG_CLOUD_PG_REGION=us-west1
SCI_RAG_CLOUD_PG_USER=sci_rag
```

An exported variable overrides the file. To share one instance across several
checkouts without configuring each one, point `SCI_RAG_CLOUD_PG_CONFIG` at a
path outside the checkouts. Without both a project and an instance, every
helper command prints the missing settings and exits nonzero.

The helper normalizes the workspace name into `sci_rag_<workspace>` and `sci_rag_test_<workspace>`. Override `SCI_RAG_CLOUD_PG_WORKSPACE` when two checkouts have the same basename.

The database pair and local proxy state prevent accidental URL and destructive-test collisions. Every database shares the same PostgreSQL role. Treat the separation as workspace isolation only.

Start the backend and print both secret-free URLs:

```console title="Terminal"
$ SCI_RAG_DB_BACKEND=cloud make db-up
$ uv run python scripts/cloud_postgres.py config
```

`start` resumes a paused instance, creates the development and test databases, starts the proxy on a free port at or above `5433`, and enables pgvector. The first start can take several minutes while Cloud SQL activates.

Record both printed URLs in an owner-only `.env`, then run migrations:

```console title="Terminal"
$ chmod 600 .env
$ uv run sci-rag db upgrade
```

<div class="srag-checkpoint" markdown>
**Checkpoint: this workspace owns its proxy state**

`uv run python scripts/cloud_postgres.py status` names the normalized database, dynamic port, and running proxy. `uv run sci-rag doctor` reports a healthy database and schema.
</div>

## Manage the Cloud SQL lifecycle

| Action | Scope and effect |
|---|---|
| `config` | Prints resolved non-secret settings and both passwordless URLs; it starts nothing |
| `start` | Resumes if needed, creates both workspace databases, starts the proxy, and enables pgvector |
| `status` | Reports instance and current workspace proxy state without changing either |
| `stop` | Stops only the current workspace proxy; `make db-down` dispatches here |
| `pause` | Stops this proxy and pauses the shared instance; it affects every workspace |
| `resume` | Changes the shared instance activation policy to running; `start` is still the workspace startup command |

`stop` and Conductor archive do not delete a database. Only the shared-instance operator should use `pause` and `resume`, which affect every workspace. Normal cleanup runs `make db-down` and stops only the current workspace proxy.

The instance has public IPv4 enabled with no authorized networks. Connections use IAM authorization and TLS through the Cloud SQL Auth Proxy. Backups and deletion protection are disabled by default. This development instance must not hold the only copy of a valuable corpus.

## Use Cloud SQL in Conductor workspaces

The kit does not ship or enable this user-installed, machine-local Conductor configuration. Store `.conductor/settings.local.toml` and the wrapper scripts in the Conductor root clone, outside the worktrees. The settings call them through `$CONDUCTOR_ROOT_PATH`:

```toml title="~/.conductor/settings.local.toml"
"$schema" = "https://conductor.build/schemas/settings.repo.schema.json"

[environment_variables.local]
# One file outside every worktree, so a new workspace needs no extra step.
SCI_RAG_CLOUD_PG_CONFIG = "~/.config/sci-rag/cloud-pg.env"

[scripts]
setup = '"$CONDUCTOR_ROOT_PATH/.conductor/setup-cloud-workspace.sh"'
archive = '"$CONDUCTOR_ROOT_PATH/.conductor/archive-cloud-workspace.sh"'
run_mode = "concurrent"

[scripts.run.serve]
command = 'uv run sci-rag serve --port "$CONDUCTOR_PORT"'
available_in = ["local"]
default = true
icon = "play"

[scripts.run.test]
command = '"$CONDUCTOR_ROOT_PATH/.conductor/run-cloud-tests.sh"'
available_in = ["local"]
icon = "test-tube"
```

The setup wrapper synchronizes dependencies, starts or verifies the proxy, writes both secret-free URLs to an owner-only `.env`, and applies migrations. Replace the placeholders with non-secret Cloud settings:

```bash title="~/.conductor/setup-cloud-workspace.sh"
#!/bin/bash
set -euo pipefail
umask 077
export SCI_RAG_DB_BACKEND=cloud
export SCI_RAG_CLOUD_PG_PROJECT="YOUR_PROJECT"
export SCI_RAG_CLOUD_PG_INSTANCE="YOUR_INSTANCE"
export SCI_RAG_CLOUD_PG_REGION="YOUR_REGION"
export SCI_RAG_CLOUD_PG_USER="YOUR_DATABASE_USER"

uv sync --group docs --group docs-test
make db-up
config="$(uv run python scripts/cloud_postgres.py config)"
dev_url="$(printf '%s\n' "$config" | sed -n 's/^SCI_RAG_DATABASE_URL=//p')"
test_url="$(printf '%s\n' "$config" | sed -n 's/^SCI_RAG_TEST_DATABASE_URL=//p')"
test -n "$dev_url" && test -n "$test_url"

touch .env
chmod 600 .env
tmp="$(mktemp "${TMPDIR:-/tmp}/sci-rag-env.XXXXXX")"
grep -vE '^SCI_RAG_(DATABASE|TEST_DATABASE)_URL=' .env > "$tmp" || true
printf 'SCI_RAG_DATABASE_URL=%s\nSCI_RAG_TEST_DATABASE_URL=%s\n' \
  "$dev_url" "$test_url" >> "$tmp"
mv "$tmp" .env
SCI_RAG_DATABASE_URL="$dev_url" uv run sci-rag db upgrade
```

The test wrapper exports only the disposable test URL to the test process:

```bash title="~/.conductor/run-cloud-tests.sh"
#!/bin/bash
set -euo pipefail
config="$(uv run python scripts/cloud_postgres.py config)"
export SCI_RAG_TEST_DATABASE_URL="$(printf '%s\n' "$config" | \
  sed -n 's/^SCI_RAG_TEST_DATABASE_URL=//p')"
test -n "$SCI_RAG_TEST_DATABASE_URL"
exec uv run pytest "$@"
```

Archive must stop only this workspace proxy. It must not pause the shared
instance or delete any database:

```bash title="~/.conductor/archive-cloud-workspace.sh"
#!/bin/bash
set -euo pipefail
export SCI_RAG_DB_BACKEND=cloud
make db-down
```

<div class="srag-checkpoint" markdown>
**Checkpoint: parallel workspaces stay isolated**

Each workspace `.env` contains a different normalized development and test database pair, and each workspace may use a different proxy port. Archiving one workspace leaves every other proxy and the shared instance running.
</div>
<!-- END GENERATED PROJECT FEATURE: cloud-helper -->

## Use a disposable test database

The integration and server fixtures drop and recreate application tables in `SCI_RAG_TEST_DATABASE_URL`, then truncate them between tests. Point that URL at a disposable database. A skipped database suite does not pass.

```dotenv title="~/.env"
SCI_RAG_TEST_DATABASE_URL=postgresql+asyncpg://sci_rag:sci_rag@localhost:5433/sci_rag_test
```

## Confirm the supported versions

Supported servers are PostgreSQL 16 through 18. CI proves 16 through the
container service and the Docker-free workflow proves the current conda-forge
resolution, PostgreSQL 18, on Linux and Apple silicon. [ADR 0008](adr/0008-supported-postgresql-versions.md)
records the range and its reversal conditions.

## Next steps

- Ingest the demo corpus and inspect retrieval: [Quickstart](quickstart.md)
- Diagnose a database that will not start: [Troubleshooting](troubleshooting.md)
- Back up, snapshot, and restore a corpus: [Operate a live corpus](operations.md)
