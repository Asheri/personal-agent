You are building a knowledge graph for this domain: $DOMAIN_NAME.

Read the numbered passages below and extract the entities and relationships they state. The passages may be in Chinese or English; keep entity names in the language the text uses. Use ONLY these entity types:

$ENTITY_TYPES

And ONLY these relationship types (each one reads "source RELATION target"):

$RELATION_TYPES

Rules:
- Extract what the text actually says. Never invent facts to complete the graph.
- Use the most canonical short name for each entity ("季度评审", not "上面提到的那次季度评审").
- List aliases only when the passage actually uses that surface form for the entity. Never invent synonyms.
- A relationship's source and target must both appear in your entities list.
- For each relationship, copy the exact phrase that states it into "evidence" and reference the passage number it came from.
- Assign each relationship a confidence: 1.0 when directly stated, 0.7 when strongly implied, or 0.4 when inferred across sentences.
- PART_OF is entity level ("person PART_OF project"). SUPERSEDES is content level ("this document replaces that one") and never describes file revisions of one file; leave that to the version chain.
- If a passage contains nothing extractable, contribute nothing from it.

Passages:

$PASSAGES

Respond with JSON only, in exactly this shape ("passages" lists the passage numbers where the entity appears):

{
  "entities": [
    {"name": "季度评审", "type": "Event", "description": "one short sentence", "passages": [1, 2], "aliases": ["Q3 review"]}
  ],
  "relationships": [
    {"source": "张三", "target": "季度评审", "type": "PART_OF", "evidence": "quoted phrase", "passage": 1, "confidence": 1.0}
  ]
}
