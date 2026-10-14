# Contributing

Contributions take one of two forms:

* **Improvements to the kit itself**: the pipeline, retrieval layers,
  evaluation harness, server, or documentation.
* **Reusable work from a domain project**: a domain profile stays in your copy of the template,
  while a general parser, collector, or evaluation pattern can be extracted and contributed here.

## Development setup

```bash
uv sync --group docs --group docs-test
make setup          # install, start the selected backend, apply migrations
make check          # ruff + mypy + the full test suite
make docs           # generated references + strict build + public-artifact guard
make docs-geometry  # optional: measure the built site's snippets in a browser
uvx pre-commit install   # optional locally; CI runs every hook on the whole tree
```

Docker is the easiest CI-parity backend and the template default. pixi and
conda can run PostgreSQL from conda-forge; uv, pixi, conda, and venv + pip can
use a supported system server or the optional Cloud helper. The full matrix is
in `docs/run-postgres.md`.

The whole suite uses deterministic local embeddings and mock LLMs. Database
tests destroy data in `SCI_RAG_TEST_DATABASE_URL`, so create a disposable test
database for the selected backend. If PostgreSQL is unreachable, integration
tests skip with instructions. A skipped database suite provides no passing evidence.

`make docs-geometry` drives a real browser over `site/` to catch presentation
bugs that Markdown checks cannot see, such as adjacent code blocks with no
gap. Run `make docs` first. The geometry target installs its separate browser
dependency; without the site or browser, the tests skip with instructions.
CI runs them in the job that builds the site.

## The bar for changes

* **Tests come with the change.** Offline by default; anything needing
  real credentials is marked `cloud` and skipped in CI.
* **`make check` is green**: ruff (lint and format), mypy, pytest. CI also
  verifies `uv.lock`, runs every configured pre-commit hook, enforces a
  coverage floor (see ci.yml), builds the Docker image, checks Terraform
  formatting and validity, and verifies internal doc links. If a change lowers
  coverage below the floor, add tests and leave the floor unchanged.
* **Retrieval or eval behavior changes bring receipts**: run
  `sci-rag eval retrieval --ablation` on the demo corpus before and
  after, and put both tables in the PR description. The CI smoke eval
  enforces a floor, but the PR should show the delta.
* **Docs move with behavior.** Every user-visible behavior change must include
  the corresponding update in `docs/`.
* **Honest degradation over silent failure**, everywhere: new failure
  modes must be visible in traces, reports, or logs.

## Style notes

Follow the existing style; ruff enforces most of it. Explain **why** a module
has its shape in docstrings, using plain language for a scientist reading the
codebase for the first time. Do not use em dashes in prose. Keep prompts and
documentation free of unexplained jargon.

## Decision records

Anything that changes an architectural decision, or adds one, gets an ADR
in `docs/adr/`. Follow the existing format: context, decision,
consequences, and the conditions under which we would reverse it.
