# Document relations supplement, v1.5 candidate

This serial candidate extends pending v1.2 through v1.4 code. The reviewed baseline
remains v1.1 until a real nonauthor reviewer adopts a revision.

Scope: C-4 through C-9, F3 and shared Agent read interfaces, components of A3-1 through
A3-9. It is not full priority-5, Chinese retrieval, model-quality, or course acceptance.

Revision 0010 adds raw document vector means, embedding versions, and mention citation
keys/source chunks/confidence. Means are refreshed with ingestion and re-embedding.
Similarity centers over the visible same-version corpus, never a private global mean.
Literal links/DOIs can be built without models; ambiguous keys remain unresolved and
later builds can resolve new targets. Cached Crossref references take precedence for
the same pair. Reads verify both endpoints and the citing chunk/literal evidence.

Retained versions remain authoritative on Document; project relationships remain its
single-owner field. The explicit version tool includes history while preserving other
filters and hiding inaccessible predecessor ids. No generic duplicate edge table, new
runtime dependency, changed retrieval weights, or automatic citation expansion is added.
Empty migrations round-trip; populated new relation data refuses destructive downgrade.

Local testing is explicitly authorized for this stage in a disposable D-drive database.
The actual MCP registry and REST service are exercised; this does not constitute external
Agent deployment or real-model multi-file reasoning. Prior reconcile tests run on the
current candidate and do not rewrite historical evidence for the prior snapshot.

Chinese keyword/routing and the earlier 7/15 extraction result remain unresolved. Future
semantic validation needs representative reviewed files and actual model evidence. Full
F3 and course acceptance must not be inferred from controlled-vector/API checks alone.
