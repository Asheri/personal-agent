---
title: Governance
description: See who decides what, how a proposal becomes a decision, and what any reviewer is empowered to block.
---

# Governance

Code changes are decided in pull requests, architecture changes in decision
records, and direction-level proposals in public RFC discussions.

## Roles

**Maintainers** merge to `main`, cut releases, own the roadmap and launch-gated decisions, and handle conduct escalations (see CODE_OF_CONDUCT.md). The current maintainers are the Sustainability Software Lab (LBL) team that builds the kit.

**Reviewers** are regular contributors whom a maintainer invites after a track record of quality reviews and merged work. Their reviews count toward merging. Maintainers still land the merge while the project is 0.x.

**Contributors** open issues, improve documentation, and send pull requests. CONTRIBUTING.md covers the mechanics: tests and `make check` must pass, claims must be honest, and numbers must come from evidence.

## How decisions are made

- **Code-level decisions** happen in pull requests. Ablations, benchmarks, and failing tests resolve disagreements. The ablation-first rule applies to maintainers too.
- **Architecture decisions** get a numbered ADR in `docs/adr/` that states the context, decision, consequences, and reversal conditions. A contradictory change updates or supersedes the ADR in the same pull request.
- **Direction-level proposals** start as a GitHub Discussion in the "Ideas" category. Title it "RFC: ..." and state the problem, proposal, and alternatives considered. This route covers new subsystems, roadmap changes, and anything touching the five public surfaces in [VERSIONING.md](VERSIONING.md). A proposal that converges becomes an ADR plus issues; otherwise, the Discussion records why it stopped.
- **Tie-breaks** go to maintainers, who decide in public and record their reasoning where the discussion happened.

## What we optimize for

Reviewers may block any change that publishes an unmeasured claim. The project
favors inspectable designs, visible limitations, and evidence that another
person can reproduce.

## Changing this document

Governance changes follow the direction-level route: start an RFC Discussion,
then update this page in a pull request. While the project is 0.x, add roles
only when there are people to fill them.
