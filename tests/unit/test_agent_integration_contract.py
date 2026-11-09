"""The GenericAgent integration contract, checkable without installing it.

GenericAgent is not vendored. Three things make that safe, and this file is
where each one is pinned:

1. The only upstream file this project imports, `plugins/hooks.py`, is stored
   byte for byte and its git blob is recorded here. If the local copy changes,
   or the pinned blob changes without a matching update, the contract fails.
2. The router may only call the seven functions that file defines. An AST scan
   reads the source rather than trusting a review.
3. The installer adds seven files and touches none of the six upstream seed
   files. That is what "no vendoring and no modification" has to mean in code.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK_BUS = ROOT / "plugins" / "hooks.py"
ROUTER = ROOT / "plugins" / "pcmem_router.py"
FIXTURE = ROOT / "scripts" / "prepare_agent_fixture.py"
INSTALLER = ROOT / "scripts" / "install_pcmem_agent.py"

# What GenericAgent's hook bus offers. The router may use these and nothing
# else: anything more would mean this project depends on internals.
HOOK_API = frozenset(
    {"register", "trigger", "unregister", "clear", "has", "discover_and_load", "load"}
)

# The files `install()` writes into an agent checkout.
INSTALLED_FILES = frozenset(
    {
        "plugins/pcmem_router.py",
        "pcmem-env.ps1",
        "pcmem-refresh.ps1",
        "start-pcmem.ps1",
        "sche_tasks/pcmem-refresh.json",
        "pcmem-poll-task.xml",
        "pcmem-install-receipt.json",
    }
)

# The upstream files the installer hashes before and after, and never writes.
SEED_FILES = (
    "agent_loop.py",
    "ga.py",
    "agentmain.py",
    "llmcore.py",
    "plugins/hooks.py",
    "reflect/scheduler.py",
)


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def test_the_stored_hook_bus_is_the_pinned_one() -> None:
    fixture = _module(FIXTURE, "pcmem_prepare_agent_fixture")
    expected, strict = fixture.PINNED["plugins/hooks.py"]

    assert strict, "the hook bus is the one file whose change must fail the run"
    assert _git_blob(HOOK_BUS.read_bytes()) == expected


def test_only_the_hook_bus_is_pinned_strictly() -> None:
    fixture = _module(FIXTURE, "pcmem_prepare_agent_fixture")

    strict = sorted(name for name, (_, is_strict) in fixture.PINNED.items() if is_strict)

    assert strict == ["plugins/hooks.py"]
    assert set(fixture.FILES) == set(fixture.PINNED)


def test_the_router_calls_the_documented_hook_api_only() -> None:
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))

    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "hooks"
    }

    assert used <= HOOK_API, (
        f"the router reached past the documented API: {sorted(used - HOOK_API)}"
    )
    assert used, "the router should register and trigger through the hook bus"


def test_genericagent_would_discover_the_router_by_filename() -> None:
    # `discover_and_load` imports every `*.py` in `plugins/` whose name does not
    # start with an underscore. A rename that breaks that convention is silent.
    name = ROUTER.name

    assert name.endswith(".py")
    assert not name.startswith("_")
    assert name != "hooks.py"


def _fake_agent(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    agent = tmp_path / "GenericAgent"
    for name in SEED_FILES:
        target = agent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# seed {name}\n", encoding="utf-8")
    kb = tmp_path / "kb"
    (kb / "src" / "sci_rag").mkdir(parents=True)
    (kb / "plugins").mkdir(parents=True)
    (kb / "plugins" / "pcmem_router.py").write_text("# router\n", encoding="utf-8")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "corpus.jsonl").write_text("{}\n", encoding="utf-8")
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    return agent, kb, corpus, python


def test_the_installer_adds_only_its_own_files_and_keeps_every_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PCMEM_DATA_DIR", str(tmp_path))
    installer = _module(INSTALLER, "pcmem_install_agent")
    agent, kb, corpus, python = _fake_agent(tmp_path)
    before = {name: hashlib.sha256((agent / name).read_bytes()).hexdigest() for name in SEED_FILES}

    receipt = installer.install(agent, kb, corpus, python, corpus / "corpus.jsonl")

    written = {
        path.relative_to(agent).as_posix()
        for path in agent.rglob("*")
        if path.is_file() and path.relative_to(agent).as_posix() not in SEED_FILES
    }
    assert written == set(INSTALLED_FILES)
    after = {name: hashlib.sha256((agent / name).read_bytes()).hexdigest() for name in SEED_FILES}
    assert after == before
    assert receipt["seeds"] == before


def test_the_installed_scheduler_task_uses_the_upstream_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PCMEM_DATA_DIR", str(tmp_path))
    installer = _module(INSTALLER, "pcmem_install_agent")
    agent, kb, corpus, python = _fake_agent(tmp_path)
    installer.install(agent, kb, corpus, python)

    task = json.loads((agent / "sche_tasks" / "pcmem-refresh.json").read_text(encoding="utf-8"))

    # The keys reflect/scheduler.py reads when it picks up a task file.
    assert set(task) == {"enabled", "repeat", "schedule", "max_delay_hours", "prompt"}
    assert task["enabled"] is True
    assert "ask_user" in task["prompt"], "a failed refresh must be reported, not swallowed"


def test_the_installer_refuses_to_replace_a_different_integration_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PCMEM_DATA_DIR", str(tmp_path))
    installer = _module(INSTALLER, "pcmem_install_agent")
    agent, kb, corpus, python = _fake_agent(tmp_path)
    installer.install(agent, kb, corpus, python)
    (agent / "pcmem-refresh.ps1").write_text("# edited by the operator\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match=r"pcmem-refresh\.ps1"):
        installer.install(agent, kb, corpus, python)


def test_the_router_stays_importable_without_a_knowledge_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GenericAgent loads every plugin at startup; a missing KB must not crash it."""
    monkeypatch.delenv("PCMEM_KB_ROOT", raising=False)
    monkeypatch.syspath_prepend(str(ROOT))

    module = pytest.importorskip("plugins.pcmem_router")

    assert module._router({"messages": []}) is None
    context: dict[str, object] = {"messages": [{"role": "user", "content": "anything"}]}
    result = module._invoke(context, "retrieval")
    assert result is context, "an unrouted scene must pass the context through untouched"
    assert os.environ.get("PCMEM_KB_ROOT") is None
