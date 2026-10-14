---
title: "ADR 0008: PostgreSQL 16 through 18"
description: Why the supported server range spans three majors, and what tests each end of it.
---

# ADR 0008: PostgreSQL 16 through 18

Sci RAG Kit supports PostgreSQL 16 through 18, and both ends of that range are tested on every change.

**Status:** accepted

**Partially superseded by [ADR 0009](0009-cloud-dev-database.md).** The original
decision below correctly records what each environment manager bundles. ADR
0009 later established that every manager may use the `local` backend with a
supported system server and may retain the optional Cloud helper.

## Context

[ADR 0001](0001-graph-in-postgres.md) put the documents, chunks, vectors,
full-text indexes, entities, relationships, and communities in one
PostgreSQL. Everything since has assumed a single operational store, and
`docker-compose.yml` has supplied it: `pgvector/pgvector:pg16`, published
on host port 5433.

That has been a real barrier for one specific audience. The environment
manager work added pixi and conda because scientific and national-lab
users asked for them, and `docs/quickstart.md` then told those same users
that the first requirement is Docker. On a managed laptop or a shared
cluster login node, that is often the one thing they cannot install.

conda-forge ships both halves of what they need. The complication is that
it builds the extension against whatever server it currently carries:

| pgvector | built against | platforms |
| --- | --- | --- |
| 0.7.0 to 0.7.3 | PostgreSQL 16 | linux-64, osx-64, osx-arm64, win-64 |
| 0.7.4, 0.8.0 | PostgreSQL 17 | linux-64, osx-64, osx-arm64 |
| 0.8.1 to 0.8.6 | PostgreSQL 18 | linux-64, linux-aarch64, linux-ppc64le, osx-64, osx-arm64 |

So a Docker-free user on a current channel gets PostgreSQL 18, while
compose and CI run 16. Three ways out were considered. Moving the whole
project to 18 changes the operational store for every existing user and
needs migration evidence to justify. Pinning Docker-free users to
pgvector 0.7.3 keeps the major aligned but fights the channel and hands
that group a two-year-old extension. Letting the two diverge untested is
how an unreproducible bug report gets written.

None of that was necessary, because nothing here needs a specific major.
The schema uses one HNSW index with `vector_cosine_ops` and no pgvector
feature newer than 0.5, no `hnsw.ef_search` or iterative-scan tuning, and
no version-specific SQL. `docs/quickstart.md` had already been telling
external-database users "PostgreSQL 15 or newer" for as long as it has
existed. The 16 in this repository was three container image tags, not a
requirement.

## Decision

Support **PostgreSQL 16 through 18**, and test both ends.

* Compose, the `ci.yml` service, and the generated-project service stay on
  the `pgvector/pgvector:pg16` image. No existing database moves, and the
  supported floor is what every pull request exercises.
* pixi and conda projects declare `postgresql >=16,<19` and `pgvector` in
  their own manifest and run the server from there. The bound rather than
  a pin is deliberate: conda-forge has to be free to pick a pgvector built
  against the same major as the server it resolves, and that pairing is
  the constraint that actually matters. Today that resolves to
  PostgreSQL 18.
* `scripts/local_postgres.py` drives `initdb` and `pg_ctl` against a
  project-local data directory, producing a database the unmodified
  `.env.example` already points at: role `sci_rag`, database `sci_rag`,
  port 5433, loopback only. Swapping compose for it should not mean
  editing a connection string.
* `docker-free-postgres.yml` runs the integration and server suites
  against a conda-forge server on linux-64 and osx-arm64, and fails if
  the suite skips. Between that job and `ci.yml`, 16 and 18
  are both proven on every release.
* uv and venv+pip get none of this and keep Docker. PyPI ships no
  PostgreSQL server, and a manager that cannot take the path must not
  advertise it. `RunnerProfile.conda_forge_packages` is the single place
  that decides which managers can, so the manifests, the task commands,
  the documentation, and the CI matrix cannot disagree.

## Consequences

A pixi or conda user installs one environment and has a working database,
with no container runtime and no second tool. That is the audience that
asked for those managers in the first place.

The cost is that two server majors are now in play. A change that depends
on version-specific behavior will pass on one and fail on the other, and
the Docker-free job is what surfaces it. That job is not in the required
set for `main`, so a failure there is visible but not blocking; promoting
it is a repository settings change, not a code one.

The local server uses `trust` authentication on 127.0.0.1. This matches
the posture of the password committed in `docker-compose.yml`: it is a
development database on one machine, reachable from nowhere else. It is
not a deployment path, and `docs/deploy-gcp.md` remains the one for that.

Support is a claim about what is tested, not about what happens to work.
PostgreSQL 15 will very likely keep running the schema, and the quickstart
said so before this ADR, but nothing exercises it, so the floor is now the
version CI proves.

## Reversal conditions

* conda-forge builds pgvector against more than one server major at a
  time. The bound exists only because it cannot today; if that changes,
  aligning the Docker-free path with compose becomes free.
* Anything in the schema, the queries, or the migrations starts depending
  on a version-specific behavior. At that point the range is a liability
  and no longer a convenience, so the project should pick one major and
  supply a migration path.
* PostgreSQL 19 lands and conda-forge follows. Extending the bound needs
  a green Docker-free run on the new major, not just an edited number.
