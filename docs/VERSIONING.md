---
title: Versioning
description: Learn which five public surfaces hold stable inside 0.x, and what evidence a 1.0 promise is waiting on.
---

# Versioning

sci-rag-kit follows [Semantic Versioning](https://semver.org/). This
page spells out the 0.x rules: "semver" alone does not promise anything
before 1.0, and users deserve clarity on what holds.

## While we are 0.x

- **Minor releases (0.2 -> 0.3) may break APIs.** The CHANGELOG says so explicitly under a "Breaking" heading with a migration note. We break deliberately and loudly, never silently.
- **Patch releases (0.2.0 -> 0.2.1) do not break anything**: fixes, docs, and additive features only.
- **The database schema is versioned by Alembic migrations** (`migrations/versions/`). Every release's migrations run forward from any prior release's schema. Skipping releases is fine; downgrades are best-effort.
- **Eval report JSON is additive**: new keys may appear in `report.json`/`calibration.json`; existing keys do not change meaning or type within 0.x. External tooling, including the UW SSEC evaluation platform, can rely on that interface.
- **Domain profiles are forward-compatible.** A `domain/` directory written for an older 0.x keeps working. New capabilities arrive as optional keys with safe defaults. The reranker block is the model: absent means off.

## What is public API

The compatibility promise covers:

1. The `sci_rag` Python package's documented top-level exports
   (`docs/api.md`)
2. The CLI command surface (`sci-rag ...`)
3. The REST contract under `/v1` and the MCP tool names/schemas
4. The `domain/` directory format
5. Eval report JSON keys

Internal module paths (anything not in `docs/api.md`) may move in any
minor release.

## Deprecation

Within 0.x: deprecated surface keeps working for one minor release with
a visible warning, then goes. The CHANGELOG lists every deprecation, the
release it starts in, and the release it lands in.

## Criteria for 1.0

1.0 is a promise, so it waits for evidence the promise can be kept:

- At least two production deployments outside the maintainers' own
  (ADOPTERS.md is the register; BioCirV is the flagship candidate)
- One full minor-release cycle with no breaking change needed to the
  five public surfaces above
- The benchmark page reproducible by an outside party from a clean
  clone (`make benchmark`)
- Judge calibration against domain-expert labels (not the shipped
  non-expert seed set) published for at least one real corpus
- Security review of the serving layer since the last surface change

After 1.0: breaking changes only in major releases, with migration
guides.

## Release mechanics

Releases are tagged `vX.Y.Z` from `main` with CI green, a CHANGELOG entry, and (once the maintainer enables it; see the launch-gated list in [ROADMAP.md](ROADMAP.md)) an archival DOI per release.

Pushing the tag runs [`.github/workflows/release.yml`](https://github.com/sustainability-software-lab/sci-rag-kit/blob/main/.github/workflows/release.yml), which verifies, publishes to TestPyPI, publishes to PyPI, then opens the GitHub Release.

1. `verify` runs four checks. It confirms the `ci` workflow already
   passed for the tagged commit, confirms the tag matches
   `project.version` in `pyproject.toml`, runs `uv build`, and installs
   the built wheel into a throwaway environment to check the main `sci-rag`
   CLI and the `sci-rag-new` compatibility entry point are both on the path.
2. `testpypi` publishes to TestPyPI. It runs first on every release
   because PyPI does not allow re-uploading a version, even a broken one,
   so a packaging mistake found on PyPI costs a version number.
3. `pypi` publishes to PyPI.
4. `github_release` creates the GitHub Release from the changelog section
   matching the tag, and attaches the same sdist and wheel that were
   published. It runs last, and only if `pypi` succeeded, because a release
   page announcing an artifact that never published is worse than no page.

### What a release page looks like

The release is titled with its tag and nothing else: `v0.5.0`, not
`v0.5.0: some name`. Earlier releases went both ways, which left a reader
unable to tell whether a bare `v0.2.0` meant a smaller release or just a
release nobody named.

The descriptive line has not gone anywhere. It is the changelog lede, which
the release page shows directly under the tag, so the name is the first
sentence rather than the heading. Keeping it there means the automation can
produce the whole page from the changelog with no manual step, and a
convention with a manual step is the kind that drifts.

Every released section opens with that lede, a sentence or two saying what the
release is for before any `###` category. `test_every_released_section_opens_with_a_lede`
enforces it. `## [Unreleased]` is exempt: the lede is written when the release
is cut, which is when its headline is finally known.

Write the changelog entry before tagging. `github_release` reads the
`## [X.Y.Z]` section through `scripts/changelog_release_notes.py` and fails
when that section is missing or empty, rather than publishing a blank page.
A tag whose entries are still under `## [Unreleased]` will fail there.

The Releases page previously fell three versions behind PyPI, because the
workflow published the package and nothing created the page. Nothing failed
while that drifted, which is why it is now part of the same run.

The tag is the source of truth for the version, and the verify job enforces
that. The project generator fetches the template at the tag matching its own
installed version, so a release whose tag and packaged version disagree would
generate projects from the wrong commit.

### One-time setup, by a maintainer

The workflow uses [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC), so the repository stores no API token to leak or rotate. Trust is
established once per index, by hand. CI cannot do this automatically:

1. Reserve `sci-rag-kit` on [PyPI](https://pypi.org/) and on
   [TestPyPI](https://test.pypi.org/). They are separate accounts and
   separate namespaces.
2. On each index, add a pending publisher for the project:
   - Owner: `sustainability-software-lab`
   - Repository: `sci-rag-kit`
   - Workflow: `release.yml`
   - Environment: `pypi` on PyPI, `testpypi` on TestPyPI
3. Create the matching GitHub environments (`pypi`, `testpypi`) in the
   repository settings. Put a required reviewer on `pypi` for the first
   release; that turns the final publish into a maintainer decision rather
   than an automatic one triggered by a tag push.
4. Verify end to end before approving the PyPI publish, from a clean
   directory. Install the TestPyPI **artifact by URL** and let dependencies
   resolve from real PyPI:

   ```bash
   WHEEL=$(curl -sS https://test.pypi.org/pypi/sci-rag-kit/<version>/json \
     | python -c "import json,sys; print(next(u['url'] for u in json.load(sys.stdin)['urls'] if u['packagetype']=='bdist_wheel'))")
   uv venv probe && VIRTUAL_ENV=probe uv pip install "$WHEEL"
   probe/bin/sci-rag new --defaults
   probe/bin/sci-rag-new --help
   ```

   Do not point the installer at both indexes at once. TestPyPI is full of
   placeholder and name-squatted packages, and any resolver told to consider
   both may prefer a fake `fastapi 1.0` from TestPyPI over the real
   one. Installing the single artifact by URL sidesteps that entirely: it
   tests the built artifact, with the dependencies end users will get.

   What to check before approving: both entry points run,
   `sci_rag.__version__` matches the tag, and `sci-rag new --defaults` produces
   a project. The generation command is the only check that exercises the
   GitHub tag fetch, which is what a PyPI upload cannot verify. The
   separate help command confirms the legacy executable remains available as a
   compatibility alias.

Skip step 2 on an index and that index's job fails with a
missing-publisher error. It publishes nothing and costs nothing; configure
it and re-run the workflow.
