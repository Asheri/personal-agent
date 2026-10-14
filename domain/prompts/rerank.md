You are ranking search results for a scientific knowledge base.

Question:
$QUERY

Candidates (numbered):
$CANDIDATES

Score every candidate 0-10 for how directly it helps answer the question
(10 = contains the answer, 0 = unrelated). Judge only the text shown; do
not reward familiar-sounding titles.

Return JSON only: {"scores": [{"index": <candidate number>, "score": <0-10>}, ...]}
