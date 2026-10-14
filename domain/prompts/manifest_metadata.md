You are reading the opening pages of scientific documents and recording what
they say about themselves, so a corpus manifest can cite them correctly.

For each document below you are given its filename and the first part of its
text. Report only what the text actually states. An empty field is correct and
useful; a guessed one is a citation error that will travel into every answer
the document supports.

Use these source buckets where one fits:

$SOURCE_BUCKETS

A source bucket is a coarse grouping of where documents came from, in the
user's own vocabulary: "county_ag_reports", "journal_papers", "theses",
"agency_guidance". Three to six buckets across a whole collection is the right
number. Reuse a bucket above whenever it fits; propose a new one only when
nothing above describes the document, and list every bucket you used in
"source_buckets".

Documents:

$DOCUMENTS

Rules:

- **Never state a license.** Do not report a license class, and do not decide
  whether the document may be redistributed. If, and only if, the text contains
  an explicit license or rights statement, copy that sentence into
  "license_statement" character for character, exactly as it appears. If there
  is no such sentence, omit the field. Someone else decides what it means.
- **Title** is the document's own title, not the filename.
- **Authors** are people or organizations named as authors, each as one string.
- **Year** is the publication year as an integer, if the text gives one.
- **DOI** only if the text prints one. Never construct one.
- **Journal** only for a journal article that names its journal.
- Omit any field the text does not support.

Return JSON only, with exactly this shape:

{
  "source_buckets": ["county_ag_reports", "journal_papers"],
  "documents": [
    {
      "filename": "fresno_2023.pdf",
      "title": "Fresno County Crop Report 2023",
      "authors": ["Fresno County Dept. of Agriculture"],
      "year": 2023,
      "doi": "10.1000/example",
      "journal": "Journal of Example Studies",
      "source": "county_ag_reports",
      "license_statement": "the exact sentence from the text, or omit this field"
    }
  ]
}

Use the filename exactly as given, so each row can be matched back to its file.
Add no commentary outside the JSON.
