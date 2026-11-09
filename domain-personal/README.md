# domain-personal: the personal file space domain profile

This directory is the PC-Mem specialization of the domain layer (spec section
4.2). The package code is domain agnostic: all personal file semantics live
here, so a user of this repository never edits `src/sci_rag/`.

## How to activate

```bash
export SCI_RAG_DOMAIN_DIR=domain-personal   # Windows: setx / set in the shell
uv run sci-rag doctor                        # reports the loaded domain
```

The shipped demo profile under `domain/` is kept untouched on purpose: the
test suite, the demo corpus, and the graph replay baseline pin it. Both
profiles can coexist; only one is active per run.

## What is specialized here

- `domain.yaml`: the personal file space ontology (12 entity types including
  Person and Project, 11 relation types), query classes for locating, project,
  person, and timeline questions. Retrieval weights and compression defaults
  are copied verbatim from the calibrated demo profile, per repository rule.
- `prompts/entity_extraction.md`: same slot contract as the shipped prompt
  ($DOMAIN_NAME, $ENTITY_TYPES, $RELATION_TYPES, $PASSAGES) with personal file
  rules (bilingual names, PART_OF versus SUPERSEDES, no invented aliases).
- `prompts/project_inference.md`, `prompts/tag_extraction.md`: draft prompts
  for the P2 metadata passes (slots documented in each file header).

## Known gaps (do not pretend otherwise)

1. Chinese keyword indexing, class matching, and routing are implemented in the
   v1.6 candidate. See `docs/chinese-retrieval.md` for migration 0011 and the
   controlled semantic-vector spike. Large-corpus and field quality remain unverified.
2. Compression defaults are validated on the demo corpus only. Re-run the
   paired gate on personal files before trusting `relevance_floor: 0.0`.
3. The project and tag passes now call their prompts through `sci_rag.projects`.
   See `docs/personal-extraction.md` for source priority, rights gating, and the
   provisional sample. Shared runtime prompts are copied from the demo profile;
   formal nonauthor review and representative personal-file quality evaluation remain open.
