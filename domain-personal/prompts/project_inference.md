# project_inference (draft prompt, consumed by the P2 project inference pass)

Decide which project a personal file belongs to, from its head (first $HEAD_CHARS characters of text, plus file name $FILE_NAME). Only these projects exist; a file may belong to none:

$PROJECT_LIST

Rules:
- Answer from evidence in the head only. If the head does not decide, answer null.
- Never invent a project that is not in the list.
- Confidence must be a number in [0, 1]; answer null when below 0.5.
- The caller keeps manual assignments and rule matches untouched; your output is the weakest source and can never overwrite them.

Respond with JSON only:

{"project": "<name from list or null>", "confidence": 0.0, "evidence": "quoted phrase or empty"}
