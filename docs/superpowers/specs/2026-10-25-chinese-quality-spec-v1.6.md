# Chinese retrieval and controlled model quality: v1.6 candidate

Status: implementation candidate, awaiting real nonauthor review. The approved
design baseline remains v1.1. This record supplements earlier candidates and
does not rewrite their history or approve a merge.

## Scope

- Specification section 4.4 / A4-1, A4-2: indexed Chinese search, query classes,
  adaptive routing, same-corpus paired evidence, and visible failure reporting.
- Section 3: revision 0011 derived keyword storage and legacy backfill.
- C-4/C-5 and section 5: current-version and scope predicates remain unchanged.
- Section 4.2 / C-6/C-7 / A2: actual model checks of extraction, directed
  relationships, ownership precedence, tags, and protected-source exclusion.
- Section 4.4 / A4: source-linked cross-file answers, old-version exclusion,
  missing-evidence responses, and matched RAG/KG configurations.

## Candidate decisions

Preserve the English keyword path and all default fusion weights. Chinese uses
jieba search tokens in a separate simple-language GIN index. Stored and query
tokens share one implementation. Personal-domain Chinese class cues and routing
patterns are active. Downgrade discards only reproducible keyword data.

Candidate B satisfies the identifier-only numeric gate on this corpus but emits
no candidates for all eight names and eight sentences. To avoid passing an
implementation that preserves the reported defect, candidate D is also required
to reach hit@20 of at least 0.75 in each of those buckets. This stronger gate and
its interpretation of the nonempty-query rule require independent review; the
approved specification text is not edited.

## Evidence and acceptance limits

Freeze 24 controlled questions and 104 chunks before measurement. Retain their
hash, raw hit matrix, per-query latency samples, semantic-vector comparator,
and `sci-rag eval diff` output. Separately retain model identities and hashes,
source facts for twenty model-ownership cases, precedence/privacy controls,
generated answers, and exact entity/directed-triple scoring.

Four development and sixteen held-out case IDs are declared in advance. Labels
are constructed from the controlled text and have not received human approval.
Mechanical answer checks inspect terms, citation IDs, expected cited projects,
and refusal cues; these are not a substitute for checking meaning. Do not claim
real-user accuracy, general KG superiority, or formal course acceptance from
these results. Do not infer improvement over the old 3B run on a different corpus.

## Review and rollback

An independent group member must inspect section 5 scope behavior, migration
backfill/rollback, token maintenance, frozen labels, actual source quotes, and
answers before adoption. Keep candidates unmerged. Source content and existing
graph provenance survive a rollback of the keyword cache. No automatic update
trigger, full browse implementation, or external Agent deployment is included.

## Controlled extraction follow-up

The personal ontology defines `canonical_suffixes` as suffix/minimum-stem pairs
and relation `source_types`/`target_types`. It keeps source forms as validated
aliases and rejects incompatible directions rather than swapping endpoints.
Generic document pronouns are not named entities. Extraction rejects aliases,
entity passages, and relationship quotes without literal source support, with
rejection counters; this source validation also applies to other domains.

One chunk per call is the measured 7B setting, using existing CLI options; global
batch defaults stay unchanged. These checks do not verify an alias's referent or
a relation's meaning simply from textual occurrence. Previously stored bad rows
need a reviewed explicit rebuild. The first failures and the development probes
are retained. The repeatedly evaluated original corpus is an exploratory paired
comparison, regardless of its historical heldout tag. See ADR 0018.
