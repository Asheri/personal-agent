# Authors

Four credits, listed by the part of the tree each one produced. Most of this
repository arrived from elsewhere, so "who wrote it" has a different answer
depending on the file, and one part of it has no answer at all yet.

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

## author undetermined: the handoff implementation, v1.2 to v1.8

Everything between the public base and the first version this repository
received: document identity and version chains, project ownership and tagging,
document relations with literal provenance, the local file types, Chinese
retrieval, scoped browsing, one-shot refresh with a durable content-free audit,
and the five-scene Agent memory routes. It arrived as serial handoffs from group
members, and no commit in this repository names its author.

That work lands as one commit (the v1.8 candidate) whose git author is the
maintainer's identity, because that is the identity that pushed it. The git
record is a convenience, not an attribution. **This section is the attribution,
and it is open: a group member who did that work should add their name here.**

## foenwhite: this branch

The work in the commits after the v1.8 candidate: the cross-platform task
runner and the `PCMEM_DATA_DIR` root, the three portability fixes found by
running the suite on macOS, the GenericAgent integration contract and its blob
pin, the concurrent answer evaluation, the MultiHop-RAG three-condition runner
and the benchmark catalogue, the provenance and licence declarations, the
credential guard, and the documentation in this branch.

Commits on this branch are authored with GitHub's noreply address for
`foenwhite`. No bot identity is used.
