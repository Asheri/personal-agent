"""Run the pinned upstream hook/dispatch/scheduler protocols against a local corpus."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from install_pcmem_agent import install
from prepare_agent_fixture import prepare
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from sci_rag.config import get_settings
from sci_rag.db import Base, Document, dispose_engine, get_engine, get_session_factory
from sci_rag.db.models import FileEvent


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def seed() -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.database_url != os.environ.get("SCI_RAG_TEST_DATABASE_URL")
        or url.host != "127.0.0.1"
        or not (url.database or "").endswith("_test")
    ):
        raise ValueError("Explicit loopback disposable database required")
    async with get_engine().begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await dispose_engine()


async def snapshot() -> dict:
    async with get_session_factory()() as session:
        docs = list((await session.scalars(select(Document))).all())
        runs = list((await session.scalars(select(FileEvent).where(FileEvent.kind == "run"))).all())
    result = dict(
        documents=[
            dict(
                id=row.id,
                license_class=row.license_class,
                is_current=row.is_current,
                access_count=row.access_count,
            )
            for row in docs
        ],
        runs=[dict(channel=row.channel, status=row.status, counts=row.counts) for row in runs],
    )
    await dispose_engine()
    return result


def run(args: argparse.Namespace) -> None:
    kb = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    provenance = prepare(args.agent, ref=args.ref)
    save(args.output / "upstream-provenance.json", provenance)
    args.corpus.mkdir(parents=True, exist_ok=True)
    manifest = args.corpus / "corpus.jsonl"
    rows = []
    for name, license_class, body in [
        (
            "visible.txt",
            "public",
            "Controlled source AGENTCONTROL2026 documents the confirmed experiment.",
        ),
        ("second.txt", "public", "A second local AGENTCONTROL2026 reference is available."),
        ("private.txt", "unknown", "PRIVATE_BODY_CANARY AGENTCONTROL2026 must stay private."),
    ]:
        path = args.corpus / name
        path.write_text(body, encoding="utf-8")
        rows.append(dict(path=name, license_class=license_class))
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    asyncio.run(seed())
    receipt = install(args.agent, kb, args.corpus, Path(sys.executable), manifest)
    assert (
        install(args.agent, kb, args.corpus, Path(sys.executable), manifest)["seeds"]
        == receipt["seeds"]
    )
    save(args.output / "installation.json", receipt)
    os.environ.update(
        PCMEM_KB_ROOT=str(kb),
        PCMEM_CORPUS_ROOT=str(args.corpus),
        PCMEM_CORPUS_MANIFEST=str(manifest),
        PCMEM_PYTHON=sys.executable,
        PCMEM_MEMORY_DIR=str(args.agent / "memory"),
    )
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def refresh_command(channel: str) -> list[str]:
        """The launcher the installed integration would run for this channel.

        Windows runs the generated PowerShell wrapper. macOS and Linux run the
        same one-shot refresh directly, because this project only ships a
        Windows scheduler today and the channel contract is the CLI call.
        """
        if os.name == "nt":
            return [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(args.agent / "pcmem-refresh.ps1"),
                "-Channel",
                channel,
            ]
        return [
            sys.executable,
            "-c",
            "from sci_rag.cli.main import app; app()",
            "refresh",
            "run",
            str(args.corpus),
            "--channel",
            channel,
            "--manifest",
            str(manifest),
        ]

    def refresh(channel):
        result = subprocess.run(
            refresh_command(channel),
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=flags,
        )
        save(
            args.output / ("launcher-" + channel + ".json"),
            dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr),
        )
        assert result.returncode == 0, result.stdout + result.stderr

    refresh("poll")
    sys.path.insert(0, str(args.agent))
    hooks = importlib.import_module("plugins.hooks")
    importlib.import_module("plugins.pcmem_router")
    loop = importlib.import_module("agent_loop")

    class Handler(loop.BaseHandler):
        def __init__(self):
            self.parent = SimpleNamespace(task_dir=None)

        def _get_abs_path(self, path):
            return str((args.corpus / path).resolve())

        def do_file_write(self, arguments, response):
            Path(self._get_abs_path(arguments["path"])).write_text(
                "Updated controlled AGENTCONTROL2026 experiment source.", encoding="utf-8"
            )
            return loop.StepOutcome({"status": "success"}, next_prompt="verified")

        def do_start_long_term_update(self, arguments, response):
            return loop.StepOutcome("Read verified memory policy", next_prompt="verified")

    handler = Handler()
    contexts = []
    for index in range(3):
        ctx = {
            "handler": handler,
            "messages": [{"role": "user", "content": "find AGENTCONTROL2026"}],
        }
        hooks.trigger("agent_before", ctx)
        assert all(row["status"] == "success" for row in ctx["pcmem_results"]), ctx
        contexts.extend(ctx["pcmem_results"])
        outcome = loop.exhaust(handler.dispatch("start_long_term_update", {}, None))
        assert "PC-Mem pointers" in outcome.next_prompt
        save(args.output / "progress.json", dict(completed_tasks=index + 1))
    assert (args.agent / "memory/pcmem_retrieval_sop.md").is_file()
    # A fresh router instance must see and reuse the persisted SOP.
    plugin = importlib.import_module("plugins.pcmem_router")
    plugin._routers.clear()
    fresh = {
        "handler": Handler(),
        "messages": [{"role": "user", "content": "find AGENTCONTROL2026"}],
    }
    hooks.trigger("agent_before", fresh)
    assert any(row.get("sop") == "pcmem_retrieval_sop.md" for row in fresh["pcmem_results"])
    written = loop.exhaust(handler.dispatch("file_write", {"path": "visible.txt"}, None))
    assert "PC-Mem pointers" in written.next_prompt
    spec = importlib.util.spec_from_file_location(
        "pcmem_upstream_scheduler", args.agent / "reflect/scheduler.py"
    )
    scheduler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scheduler)
    try:
        prompt = scheduler.check()
        assert prompt and "pcmem-refresh" in prompt and "ask_user" in prompt
        refresh("scheduler")
    finally:
        scheduler._lock.close()
    scheduled = {"handler": handler}
    hooks.trigger("scheduler", scheduled)
    assert scheduled["pcmem_results"][0]["status"] == "success"
    state = asyncio.run(snapshot())
    assert {row["channel"] for row in state["runs"]} == {"poll", "hooks", "scheduler"}
    assert all(row["status"] == "success" for row in state["runs"])
    private = {row["id"] for row in state["documents"] if row["license_class"] == "unknown"}
    injected = {key for row in contexts + fresh["pcmem_results"] for key in row["document_ids"]}
    assert injected and not (injected & private)
    assert any(
        row["access_count"] > 0 for row in state["documents"] if row["license_class"] == "public"
    )
    logs = (args.agent / "memory/router_events.jsonl").read_text(encoding="utf-8")
    assert all(
        word not in logs
        for word in ["AGENTCONTROL2026", "PRIVATE_BODY", "visible.txt", "private.txt"]
    )
    assert (
        len((args.agent / "memory/global_mem_insight.txt").read_text(encoding="utf-8").splitlines())
        <= 30
    )
    seed_hashes = {
        name: hashlib.sha256((args.agent / name).read_bytes()).hexdigest()
        for name in receipt["seeds"]
    }
    assert seed_hashes == receipt["seeds"]
    import shutil

    for path in (args.agent / "memory").rglob("*"):
        if path.is_file():
            target = args.output / "memory" / path.relative_to(args.agent / "memory")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    save(
        args.output / "summary.json",
        dict(
            status="passed",
            seeds_unchanged=True,
            confirmed_tasks=3,
            new_session_sop_reused=True,
            private_pointer_leaks=0,
            channels=sorted({row["channel"] for row in state["runs"]}),
            state=state,
            scenes=["task_start", "retrieval", "file_write", "task_end", "scheduled"],
            limits="Pinned upstream hook/dispatch/scheduler protocols and local CLI tested with a controlled handler. No live model conversation, personal corpus, or persistent OS task registration.",
        ),
    )
    print(
        json.dumps(
            dict(status="passed", confirmed_tasks=3, channels=["hooks", "poll", "scheduler"])
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--ref",
        default=None,
        help="GenericAgent branch or tag to fetch the fixture from (default main)",
    )
    run(parser.parse_args())
