"""Unchanged files still retry a previously failed derived-knowledge update."""


async def test_unchanged_source_retries_failed_knowledge(
    clean_tables, tmp_path, local_embedder, monkeypatch
):
    from sci_rag.refresh import refresh_corpus

    calls = []

    async def knowledge(factory, embedder, *, update_graph, changed):
        calls.append(changed)
        return {
            "graph_status": "success",
            "metadata": {"inference_failed": 1 if len(calls) == 1 else 0},
        }

    monkeypatch.setattr("sci_rag.refresh._knowledge", knowledge)
    (tmp_path / "record.txt").write_text("Controlled retry source.", encoding="utf-8")
    first = await refresh_corpus(root=tmp_path, embedder=local_embedder, update_graph=False)
    second = await refresh_corpus(root=tmp_path, embedder=local_embedder, update_graph=False)
    assert first["status"] == "failed" and second["status"] == "success"
    assert second["counts"]["unchanged"] == 1 and calls == [True, True]
