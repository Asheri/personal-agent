You are grading an AI assistant's answer against a reference answer written by a domain expert in $DOMAIN_NAME. Judge factual agreement, not style.

Question:
$QUERY

Reference answer (ground truth):
$REFERENCE

Assistant's answer:
$ANSWER

Score one dimension from 0 to 2 (whole numbers):

- correctness: 2 if the assistant's substantive claims agree with the reference; 1 if it is partially right with meaningful gaps or minor errors; 0 if it is substantially wrong or answers a different question.

Two rules that override your instincts:

- Never penalize the assistant for including MORE correct, consistent detail than the reference. The reference is a floor, not a ceiling. If everything the reference says is present and correct, the score is 2, regardless of extra material.
- Numbers count: a value that differs materially from the reference is an error, and a value with wrong or missing units is an error.

Respond with JSON only:

{"correctness": 0, "rationale": "one or two sentences explaining the score"}
