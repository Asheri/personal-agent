---
title: "ADR 0010: The local template boundary is tracked content"
description: Why generating from a local checkout copies what the repository tracks instead of what the working tree holds.
---

# ADR 0010: The local template boundary is tracked content

Generating a project from a local checkout copies the files the repository tracks. Everything else in that directory is the author's local state and stays where it is.

**Status:** accepted

## Context

`sci-rag new` has two ways to put the template on disk. The default downloads
a tarball from GitHub at the tag matching the generator's version, which is
already exactly the tracked content at that tag. The `--template-path` route
copies from a checkout on the same machine, which is what the tests use and
what anyone generating offline uses.

A checkout is not a template. It also holds the Cloud SQL proxy password and
cached credentials under `.cloudsql/`, agent working files under `.context/`,
a filled in `.env`, a virtualenv, a local PostgreSQL cluster under `.pgdata/`,
Terraform state that contains a generated database password, and whatever
corpus the author last ingested under `data/raw/`.

Until this decision the copy excluded eleven names it happened to know about:
`.git`, `.venv`, `.pixi`, `__pycache__`, `*.pyc`, `site`, `eval_results`,
`node_modules`, and the three tool caches. Every other ignored path crossed
into the generated project byte for byte. The 2026-08-29 documentation route
audit reproduced that with synthetic sentinels in `.cloudsql/` and `.context/`
and filed it as blocker F-001.

The defect is not the missing names. It is the direction of the rule. A
denylist of remembered names fails open: the next ignored directory somebody
adds to the repository leaks until someone notices and adds a twelfth entry.

## Decision

The local template boundary is **what the repository tracks**.

`git ls-files` in the source checkout enumerates the copy set, and the copy
reads each of those paths out of the working tree, so uncommitted edits to
tracked files still generate. An ignored file cannot be copied because it is
never enumerated. This is the same content the download route produces, so the
two routes stop disagreeing about what a generated project contains.

A source directory that git knows nothing about, such as an extracted
`git archive` or a hand assembled tree, keeps working. Its fallback is fail
closed:

* no dot prefixed entry is copied unless the template genuinely ships it,
* the build output and cache directories that carry no dot are named,
* the corpus and evaluation directories keep only their `.gitkeep`.

A git repository with no tracked files is an error rather than an empty
project, because silently generating nothing is worse than refusing.

## Consequences

* Credentials, agent state, environment files, caches, Terraform state, and a
  private corpus cannot reach a generated project through `--template-path`.
* A new ignored directory added to this repository is excluded the moment it is
  ignored. Nothing has to be remembered.
* A file that is untracked and not ignored, such as a newly written module the
  author has not staged, does not generate. This is the fail closed direction
  and it is visible immediately: the generated project is missing a file the
  author knows they wrote.
* `--template-path` against a checkout now prefers the `git` binary. The
  download route still needs no git at all, and the fallback keeps the offline
  route working when git is absent.
* Generation reports which boundary ran, so a surprising result can be
  diagnosed without reading this file.

## Reversal conditions

Revisit if the generator ever needs to produce content that the repository
deliberately does not track, or if a supported environment cannot provide git
for the `--template-path` route and the fallback proves too coarse for it.
