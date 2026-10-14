"""The project factory: turn the running template into someone else's project.

This package is deliberately import-light. ``sci-rag-new`` starts a wizard
before it has a database, credentials, or a server, so nothing here may
import :mod:`sci_rag.db`, :mod:`sci_rag.server`, or :mod:`sci_rag.llm` at
module scope. The ontology drafter imports its LLM client inside the
function that needs it.

There are no template placeholders anywhere in this package. The kit stays a
runnable, CI-tested repository; the scaffold is a post-fetch applier that
rewrites configuration files in place (see ADR 0004).
"""

from __future__ import annotations

__all__ = ["answers", "apply", "licenses", "ontology", "questions", "runners", "wizard"]
