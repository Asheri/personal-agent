You are grading an AI assistant's answer for a question about $DOMAIN_NAME. You see the question, the answer, and the numbered source passages the assistant retrieved. You do NOT see any reference answer, and you must judge only against the sources shown.

Question:
$QUERY

Assistant's answer:
$ANSWER

Sources the assistant retrieved:
$SOURCES

Score three dimensions from 0 to 2 (whole numbers):

- groundedness: 2 if every factual claim in the answer is supported by the sources; 1 if most are but some go beyond them; 0 if the answer substantially invents or contradicts.
- citation_accuracy: 2 if bracketed citations point to sources that really support the adjacent claim; 1 if citations exist but some point to the wrong source; 0 if citations are missing or decorative.
- completeness: 2 if the answer uses the relevant material available in the sources; 1 if it misses clearly relevant material; 0 if it ignores most of it. If the sources genuinely lack the answer and the assistant said so, that honesty scores 2.

Respond with JSON only:

{"groundedness": 0, "citation_accuracy": 0, "completeness": 0, "rationale": "two or three sentences explaining the scores"}
