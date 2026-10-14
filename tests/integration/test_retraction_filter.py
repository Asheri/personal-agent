from pathlib import Path

import pytest
from sqlalchemy import update

from sci_rag.answer import AnswerEngine
from sci_rag.db import Document, get_session_factory
from sci_rag.domain import load_domain
from sci_rag.ingest import CorpusEntry, ingest_entries
from sci_rag.llm import MockLLM
from sci_rag.retrieve import RetrievalScope, Retriever

pytestmark = pytest.mark.integration

DOMAIN_DIR = Path(__file__).parents[2] / "domain"
RETRACTED_PHRASE = "withdrawn catalytic conversion result"
CURRENT_PHRASE = "replicated catalytic conversion result"


async def test_answer_excludes_known_retracted_documents_by_default(
    clean_tables, local_embedder, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    retracted = tmp_path / "retracted.md"
    retracted.write_text(
        f"This paper reports a {RETRACTED_PHRASE} for rice straw under mild conditions."
    )
    current = tmp_path / "current.md"
    current.write_text(
        f"This paper reports a {CURRENT_PHRASE} for rice straw under mild conditions."
    )
    await ingest_entries(
        [
            CorpusEntry(path=retracted, title="Retracted result", doi="10.1000/retracted"),
            CorpusEntry(path=current, title="Current result", doi="10.1000/current"),
        ],
        embedder=local_embedder,
    )
    async with get_session_factory()() as session:
        await session.execute(
            update(Document)
            .where(Document.doi == "10.1000/retracted")
            .values(extra={"crossref": {"is_retracted": True}})
        )
        await session.commit()

    llm = MockLLM(default_response="The current evidence supports this result [1].")
    retriever = Retriever(
        domain=load_domain(DOMAIN_DIR),
        embedder=local_embedder,
        llm=llm,
        session_factory=get_session_factory(),
    )
    answer = await AnswerEngine(retriever=retriever, llm=llm).answer(
        "catalytic conversion result for rice straw",
        profile="interactive",
        limit=10,
    )

    content = " ".join(item.content for item in answer.retrieval.items)
    assert CURRENT_PHRASE in content
    assert RETRACTED_PHRASE not in content

    opted_in = await AnswerEngine(retriever=retriever, llm=llm).answer(
        "catalytic conversion result for rice straw",
        profile="interactive",
        limit=10,
        scope=RetrievalScope(exclude_retracted=False),
    )
    opted_in_content = " ".join(item.content for item in opted_in.retrieval.items)
    assert RETRACTED_PHRASE in opted_in_content

    raw = await retriever.retrieve(
        "catalytic conversion result for rice straw", profile="interactive", limit=10
    )
    assert RETRACTED_PHRASE in " ".join(item.content for item in raw.items)
