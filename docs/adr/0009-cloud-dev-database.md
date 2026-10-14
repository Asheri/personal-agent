---
title: "ADR 0009: A shared Cloud SQL instance with workspace databases"
description: Why the optional Cloud SQL development backend shares an instance while isolating each workspace's data and local proxy.
---

# ADR 0009: A shared Cloud SQL instance with workspace databases

Sci RAG Kit can use one managed development instance without making workspaces share databases, proxy state, or ports.

**Status:** accepted

## Context

The default development database is one `pgvector/pgvector:pg16` container.
On macOS, Docker Desktop keeps a Linux VM resident even though this project
needs only PostgreSQL. Parallel Conductor workspaces also share Docker's
container-name and host-port namespace, so they collide on `sci-rag-db` and
port 5433.

[ADR 0008](0008-supported-postgresql-versions.md) added a Docker-free local
server for pixi and conda. That path is fast and inexpensive, and a system
PostgreSQL with pgvector, including Postgres.app, can drive the same helper.
It does not provide a centrally managed backend for developers who prefer one,
and each local cluster still owns its own disk and lifecycle.

Cloud SQL can share one PostgreSQL instance while giving each workspace its
own logical development and test databases. The test database distinction is
a safety boundary because the integration and server fixtures drop, recreate,
and truncate application tables.

The original proposal used private IP only. The Cloud SQL Auth Proxy provides
IAM authorization and TLS, but it does not create a network route. A proxy on
a laptop can reach a private address only through an existing VPN,
Interconnect, or in-VPC intermediary. The target project has none, and adding
one would make the development module substantially larger than the database.

The required helper verbs also exceed `roles/cloudsql.client`. Connectivity
needs `cloudsql.instances.connect`, but creating per-workspace databases needs
`cloudsql.databases.create`, and pause/resume needs
`cloudsql.instances.update`. Cloud SQL Editor contains those permissions.

## Decision

Add `SCI_RAG_DB_BACKEND=docker|local|cloud`, with `docker` as the template
default. `make db-up` and `make db-down` dispatch to the selected backend.
Generated pixi and conda projects retain their existing local-server default;
all four environment managers may opt into the cloud helper.

This supersedes ADR 0008's narrower statement that uv and venv+pip cannot
offer the local helper. They still cannot bundle a PostgreSQL server from
PyPI, but they can now select `local` when a supported system PostgreSQL and
pgvector are already on PATH.

<!-- BEGIN GENERATED PROJECT FEATURE: cloud-helper -->
`scripts/cloud_postgres.py` manages one workspace only:

* The directory name is normalized into `sci_rag_<workspace>` and
  `sci_rag_test_<workspace>` database names.
* A free loopback port is selected at or above 5433 and persisted with the
  proxy PID under `.cloudsql/`.
* `start` resumes the instance, creates missing databases, fetches the database
  password once, starts the proxy, waits for readiness, and enables pgvector in
  both databases. Repeating it is safe.
* `stop` terminates only the workspace-local PID whose command line matches the
  shared instance connection name. It never pauses the shared instance.
* `pause` stops this workspace's proxy and sets activation policy `NEVER`.
  `resume` sets `ALWAYS`. These verbs are explicit because they affect every
  workspace using the shared instance. Terraform ignores only activation
  policy drift because the helper deliberately owns that operational field.
* `config` prints resolved non-secret settings and passwordless asyncpg URLs.
  Each URL references a mode-0600 pgpass file, so a paste-ready
  `SCI_RAG_DATABASE_URL=` line does not expose the generated password.
<!-- END GENERATED PROJECT FEATURE: cloud-helper -->

<!-- BEGIN GENERATED PROJECT FEATURE: cloud-provisioning -->
Provision the instance through the independent
`infra/terraform/dev-database/` module. The module takes `project_id` and
`instance_name` as required inputs with no defaults, so it cannot reach an
instance the operator did not name. It uses PostgreSQL 16 on
the Enterprise edition's `db-g1-small` shared-core tier, zonal availability,
no backups, and deletion protection off by default. These are development
cost choices, not production defaults. The edition is explicit because the
Cloud SQL API's current PostgreSQL 16 default is Enterprise Plus, which does
not accept shared-core tiers.

The instance has public IPv4 enabled with no authorized networks. Direct
database connections are not admitted. Developers connect through the Cloud
SQL Auth Proxy, which requires Google credentials, IAM authorization, and TLS.
The Terraform IAM binding grants Cloud SQL Editor under a resource-name
condition limited to the instance this module creates; secret accessor is
granted only on that instance's password secret. Every other Cloud SQL
instance in the project, production included, is outside the condition.
<!-- END GENERATED PROJECT FEATURE: cloud-provisioning -->

<!-- BEGIN GENERATED PROJECT FEATURE: cloud-helper -->
The live test is opt-in under `pytest.mark.cloud` and
`SCI_RAG_RUN_CLOUD_TESTS=1`. CI does not hold project credentials. Offline unit
tests use controlled fake binaries to prove lifecycle, isolation, and secret
handling without contacting Google.
<!-- END GENERATED PROJECT FEATURE: cloud-helper -->

## Measured latency

Both accepted timings use the same working tree, Python environment, 64
dimensional deterministic embedder, and 145-test selection. Neither run
skipped a database test. Two database-independent CLI subprocess tests were
deselected from both runs because this heavily loaded Mac repeatedly exceeded
their fixed 30-second process timeout. They are not counted as passes here.

| Backend | Command | Result | Wall time |
| --- | --- | --- | --- |
| Postgres.app 16 | `time uv run pytest tests/integration tests/server -q` with the two CLI tests deselected | 145 passed, 2 deselected in 203.89s | 228.43s |
| Cloud SQL | `SCI_RAG_DB_BACKEND=cloud time uv run pytest tests/integration tests/server -q` with the workspace test URL exported and the same two deselections | 145 passed, 2 deselected in 809.60s | 832.86s |

Cloud SQL was 3.65 times slower by wall clock in this matched run. An earlier
Docker baseline attempt was invalid: the same two fixed-timeout subprocess
tests failed while the 10 GiB Docker VM and severe swap pressure were still
present, so its timing is intentionally not reported as a benchmark result.

Each fixture transaction and table reset becomes a WAN round trip on Cloud
SQL. `pool_pre_ping=True` would add another query on every checkout, so this
change does not alter `src/sci_rag/db/engine.py`. If the measured gap harms the
loop, pooling and fixture batching need their own matched benchmark and review.

## Consequences

Docker is no longer required for the full development loop. Separate
workspaces do not share database names, proxy PIDs, state directories, or
ports. The Cloud SQL instance still has shared cost and shared pause state, so
`pause` is an operator action rather than part of `db-down`.

The public endpoint is a deliberate compromise. It avoids permanent VPN or
bastion infrastructure while keeping authorized networks empty and requiring
the proxy. A future organization policy that forbids public IP would make this
backend unusable from laptops until a private network path exists.

The cloud suite is expected to be slower than loopback. Postgres.app or the
conda-forge backend remains the preferred fast feedback loop, and Cloud SQL is
the parity and shared-state option.

The cached password and pgpass file are credentials. Both are mode 0600 under
the ignored `.cloudsql/` directory. Neither may appear in logs, test fixtures,
snapshots, issue comments, or commits.

## Reversal conditions

* A supported VPN, Interconnect, or in-VPC proxy makes private-IP laptop
  access routine. Disable public IPv4 only after that route is proven.
* Instance-scoped custom roles become simpler than the conditional predefined
  role. Preserve the database-create, pause/resume, and connect permissions.
* WAN timing makes the integration loop impractical. Measure pooling or
  fixture-batching changes against the same corpus and test set before changing
  production engine defaults.
* Shared pause coordination becomes unreliable. At that point, prefer
  scheduled activation or one instance per developer over hidden automation.
