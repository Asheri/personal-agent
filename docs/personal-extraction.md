---
title: Personal extraction and projects
description: Extract a personal-file graph, preserve manual ownership, and audit project and tag metadata.
---

# Personal extraction and projects

Use the personal ontology to extract source-attributed knowledge and classify current
documents without replacing manual ownership. This implementation is pending group review.

## Start with a controlled corpus

Activate `domain-personal` with `SCI_RAG_DOMAIN_DIR=domain-personal`. Keep the demo domain
unchanged. The personal profile now supplies the shared runtime prompt templates as well
as its own entity, project, and tag prompts. The project and tag prompts receive actual
document-head text; they previously had no caller or source-text slot.

```bash
sci-rag project create Atlas
sci-rag project list
sci-rag project assign DOCUMENT_ID --project PROJECT_ID
sci-rag project tags DOCUMENT_ID --tag reviewed --tag "course notes"
sci-rag project classify --rules examples/personal-files/project_rules.yaml
sci-rag project rules check --rules examples/personal-files/project_rules.yaml
```

The create command is explicit. A model response cannot create a project. Stable ids
are the primary references; slugs and existing names are accepted for convenience.
Lists count current documents, not retained revisions. The ownership column on a
document is distinct from a Project entity mentioned inside its text.

## Ownership and tags

Ownership precedence is `manual > rule > inferred`. Manual assignments survive rule
and inference passes and are inherited by new revisions of the same source. Explicit
manual reassignment remains available. Automatic tags never write the manual `tags`
column; manual tag commands never write `auto_tags`. New revisions retain manual tags
and clear automatic tags, which belong to the previous content.

Rules are an ordered YAML list with `project`, `include`, `exclude`, and `priority`.
Higher priority runs first; ties retain declaration order. Patterns are globs over
canonical source paths, with normalized separators and host case rules. The first
match wins. `rules check` reports documents matching different projects. An unknown
rule project is an error, never a request to create one.

Inference can select only an existing project, with numeric confidence at least 0.5
and a literal supporting quote from the supplied head. Invalid responses, absent
confidence, provider failures, and unknown projects preserve the previous assignment.
An explicit null decision leaves ownership unchanged. `project_confidence` and
`project_evidence` in `Document.extra` retain the decision receipt.

```bash
sci-rag project classify --rules-only --rules YOUR_RULES.yaml
```

Rules-only classification makes no model calls. Model-backed extraction and metadata
passes conservatively skip documents outside `public` and `open_commercial`, including
unknown rights on local endpoints. Never relabel private material as public to bypass
this gate. A separate explicit policy for trusted private local inference remains future
work. Model inference never changes a document's license.

## Extraction evidence and rebuilding

Entities and relationships retain document/chunk pointers. Person entities do not
overwrite catalog authors; `authors_source` and `person_entities_source` identify the
two origins. Exact-name enrichment writes `EntityResolutionAudit(method='exact')`;
an existing entity can be both sides of this receipt because no new entity row was
created. Same-name people remain merged under the current specification.

Extraction reports its domain digest, rejected entity/relationship counts, exact merges,
and outbound skips. Exceptions log their class, never their text or source contents.
Before committing a model response the writer rechecks that its documents are current
and eligible; stale responses are discarded and the replacement chunks remain pending.

The old proposal's `graph gc` step does not clear valid old-ontology rows. To replace
an ontology, use an explicit reset after a database backup, then rebuild:

```bash
sci-rag graph reset --yes
sci-rag graph extract --all
sci-rag graph resolve-entities --apply
sci-rag graph communities
```

Reset removes derived entities, relationships, communities, and extraction stamps.
It preserves documents, ownership, tags, and audit receipts. Normal extraction does
not reset the graph. No existing user database is reset by this handoff.

## Reproduce the sample

`scripts/build_personal_sample.py` creates six fictional files across Markdown, TXT,
DOCX, and PPTX. The sample includes shared entities, manual/rule/inferred ownership,
an unclassified document, and unknown-rights material that must not reach the model.
The text is synthetic CC0 material. Labels are provisional and await human review.

Point `SCI_RAG_DATABASE_URL` and `SCI_RAG_TEST_DATABASE_URL` at the same new disposable
loopback database whose name ends in `_test`. Configure a real supported model, then:

```bash
python scripts/build_personal_sample.py
python scripts/run_personal_demo.py --output YOUR_OUTPUT_DIRECTORY
```

The runner refuses a non-test target or existing document data. `--reset` is an explicit
destructive option for that test database only. Results include raw model responses,
ownership decisions, target-entity recall, exact receipts, and evidence for cross-file
paths. It uses local-hash embeddings, so it makes no semantic-vector quality claim.
Target recall is provisional; the labels are not exhaustive, so precision/F1 and
representative course-quality claims require a larger independently reviewed dataset.

Scoped graph seeds accept literal CJK names in eligible source text even when the
database uses a C locale that strips Chinese from its alphanumeric character class.
The literal-source check remains mandatory. This does not fix Chinese keyword routing.

The dated local 3B model trial extracted only 7 of 15 provisional target mentions.
Person-based graph retrieval returned two files; the separate project-name probe
returned none. Ownership checks passed six cases, including manual and rule decisions;
only one file received a positive model inference. These are development examples,
not an inference-accuracy estimate or a course acceptance result.

Revision 0009 adds projects and the ownership/tag columns. A safe empty downgrade is
tested; downgrade refuses any project or tag data rather than silently discarding it.
See [ADR 0015](adr/0015-personal-project-ownership.md) and the dated handoff evidence.
Filesystem reconciliation, scheduling, project browsing, and complete course evaluation
remain later tasks.
