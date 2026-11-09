"""The five hook scenes call real operation adapters and persist verified pointers."""

import json


def test_five_routes_and_three_task_sop_are_pointer_only(tmp_path):
    from sci_rag.agent_memory import MemoryRouter

    calls = []

    def invoke(operation, payload):
        calls.append(operation)
        if operation == "refresh":
            return {"status": "success", "exit_code": 0}
        if operation == "search_corpus":
            return {
                "results": [{"document_id": "a" * 32, "text": "PRIVATE_BODY_MUST_NOT_BE_INJECTED"}]
            }
        return {
            "documents": [{"id": "a" * 32, "title": "PRIVATE_TITLE"}],
            "projects": [],
            "versions": [],
        }

    router = MemoryRouter(memory_dir=tmp_path, invoke=invoke)
    for scene in ["task_start", "retrieval", "file_write", "task_end", "scheduled"]:
        result = router.route(
            scene,
            query="Controlled query",
            project_id="b" * 32,
            path="ignored-local-file",
            task_id=scene,
            confirmed=scene == "task_end",
        )
        assert "PRIVATE_BODY" not in json.dumps(result) and "PRIVATE_TITLE" not in json.dumps(
            result
        )
    assert {
        "browse_corpus",
        "list_projects",
        "search_corpus",
        "get_document_versions",
        "refresh",
        "complete_task",
        "maintain_memory",
    } <= set(calls)
    for index in range(3):
        router.route("retrieval", query="Controlled query", task_id=str(index))
        router.route("task_end", task_id=str(index), confirmed=True)
    fresh = MemoryRouter(memory_dir=tmp_path, invoke=invoke)
    assert fresh.sop("retrieval").is_file()
    assert len((tmp_path / "global_mem_insight.txt").read_text(encoding="utf-8").splitlines()) <= 30
    assert list((tmp_path / "patches").glob("*.patch"))
    logs = (tmp_path / "router_events.jsonl").read_text(encoding="utf-8")
    assert (
        "Controlled query" not in logs
        and "ignored-local-file" not in logs
        and "PRIVATE" not in logs
    )


def test_unverified_tasks_never_create_sop(tmp_path):
    from sci_rag.agent_memory import MemoryRouter

    router = MemoryRouter(
        memory_dir=tmp_path, invoke=lambda op, data: {"status": "failed", "exit_code": 1}
    )
    for index in range(4):
        router.route("retrieval", task_id=str(index))
        router.route("task_end", task_id=str(index), confirmed=True)
    assert not router.sop("retrieval").exists()


def test_hot_index_is_a_bounded_patch_preserving_existing_rules(tmp_path):
    from sci_rag.agent_memory import MemoryRouter

    path = tmp_path / "global_mem_insight.txt"
    path.write_text("Verified rule stays here.\n", encoding="utf-8")
    router = MemoryRouter(
        memory_dir=tmp_path, invoke=lambda op, data: {"hot_document_ids": ["a" * 32, "b" * 32]}
    )
    router.route("scheduled")
    assert "Verified rule stays here." in path.read_text(encoding="utf-8")
    assert "a" * 32 in path.read_text(encoding="utf-8")
    router.invoke = lambda op, data: {"hot_document_ids": ["b" * 32, "a" * 32]}
    router.route("scheduled")
    content = path.read_text(encoding="utf-8")
    assert content.index("b" * 32) < content.index("a" * 32) and len(content.splitlines()) <= 30


def test_maintenance_document_count_is_not_a_document_list(tmp_path):
    from sci_rag.agent_memory import MemoryRouter

    router = MemoryRouter(
        memory_dir=tmp_path, invoke=lambda op, data: {"documents": 2, "hot_document_ids": []}
    )
    assert router.route("scheduled")["status"] == "success"


def test_new_sop_keeps_a_pointer_when_hot_index_is_full(tmp_path):
    from sci_rag.agent_memory import MemoryRouter

    target = tmp_path / "global_mem_insight.txt"
    target.write_text("".join(f"Verified rule {index}.\n" for index in range(18)), encoding="utf-8")
    router = MemoryRouter(
        memory_dir=tmp_path,
        invoke=lambda op, data: {"hot_document_ids": [f"{n:032x}" for n in range(10)]},
    )
    router.route("scheduled", task_id="maintenance")
    assert len(target.read_text(encoding="utf-8").splitlines()) == 30
    for index in range(3):
        router.route("retrieval", task_id=str(index))
        router.route("task_end", task_id=str(index), confirmed=True)
    content = target.read_text(encoding="utf-8")
    assert len(content.splitlines()) <= 30 and "pcmem_retrieval_sop.md" in content
    assert all(f"Verified rule {index}." in content for index in range(18))
