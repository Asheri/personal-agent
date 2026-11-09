---
title: Document versions
description: Keep source copies and revisions separate while retrieving current evidence.
---

# Document versions

Local source identity uses the canonical absolute path and a stable member key.
Equal text at two paths creates two documents. Ingesting an unchanged source skips it;
editing its parsed content creates a new revision and retains its previous chunks.
A revert to earlier content creates another revision. Case and section changes are
checked even if normalized content hashes match.

Install and migrate using the existing project commands after reviewing the pending
v1.2 candidate and backing up any existing database. Revision 0008 adds identity and
version fields. It supports fresh installations and recorded paths from older data.
Validation for this handoff uses a new disposable database; it does not upgrade an
existing user database.

## Current and historical reads

Retrieval, document lists and details, default exports, and MCP evidence tools use
current documents. A version switch invalidates affected graph aggregates until current
evidence is rebuilt. Deleting a revision reconnects the remaining chain and promotes
the last survivor. Old source content stays in its document and chunk rows.
Deleting attributed evidence also clears affected shared descriptions and aliases,
so deleted facts cannot survive in a current aggregate.

Python callers can explicitly request history:

```python
from sci_rag.retrieve import RetrievalScope

history = RetrievalScope(include_superseded=True)
```

Pass that scope to the existing retriever or exporter. Default exports include
`version_seq` and `is_current`, while internal identity keys and hidden predecessor ids
are excluded. No new public history endpoint or filesystem watcher is added here.

## Upgrade and rollback limits

The upgrade reconstructs chains from recorded absolute paths and ingestion order.
Unknown paths receive separate legacy identities. It cannot recover copies that an
older global deduplication already discarded. A rename is a different path and needs
separate cross-file version inference if the application wants to connect it.

Downgrade refuses data that the old schema cannot represent, including retained history
and equal-content copies. No rows are silently collapsed. Keep a database backup and
choose an explicit conversion before retrying. The corpus inventory snapshot contains
hashes and counts; it is not a backup of source content.

Automatic reconciliation, scheduling, fingerprint skips, project inference, and a
temporal knowledge graph remain separate tasks. Formal nonauthor review of the v1.2
candidate and its implementation is still required.
