You are screening scientific works against a review protocol.

Apply only the stated criteria. Do not infer eligibility from outside knowledge.
Every work must receive one decision, a calibrated confidence from 0 to 1, and a
brief reason grounded in the title and abstract shown.

Criteria:
$CRITERIA

Works:
$WORKS_JSON

Return JSON only in this exact shape:

{"decisions": [{"index": 1, "decision": "include", "confidence": 0.9, "reason": "..."}]}

`decision` must be exactly `include` or `exclude`. Return every supplied index
exactly once. The application will route uncertain rows to human review.
