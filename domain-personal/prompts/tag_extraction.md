# tag_extraction (draft prompt, consumed by the P2 automatic tag pass)

Extract 3 to 8 short topic tags for a personal file from its head (first $HEAD_CHARS characters of text, plus file name $FILE_NAME). Tags go to the automatic tag column; the user's manual tags are never overwritten.

Rules:
- Tags are 1 to 4 words (or 2 to 6 Chinese characters), lowercase for ASCII, no punctuation.
- Prefer concrete subjects ("合同评审", "transformer 量化") over generic words ("document", "工作").
- Never output a person name as a tag; people are entities, not tags.
- If nothing extractable, answer with an empty list.

Respond with JSON only:

{"tags": ["tag one", "tag two"]}
