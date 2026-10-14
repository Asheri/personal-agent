"""Using sci-rag as a Python library (for notebooks and embedding in apps).

Prerequisites, same as the CLI quickstart: a configured .env and a
migrated database (`make setup`). Then:

    uv run python examples/library_quickstart.py

The CLI is a thin wrapper over exactly these calls, so anything the CLI
does is available here too.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sci_rag import (
    AnswerEngine,
    RetrievalScope,
    Retriever,
    get_embedder,
    get_settings,
    ingest_entries,
    load_manifest,
)


async def main() -> None:
    # 1. Ingest the demo corpus (idempotent: already-ingested files skip).
    entries = load_manifest(Path("data/demo/manifest.jsonl"))
    report = await ingest_entries(entries, embedder=get_embedder(get_settings()))
    print(f"ingested={report.ingested} skipped={report.skipped} failed={report.failed}")

    # 2. Retrieval only: ranked evidence with per-layer traces.
    retriever = Retriever()
    result = await retriever.retrieve(
        "rice straw availability in the Colusa Basin",
        profile="interactive",
        limit=3,
        # Scoping works the same as everywhere else; None means unrestricted.
        scope=RetrievalScope(license_classes=("public", "open_commercial")),
    )
    for item in result.items:
        print(f"- {item.title} (layers: {'+'.join(item.layers)}, score {item.score:.4f})")
    print("stage statuses:", {t.stage: t.status for t in result.traces})

    # 3. A grounded answer (needs Google credentials; see .env.example).
    engine = AnswerEngine(retriever=retriever)
    try:
        answer = await engine.answer(
            "How much rice straw was generated in the Colusa Basin in 2023?",
            profile="interactive",
        )
        print("\n" + answer.text)
        for source in answer.cited_sources:
            print(f"  [{source.index}] {source.citation or source.title}")
    except RuntimeError as exc:
        print(f"\n(answer skipped: {exc})")


if __name__ == "__main__":
    asyncio.run(main())
