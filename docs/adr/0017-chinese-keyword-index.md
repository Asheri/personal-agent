# ADR 0017: Separate Chinese search tokens from the English index

Chinese queries need segmented terms while existing English retrieval keeps its
calibrated index and query behavior.

## Context

The English generated full-text column matches an unsegmented Chinese sentence
as one lexeme. The previous Chinese name probe returned no keyword candidates.
The reviewed specification requires a measured choice among pg_trgm, jieba, and
declared degradation, including query classification and routing.

## Decision

Retain the English index and add a jieba 0.42.1 search-mode token column, a
generated simple-language vector, and a GIN index in revision 0011. Use the same
tokenizer on index and query writes. ORM chunk events maintain derived tokens.
Chinese queries use OR terms; English queries keep their existing query path.
Add Chinese personal-domain classification and routing cues without changing
retrieval weights or enabling citation expansion.

The native PostgreSQL C locale returned no trigrams for the tested Chinese name.
Candidate B passed the identifier-only gate but failed every name and sentence
probe. Selecting it would retain the known empty Chinese-query failure. Candidate
D meets the original identifier gate and the additional name/sentence gates;
this interpretation is identified in the v1.6 candidate for nonauthor review.

## Consequences

One pinned runtime dependency and a derived index are added. Existing rows need
backfilling; downgrade can safely discard and later rebuild this cache. Fresh
upgrades account for the historical 0001 migration importing live ORM metadata.
Raw SQL content changes bypass ORM maintenance. A first query may pay tokenizer
initialization cost, and OR terms can broaden retrieval. The controlled spike
does not establish production latency or representative answer quality.

## Reversal conditions

Revisit the choice if a representative corpus fails the registered gates or
backfill and indexing costs exceed the deployment budget. Preserve the English
index, retain the measured matrix, and declare Chinese degradation if no tested
candidate meets the acceptance contract. Any such semantic change requires
nonauthor review under AGENTS.md section 5.
