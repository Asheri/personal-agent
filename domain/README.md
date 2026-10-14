# The domain folder

Everything the kit knows about a field lives in this folder: the concepts it looks for, the words it uses when it asks a model for something, and the questions it scores itself against. Pointing it at a new field never means editing Python.

| File | What it controls |
|------|------------------|
| `domain.yaml` | The project's name and description, the ontology (entity and relation types), the question classes that steer the hypothetical-answer search, retrieval tuning, and answer compression |
| `prompts/entity_extraction.md` | How chunks become graph entities and relationships |
| `prompts/query_entities.md` | How the concepts in a question are spotted for the graph search |
| `prompts/hyde.md` | How the hypothetical answering passage is written |
| `prompts/answer.md` | How answers are written and cited |
| `prompts/snippet_compression.md` | How retrieved chunks are scored and summarized before answering |
| `prompts/community_summary.md` | How clusters of related entities are summarized |
| `prompts/screening.md` | How campaign abstracts are screened against stated criteria |
| `prompts/judge_grounding.md`, `prompts/judge_correctness.md` | How the grader scores answers. Keep the two passes separate |
| `prompts/ontology_from_corpus.md`, `prompts/manifest_metadata.md`, `prompts/seed_questions.md`, `prompts/prompt_localization.md` | How `sci-rag draft` asks a model for a first version of the files above |
| `eval_seed_questions.jsonl` | The test questions, with the evidence a correct answer rests on |
| `eval_calibration_labels.jsonl` | Human scores for graded answers, used to check the grader |

Prompts are Markdown with `$UPPER_CASE` slots filled at runtime (`$DOMAIN_NAME`, `$QUERY`, `$ENTITY_TYPES`, and so on). Edit the words around the slots freely; that is how the register of a prompt gets moved from agricultural residues to membrane chemistry. Keep every slot, though, because a template that lost one loads without error and fails mid-run.

As shipped, the folder is configured for the demo domain, agricultural residues, so everything works before anything changes. [Bring your own domain](../docs/bring-your-own-domain.md) is the seven-command recipe for pointing it at a new field; three of the commands write into this folder.

## Start from a draft

`sci-rag draft` writes a first version of the files above from the documents already on disk, so the ontology it proposes is about what those documents discuss:

```
uv run sci-rag draft manifest --folder data/raw   # data/corpus.jsonl
uv run sci-rag draft ontology --folder data/raw   # domain.yaml
uv run sci-rag draft questions --count 10         # eval_seed_questions.jsonl
uv run sci-rag draft prompts entity_extraction    # prompts/*.md
```

Each command writes a `.proposed` file to review. Each also prints its prompt with `--print-prompt`, for pasting into any assistant, and reads the reply back with `--from-file`. That route needs no API key and runs the same validation.

## Two things stay yours

**Rights.** No model sets `license_class`. Every drafted manifest row says `unknown`, which retrieval treats as unsafe until a person decides.

**Ground truth.** Drafted seed questions carry a `drafted` tag, and every evaluation report repeats it until a domain expert removes it. `eval_calibration_labels.jsonl` is never drafted: it exists to check the grader against human judgment, and a model-written version would measure nothing.

[Drafting with a model](../docs/bring-your-own-domain.md#drafting-with-a-model) explains the three routes in full.
