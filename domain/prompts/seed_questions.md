You are helping a scientist build the ground truth for evaluating a retrieval
system over their own document collection. Domain: $DOMAIN_NAME.

The knowledge base organizes its field with these entity types:

$ENTITY_TYPES

and expects these kinds of question:

$QUERY_CLASSES

Below are real passages from the collection, each numbered and labeled with
the document it came from.

$PASSAGES

Write $COUNT evaluation questions a domain expert could vouch for.

Rules, in order of importance:

- **Quote your evidence.** Every string in "evidence_phrases" must be copied
  character for character out of one of the passages above. Do not paraphrase,
  do not round a number, do not fix a typo. A phrase you cannot copy is a
  phrase you must not use.
- **Name the right documents.** Every title in "reference_titles" must be one of
  the document titles labeled above, spelled the same way, and it must be a
  document whose passages actually contain the evidence you quoted.
- **Ask what the passages answer.** If the passages do not settle the question,
  do not ask it.
- **Spread across the collection.** Do not draw every question from one document
  or one query class.
- **At least one multi-hop question** whose answer needs two different documents.
  Name both in "reference_titles".
- **Exactly one honesty probe**, tagged "unanswerable": a plausible question in
  this field that these passages do not answer. It gets an empty
  "reference_titles" and an empty "evidence_phrases", and its
  "reference_answer" says the collection does not cover it.
- **Distinctive phrases only.** "the study" appears everywhere; "302,000 dry
  tons" appears once. Prefer numbers, units, and named things.

Return JSON only, with exactly this shape:

{
  "questions": [
    {
      "id": "short-kebab-case-id",
      "question": "What does the corpus say about ...?",
      "reference_answer": "One or two sentences a correct answer must convey.",
      "reference_titles": ["Exact Document Title From Above"],
      "evidence_phrases": ["a phrase copied verbatim from a passage"],
      "tags": ["one of the query classes above"]
    }
  ]
}

Ids must be unique and readable. Add no commentary outside the JSON.

$REJECTED
