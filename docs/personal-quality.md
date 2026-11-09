# Controlled personal-file quality

The acceptance runner exercises actual extraction, ownership, and source-linked
answers on a fixed fictional corpus. Its results measure this controlled task;
they do not establish real-user or course acceptance.

The user selected controlled inputs. Twenty positive model-ownership cases cover
Markdown, TXT, HTML, PDF, DOCX, and PPTX. Eight controls distinguish manual locks,
directory rules, unclassified generic text, and unknown/private rights. A prior
revision on one path must remain outside current retrieval. Protected inputs use
local hash embeddings and are excluded from generation and semantic-model calls.

The JSON source facts enumerate named entities and directed triples. The scorer
reports precision, recall, and F1 against those exact constructed facts, ownership
separately from manual/rule precedence, and actual relation quote provenance.
Answer checks record required terms, prohibited old-version terms, valid citation
IDs, expected cited projects, and refusal cues. Read the retained answers: a
mechanical pass alone cannot establish correct attribution or meaning.

The first trials failed extraction gates despite passing ownership and answer
checks. They are retained. Changes use declared development cases, but the original
corpus was evaluated repeatedly; its final scores are exploratory matched results,
not a blinded held-out benchmark. The historical development/heldout tags do not
change that limitation. Labels have no independent human approval.

The local configuration uses Qwen2.5-7B-Instruct Q4_K_M for generation and
Qwen3-Embedding-0.6B Q8_0 with 1024 dimensions for semantic retrieval. Hashes,
revisions, runtime tag, raw responses, source identities, and commands accompany
the dated evidence. Both answer configurations use the same semantic vectors,
keyword index, sources, generation model, and source limit. KG adds the real graph
stage; communities, HyDE, reranking, citation expansion, and compression stay off
for this comparison. No model self-grader supplies the correctness labels.

`scripts/run_personal_quality.py` requires an explicit loopback database whose
name ends in `_test`. Its seed phase resets only that selected test schema; never
point it at a retained database. Generated format files belong in a disposable
D-drive directory. The evaluate phase retains model output and answer evidence.
The dated handoff includes exact setup commands for its isolated native database
and two loopback model endpoints. The evaluation embedding adapter does not add
an application provider or change deployment defaults.

For the measured 7B setup, pass `--batch-size 1` to `sci-rag graph extract` or
`sci-rag build`. Larger extraction batches need separate accuracy evidence;
the global default is unchanged. Existing invalid graph rows need an explicit,
reviewed rebuild; new validation does not repair historical rows automatically.

See [ADR 0018](adr/0018-grounded-extraction.md) for name, type, and evidence checks,
and [Chinese retrieval](chinese-retrieval.md) for the separate query spike.

The answer prompt requests facts separated by source. Citation metadata accepts
single numbers, comma-separated lists, and numeric ranges emitted by the tested
model. It marks only retrieved source indices, without expanding unbounded ranges
or changing the model's text. This syntax support does not validate claim meaning.
