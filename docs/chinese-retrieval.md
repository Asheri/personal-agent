# Chinese retrieval

Chinese questions use a separate, segmented keyword index. English-only queries
retain the existing English full-text path. Fusion weights and default retrieval
profiles are unchanged.

Run `uv sync` and `sci-rag db upgrade` before using this candidate. Revision 0011
backfills `chunks.search_tokens` in batches of 500 and creates a GIN index on the
generated `search_zh_tsv` column. It retains the English index. The upgrade is
transactional and can hold write locks while backfilling a large corpus. Back up
the database and allow maintenance time; large-corpus duration is unmeasured.

The application maintains tokens on ORM chunk insert and update. Direct SQL
content writes bypass that maintenance and are outside the supported writer
contract. A downgrade removes only derived search columns and their index;
source text, vectors, file versions, projects, and graph evidence remain.

The index and query use the same pinned jieba search-mode tokenizer and a short
function-word stoplist. Chinese query terms use OR to tolerate absent question
words. This improves recall but can return irrelevant passages; a keyword hit
does not establish an answer. Values stay bound and query punctuation is removed
before token assembly. Source, license, current-version, and other retrieval
filters apply before ranking and limiting.

Personal-domain classes recognize literal Chinese keyword cues. The router adds
Chinese lookup, comparison, and overview cues, with comparison taking precedence.
English class matching retains its existing word boundaries.

The measured decision and limitations are in
[the Chinese spike](spikes/zh-keyword-spike.md). In particular, its latency covers
warm queries on 104 controlled chunks. Initial tokenizer loading took about
0.65 seconds on this host. Neither measurement is a large-corpus service SLA.
