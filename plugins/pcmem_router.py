"""PC-Mem memory router (spec section 4.7, memory face).

Decides when the agent proactively consults the file knowledge base and what it
pulls in. This is the skeleton shipped in step 1: every trigger point is wired
to the GenericAgent hook bus (plugins.hooks) and records an auditable event; the
actual injections (project context, retrieval, version lookup) land in later
phases and must keep this file's contract:

- never modify GenericAgent seed code (agent_loop/ga/agentmain/llmcore);
- every invocation is logged to memory/router_events.log (no file content, no
  secrets, only event kind and identifiers);
- hooks receive a ctx dict and must return a dict.

Trigger map (spec 4.7):
  agent_before -> task start: project context + topic overview   (phase P5)
  tool_after   -> file_write/file_patch: record file event, run incremental channel 2
  scheduler    -> periodic reconcile / stale marking             (phase P5, external)
"""

import os
import time

import plugins.hooks as hooks

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(_ROOT, "memory", "router_events.log")


def _log(event: str, note: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {event}: {note}\n")
    except OSError:
        pass


@hooks.register("agent_before")
def on_task_start(ctx: dict) -> dict:
    """Task start: later injects project context and topic overview here."""
    _log("task_start", "router skeleton active; injection lands in P5")
    return ctx


@hooks.register("tool_after")
def on_tool_after(ctx: dict) -> dict:
    """Record file-mutating tool calls as file events for the incremental face."""
    tool_name = ctx.get("tool_name", "")
    if tool_name in ("file_write", "file_patch"):
        args = ctx.get("args") or {}
        path = str(args.get("path", ""))[:200]
        _log("file_event", f"{tool_name} {path}")
    return ctx
