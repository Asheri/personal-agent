"""Opt-in PC-Mem routes for the unchanged GenericAgent hook bus."""
import json
import os
from pathlib import Path
from uuid import uuid4

import plugins.hooks as hooks

_routers = {}


def _router(ctx):
    injected = ctx.get("pcmem_router")
    if injected is not None:
        return injected
    root = os.environ.get("PCMEM_KB_ROOT")
    if not root:
        return None
    from sci_rag.agent_backend import CliAgentClient
    from sci_rag.agent_memory import MemoryRouter
    key = str(Path(root).resolve())
    if key not in _routers:
        directory = Path(os.environ.get("PCMEM_MEMORY_DIR", str(Path(__file__).resolve().parents[1] / "memory")))
        _routers[key] = MemoryRouter(memory_dir=directory, invoke=CliAgentClient(Path(root), os.environ.get("PCMEM_PYTHON")))
    return _routers[key]


def _invoke(ctx, scene, **values):
    router = _router(ctx)
    if router is None:
        return ctx
    handler = ctx.get("handler") or ctx.get("self")
    task_id = str(ctx.get("task_id") or getattr(handler,"_pcmem_task_id",None) or id(handler))
    result = router.route(scene, task_id=task_id, project_id=ctx.get("project_id"), **values)
    ctx.setdefault("pcmem_results", []).append(result)
    message = next((row for row in reversed(ctx.get("messages") or []) if isinstance(row, dict) and row.get("role") == "user"), None)
    if message is not None:
        text = "\n[PC-Mem pointers] " + json.dumps(result, ensure_ascii=False)
        if isinstance(message.get("content"), str):
            message["content"] += text
        elif isinstance(message.get("content"), list):
            message["content"].append({"type": "text", "text": text})
    elif ctx.get('ret') is not None:
        outcome=ctx['ret']
        outcome.next_prompt=(outcome.next_prompt or '')+'\n[PC-Mem pointers] '+json.dumps(result,ensure_ascii=False)
    return ctx


@hooks.register("agent_before")
def on_task_start(ctx):
    handler=ctx.get('handler') or ctx.get('self')
    if handler is not None and not ctx.get('task_id'):
        handler._pcmem_task_id=uuid4().hex
    query = ctx.get("query")
    if query is None:
        message = next((row for row in reversed(ctx.get("messages") or []) if isinstance(row, dict) and row.get("role") == "user"), {})
        query = message.get("content", "")
    _invoke(ctx, "task_start")
    if isinstance(query, str) and any(token in query.lower() for token in ["查找", "检索", "搜索", "哪份", "哪个项目", "search", "find", "retrieve"]):
        _invoke(ctx, "retrieval", query=query)
    return ctx


@hooks.register("tool_after")
def on_tool_after(ctx):
    name = ctx.get("tool_name", "")
    args = ctx.get("args") or {}
    if name in {"file_write", "file_patch"}:
        ret = ctx.get("ret")
        data=getattr(ret,'data',ret)
        success = ctx.get('success') is True or (isinstance(data,dict) and data.get('status')=='success')
        if success:
            path=str(args.get('path') or args.get('file_path') or '')
            handler=ctx.get('handler') or ctx.get('self')
            if handler is not None and hasattr(handler,'_get_abs_path'):
                path=handler._get_abs_path(path)
            return _invoke(ctx, "file_write", path=path)
    if name == "start_long_term_update":
        return _invoke(ctx, "task_end", confirmed=True)
    return ctx


@hooks.register("scheduler")
def on_scheduler(ctx):
    return _invoke(ctx, "scheduled")
