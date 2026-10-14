"""sci-rag-kit: retrieval-augmented generation, built around your
scientific domain.

Point it at a folder of papers and reports, and it gives you a grounded,
citation-backed question-answering system for your field: ingestion with
structure-aware chunking, a knowledge graph stored natively in Postgres,
five fused retrieval layers, an honest evaluation harness, and serving
over REST and MCP.

The pieces are importable directly for notebook and library use::

    from sci_rag import Retriever, AnswerEngine, RetrievalScope

    retriever = Retriever()
    result = await retriever.retrieve("rice straw availability", profile="deep")

Exports resolve lazily (PEP 562), so ``import sci_rag`` stays cheap and
circular imports are impossible.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from typing import Any

try:
    #: Read from the installed distribution rather than declared here.
    #: A hand-maintained copy drifts, and this one had: v0.2.0 shipped
    #: reporting 0.1.0a0. `sci-rag-new` resolves the template tag from this
    #: same metadata, so the two cannot disagree about what version this is.
    __version__ = _installed_version("sci-rag-kit")
except PackageNotFoundError:  # pragma: no cover - only in a bare source tree
    __version__ = "0.0.0+unknown"

_EXPORTS: dict[str, str] = {
    # configuration and domain
    "Settings": "sci_rag.config",
    "get_settings": "sci_rag.config",
    "DomainProfile": "sci_rag.domain",
    "load_domain": "sci_rag.domain",
    # ingestion
    "CorpusEntry": "sci_rag.ingest",
    "discover_folder": "sci_rag.ingest",
    "load_manifest": "sci_rag.ingest",
    "ingest_entries": "sci_rag.ingest",
    # providers
    "get_embedder": "sci_rag.embed",
    "get_llm": "sci_rag.llm",
    # graph
    "extract_graph": "sci_rag.graph",
    "build_communities": "sci_rag.graph",
    # retrieval and answering
    "Retriever": "sci_rag.retrieve",
    "RetrievalResult": "sci_rag.retrieve",
    "RetrievalScope": "sci_rag.retrieve",
    "AnswerEngine": "sci_rag.answer",
    # evaluation
    "load_seed_questions": "sci_rag.evals",
    "run_retrieval_eval": "sci_rag.evals",
    "run_answer_eval": "sci_rag.evals",
    # serving
    "create_app": "sci_rag.server",
    "build_mcp_server": "sci_rag.server",
}

__all__ = ["__version__", *sorted(_EXPORTS)]


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module 'sci_rag' has no attribute {name!r}")
    return getattr(import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
