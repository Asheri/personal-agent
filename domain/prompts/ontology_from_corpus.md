You are helping a scientist tune the ontology a graph extractor uses to read
their literature. Unlike a cold draft, you can see what their documents
actually say.

Project: $DOMAIN_NAME
Domain: $DESCRIPTION

Current ontology:

$EXISTING_ONTOLOGY

Real passages from the collection, numbered and labeled with the document they
came from:

$PASSAGES

Judge the ontology against those passages, not against what the field might
contain in general. A type nothing in the corpus instantiates costs extraction
time and returns nothing; a concept the passages keep naming with no type to
hold it is evidence lost.

Requirements either way:

1. **Entity types**: 6 to 12 concepts, named in the field's own vocabulary as
   the passages use it. Each needs a short description with two or three
   concrete examples, because the description is shown to the extraction model
   verbatim.
2. **Relation types**: 4 to 10 directed relationships, named in
   SCREAMING_SNAKE_CASE and read as "source RELATION target".
3. **Query classes**: 3 to 6 kinds of question a user of this knowledge base
   would ask, each with keywords that identify it and a one-sentence
   instruction for writing a hypothetical answer passage to search with.

**If a current ontology is shown above**, do not rewrite it. Return only what
you would add and what you would remove, and give a reason for every removal
that points at the passages:

{
  "additions": {
    "entity_types": [{"name": "Pretreatment", "description": "A step before conversion (alkali soak, steam explosion)"}],
    "relation_types": [{"name": "PRECEDES", "description": "One process runs before another"}],
    "query_classes": [{"name": "economics", "keywords": ["cost", "price"], "hyde_instruction": "Write a cost analysis passage."}]
  },
  "removals": [
    {"kind": "entity_type", "name": "Equipment", "reason": "no sampled passage names machinery"}
  ]
}

Leave an additions list empty rather than padding it, and return no removals at
all if every current type earns its place.

**If the current ontology section says there is none yet**, return the full
ontology instead:

{
  "entity_types": [{"name": "Feedstock", "description": "A biomass or residue stream (rice straw, almond prunings)"}],
  "relation_types": [{"name": "CONVERTED_BY", "description": "A feedstock is converted by a process"}],
  "query_classes": [{"name": "availability", "keywords": ["tons", "acreage"], "hyde_instruction": "Write a resource assessment passage."}]
}

Use only vocabulary the passages support. Do not invent types to fill a quota,
and add no commentary outside the JSON.
