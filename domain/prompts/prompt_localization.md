You are rewriting one prompt template so it speaks the vocabulary of a
particular scientific field, without changing what it asks the model to do.

Template being rewritten: $PROMPT_NAME
Domain: $DOMAIN_NAME

The entity types this domain works with:

$ENTITY_TYPES

Current text of the template, between the markers:

<<<TEMPLATE
$CURRENT_TEXT
TEMPLATE

Rewrite it so a specialist in this field recognizes their own terms, examples,
and units. Change the wording. Do not change the job.

Hard requirements:

- **Keep every one of these slots, spelled exactly, at least once**:
  $REQUIRED_SLOTS
  They are substituted at run time. A template that has lost one loads fine and
  fails in the middle of a pipeline run.
- **Introduce no new placeholder.** Do not add any `$$NAME` marker that is not
  in the list above, and write no lone dollar sign anywhere in the text. A
  dollar sign you actually mean must be doubled.
- **Keep the output contract identical.** If the template asks for JSON, ask for
  JSON with exactly the same keys, the same nesting, and the same value types.
  Downstream code parses this; renaming a key breaks it.
- **Keep every rule that constrains honesty**: instructions not to invent,
  to copy evidence verbatim, to say when something is absent, to stay within
  the supplied passages. Reword them, do not soften or drop them.
- **Keep the structure**: the same sections in the same order, so a reader
  comparing old and new can see what changed.

Replace generic examples with ones this field actually uses. If the current text
names a feedstock or a process from someone else's domain, name one from this
one instead.

Return JSON only, with exactly this shape:

{
  "prompt": "the complete rewritten template, as one string",
  "notes": ["one short line per substantive change you made"]
}

The "prompt" value is written to disk verbatim, so it must be the whole
template, not a diff and not an excerpt.
