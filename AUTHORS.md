# Authors

Three contributors of record, listed by the part of the tree they produced.
Most of this repository arrived from elsewhere, so "who wrote it" has three
different answers depending on the file.

## Asheri: the fork

First author of this repository. Migrated the two upstream trees in `7041ab2`,
installed the PC-Mem specification baseline and the task ledger in `3246181`,
and made `AGENTS.md` the single entry point in `b3aca07`. The commits before
this branch are theirs.

## the sci-rag-kit contributors: the knowledge base

`src/sci_rag/`, the `domain/` demo profile, Alembic revisions `0001` to `0007`,
most of `docs/`, and the test suite come from
[sci-rag-kit](https://github.com/sustainability-software-lab/sci-rag-kit) at tag
`v0.5.0`, under BSD-3-Clause. Credit for that code belongs to that project.
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) records the grant, and
[MIGRATION.md](MIGRATION.md) records what was copied and what was excluded.

The Agent memory face (`plugins/hooks.py`, `plugins/project_mode.py`, and the
seeds in `memory/`) comes from
[GenericAgent](https://github.com/lsdefine/GenericAgent) under MIT, with the
same treatment and a blob-level pin.

A naming note, because it is easy to misread: `tylerhuntington` appears in
`.github/workflows/generated-projects.yml` and two tests as a **forbidden**
pattern. The scaffolder fails when a generated project's docs contain that
username, so the string is a leak guard, not an attribution. Do not move it
into a credit line without confirming the maintainer's role upstream first.

## foenwhite: this branch

The implementation from v1.2 to v1.8: document identity and version chains,
project ownership and tagging, document relations with literal provenance,
local file types (Office, mail, code, data, optional OCR), Chinese retrieval,
scoped browsing with facets and timeline, one-shot refresh with a durable
content-free audit, the five-scene Agent memory routes, the external-safe
rights default, plus the cross-platform task runner, the Agent contract, the
benchmark runner, and the documentation in this branch's commits.

Commits on this branch are authored with GitHub's noreply address for
`foenwhite`. No bot identity is used, and no other person is credited with work
they did not do.
