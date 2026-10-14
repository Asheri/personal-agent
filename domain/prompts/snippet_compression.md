Score and compress each retrieved scientific passage for the user's question.

Question: $QUERY

Return JSON with exactly this shape:
{"snippets":[{"index":1,"relevance_score":0.0,"summary":"..."}]}

Rules:
- Return exactly one object for every input index and preserve each index.
- relevance_score is a number from 0 to 1 measuring relevance to the question.
- summary contains only question-relevant facts stated in that passage.
- Preserve numbers, units, qualifications, disagreements, and uncertainty exactly.
- Do not add outside knowledge, citations, or claims from another passage.
- Keep each summary at or below $MAX_TOKENS_PER_CHUNK tokens.
- Even when a passage is irrelevant, return a short faithful summary; the caller applies the floor.

Passages JSON:
$CHUNKS_JSON
