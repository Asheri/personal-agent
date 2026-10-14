---
title: "ADR 0007: A generator that configures"
description: Why the project wizard rewrites real configuration files and renders no placeholders.
---

# ADR 0007: A generator that configures

`sci-rag new` fetches this repository at a pinned tag and rewrites its
configuration files in place. Nothing is templated and nothing is rendered.

**Status:** accepted

**Amended:** 2026-08-28. `sci-rag new` is the primary command. The original
`sci-rag-new` entry point remains a compatibility alias, and Quick and Advanced
prompt modes now present the same underlying configuration contract at two
levels of detail. Quick selects the first supported environment manager on
`PATH`, keeps production Terraform and the demo corpus, removes the optional
Cloud development helper, and writes an owner-only `.env`. Advanced exposes
those choices. Only `sci-rag new` performs the credential preflight before the
template download; `sci-rag init` uses the same answers without that network
check. This amendment changes the interface, not the decision below.

## Context

[ADR 0004](0004-template-repo-not-cookiecutter.md) rejected cookiecutter
because "the template itself is dead code: it cannot be browsed
comfortably, cannot run, and cannot be CI-tested as-is, and template bugs
are only found by generating." That reasoning still holds. But the same
ADR left a door open in its own consequences: "A cookiecutter wrapper
could be generated mechanically later if a downstream community wants
one; nothing in this decision blocks it."

What it left behind was an onboarding path made of manual steps. Click
**Use this template**, clone, copy `.env.example`, run `make setup`, then
work through seven steps in the bring-your-own-domain tutorial and
hand-edit `domain/domain.yaml`. The only automation was
`scripts/init_domain.py`, which set a name and a description. Everything
that actually makes a project yours stayed manual: the ontology, the
credential mode, the corpus source, the parser and reranker choices, the
environment manager.

Cookiecutter Data Science, the nearest comparable tool, answers this with
a short questionnaire and no directory to create first. The gap was never
the idea of a wizard. It was that the obvious way to build one drags back
in exactly what ADR 0004 refused.

## Decision

Ship an interactive generator that is a post-fetch applier and never a
template renderer.

`sci-rag new` downloads this repository at a pinned tag, then rewrites
its configuration files in place. `sci-rag init` does the same inside a
checkout you already have. The compatibility entry point `sci-rag-new`
routes to the new-project command. All three drive the same answer model and
appliers.

Interactive setup starts with Quick or Advanced. Quick asks for six setup
decisions, plus the credential value required by the selected mode, and uses
defaults for the other fields. Advanced asks every applicable question.
`sci-rag new` also checks a selected Google credential before the template
download; `sci-rag init` captures credentials without that new-project
preflight. These presentation and validation layers still converge on the same
`ProjectAnswers` contract before files change.

Four properties keep this inside ADR 0004:

* No placeholders. Nothing in the repository is a token waiting to be
  rendered, and no directory name is one either. A test generates a
  project for every environment manager and fails on any
  placeholder-looking token it cannot account for. Three contexts are
  accepted, by content rather than by filename: a GitHub Actions
  expression, BibTeX brace protection, and the illustration in ADR 0004
  of the syntax this project refuses.
* The template stays the runnable application. What the generator
  fetches is this repository, byte for byte: browsable, runnable, and
  CI-tested as itself. Nothing here becomes real code only after
  generation.
* The wizard is ordinary tested code. It lives in
  `src/sci_rag/scaffold/`, the unit suite covers it like anything else,
  and `.github/workflows/generated-projects.yml` exercises the result
  once per environment manager. The test suite finds template bugs; you
  do not have to generate a project and look.
* The package name still does not change. Derived projects keep the
  `sci_rag` import path, for the reason ADR 0004 gave: it preserves the
  ability to diff against, and pull improvements from, upstream.

The appliers round-trip their output through the same models the
application reads. `domain/domain.yaml` comes from serializing a
`DomainConfig`, so a generated profile cannot be something
`load_domain()` rejects, and an LLM-drafted ontology goes through that
same validation before anything reaches disk.

One `RunnerProfile` per environment manager renders uv, pixi, conda, and
venv+pip. The kit is manager-wired in five places (task commands, CI,
container, dev container, docs), and any disagreement between them
breaks a generated project on its first run.

## Consequences

* Onboarding is `pipx install sci-rag-kit`, then `sci-rag new`. No
  repository to clone first, no file to hand-edit before the first run.
* The generator ships in the same distribution as the application, so
  installing it also installs `sci-rag`. That install is heavy for what
  is mostly a generator: fastapi, uvicorn, asyncpg, sqlalchemy, alembic,
  pgvector, google-genai, mcp, and pypdf all come along. Accepted
  knowingly. The same install is the tool the user wants next, pipx
  isolates it, and the scaffold package lazy-imports the runtime, so
  startup stays fast even though installation is not.
* The new-project command and its compatibility alias fetch the tag matching
  their installed version. A
  given generator release always produces the same project, and
  upgrading the generator is the only way to change what a new project
  contains.
* The generator is now a compatibility surface. CI and the documentation
  both read its question names and answers-file format, so changing them
  follows the promises in [VERSIONING.md](../VERSIONING.md).
* The homepage session is generated from the question list, never
  recorded by hand, so it cannot quietly drift from what the wizard asks.
* ADR 0004 is not superseded. This implements the escape hatch it
  described, under the constraints it set.

## Reversal conditions

Revisit if any of these stop being true:

* A generated project stays diffable against upstream. If it stops
  being so, the generator has started producing structure rather than
  configuration.
* A person will sit through the question set. Past that point the
  answers file is the primary interface and the interactive path is the
  fallback, which is a different tool.
* No placeholder syntax appears anywhere in the tree. That is the
  specific failure ADR 0004 refused, and the reason the unresolved
  placeholder test exists.
