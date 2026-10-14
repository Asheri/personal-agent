---
title: "ADR 0004: A runnable template, not a cookiecutter"
description: Why this repository is the application you run, and not a tree of placeholders that becomes one.
---

# ADR 0004: A runnable template, not a cookiecutter

This repository is the application you run. It is a GitHub template you copy and configure, and it contains no placeholders waiting to be rendered.

**Status:** accepted

## Context

The classic way to ship a project factory is cookiecutter: a repository
full of `{{ cookiecutter.project_slug }}` placeholders that a generator
renders into a real project. Cookiecutter parameterizes everything. The
price is that the template itself is dead code: it cannot be browsed
comfortably, cannot run, and cannot be CI-tested as-is, and template bugs
are only found by generating.

## Decision

sci-rag-kit is a **GitHub template repository that is itself a working
application**: real code, a real demo corpus, green CI, "Use this
template" to copy it. You configure it by editing data and
configuration, meaning the `domain/` folder, the corpus manifest, and
`.env`, rather than by renaming Python packages. A small
`scripts/init_domain.py` handles the cosmetic rebranding: project name,
description, and a seed-question reset.

The Python package deliberately stays `sci_rag` in every derived
project. Renaming the import path buys nothing functional, and it costs
you the ability to diff against the upstream template and pull
improvements from it.

## Consequences

* A newcomer evaluates the kit by reading and running it, before
  committing to it. The demo is the documentation of behavior.
* The same CI that gates any application gates template quality.
* We give up cookiecutter-style deep parameterization, such as license
  choice and layout variants. That is acceptable: this template has
  opinions, and disagreeing with one costs you a normal code change in
  your own copy.

## Reversal conditions

* Enough of the tree needs per-project parameterization that configuring
  files in place stops being expressible, and a real placeholder syntax
  becomes the smaller cost.
* A downstream community needs a cookiecutter wrapper. That can be
  generated mechanically from this repository, so it is an addition and
  not a reversal.
