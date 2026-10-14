You are helping a scientist set up a knowledge base for their field. Draft the
ontology that a graph extractor will use to read their literature.

Project name: $PROJECT_NAME
Domain: $DESCRIPTION

Propose:

1. **Entity types**: 6 to 12 concepts an expert in this field would use to
   organize knowledge. Prefer the categories that appear in the field's own
   review articles over generic ones. Each needs a short description with two
   or three concrete examples, because the description is shown to the
   extraction model verbatim.
2. **Relation types**: 4 to 10 directed relationships between those entity
   types, named in SCREAMING_SNAKE_CASE and read as "source RELATION target".
3. **Query classes**: 3 to 6 kinds of question a user of this knowledge base
   would ask. Each needs keywords that identify it and a one-sentence
   instruction for writing a hypothetical answer passage to search with.

Return JSON only, with exactly this shape:

{
  "entity_types": [
    {"name": "Membrane", "description": "A separation layer (polyamide thin-film, ceramic, hollow fiber)"}
  ],
  "relation_types": [
    {"name": "REMOVES", "description": "A membrane or process removes a contaminant"}
  ],
  "query_classes": [
    {
      "name": "performance",
      "keywords": ["flux", "rejection", "permeability"],
      "hyde_instruction": "Write a passage reporting membrane performance figures."
    }
  ]
}

Use only the field's real vocabulary. Do not invent entity types to fill a
quota, and do not include commentary outside the JSON.
