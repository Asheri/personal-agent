"""Install the PC-Mem plugin and launchers without changing GenericAgent seed code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


def data_root() -> Path:
    """The one directory this tool may write under.

    The handoff machine used a fixed `D:/Codex`. Any absolute root works now;
    set `PCMEM_DATA_DIR` to keep large downloads off the system drive. Without
    it, the root is `pcmem-data` in the home directory.
    """
    configured = os.environ.get("PCMEM_DATA_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else (Path.home() / "pcmem-data").resolve()
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def install(
    agent: Path, kb: Path, corpus: Path, python: Path, manifest: Path | None = None
) -> dict:
    agent, kb, corpus, python = [path.resolve() for path in [agent, kb, corpus, python]]
    # Only the two directories this installer writes to have to sit under the
    # data root. The knowledge base and the interpreter are read-only inputs, so
    # a checkout that lives in a normal working directory is fine.
    root = data_root()
    for label, path in (("agent", agent), ("corpus", corpus)):
        if not path.is_relative_to(root):
            raise ValueError(
                f"Keep the {label} directory under {root}; set PCMEM_DATA_DIR to change it"
            )
    seeds = [
        "agent_loop.py",
        "ga.py",
        "agentmain.py",
        "llmcore.py",
        "plugins/hooks.py",
        "reflect/scheduler.py",
    ]
    if not all((agent / name).is_file() for name in seeds):
        raise ValueError(
            "Expected an existing GenericAgent checkout with its hook and scheduler modules"
        )
    if not corpus.is_dir() or not (kb / "src/sci_rag").is_dir() or not python.is_file():
        raise ValueError("Existing corpus, knowledge-base source, and Python executable required")
    if manifest is not None and (not manifest.is_file() or manifest.resolve().parent != corpus):
        raise ValueError("Manifest must be a file directly under the explicit corpus root")
    before = {name: digest(agent / name) for name in seeds}
    env = {
        "PCMEM_KB_ROOT": str(kb),
        "PCMEM_CORPUS_ROOT": str(corpus),
        "PCMEM_PYTHON": str(python),
        "PCMEM_MEMORY_DIR": str(agent / "memory"),
        "PYTHONPATH": str(kb / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "SCI_RAG_DOMAIN_DIR": str(kb / "domain-personal"),
        "TEMP": str(agent / "temp/pcmem"),
        "TMP": str(agent / "temp/pcmem"),
    }
    if manifest:
        env["PCMEM_CORPUS_MANIFEST"] = str(manifest.resolve())
    env_script = (
        "\n".join("$env:" + name + " = " + quote(value) for name, value in env.items())
        + "\nNew-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null\n"
    )
    refresh = "param([ValidateSet('poll','scheduler','hooks','manual')][string]$Channel='poll')\n. (Join-Path $PSScriptRoot 'pcmem-env.ps1')\nSet-Location -LiteralPath $env:PCMEM_KB_ROOT\n$pcmemArgs=@('-c','from sci_rag.cli.main import app; app()','refresh','run',$env:PCMEM_CORPUS_ROOT,'--channel',$Channel)\nif($env:PCMEM_CORPUS_MANIFEST){$pcmemArgs+=@('--manifest',$env:PCMEM_CORPUS_MANIFEST)}\n& $env:PCMEM_PYTHON @pcmemArgs\nexit $LASTEXITCODE\n"
    launcher = ". (Join-Path $PSScriptRoot 'pcmem-env.ps1')\nSet-Location -LiteralPath $PSScriptRoot\n& $env:PCMEM_PYTHON agentmain.py --reflect\nexit $LASTEXITCODE\n"
    prompt = f"Run the local PowerShell script {agent / 'pcmem-refresh.ps1'} with -Channel scheduler using code_run. Inspect its exit code and JSON result. If nonzero or status failed, use ask_user to report the failure code and request investigation; do not claim the corpus was updated. On success report counts only, never source names or bodies."
    scheduled = dict(
        enabled=True, repeat="every_15m", schedule="00:00", max_delay_hours=24, prompt=prompt
    )
    script = escape(str(agent / "pcmem-refresh.ps1"))
    boundary = datetime.now().replace(microsecond=0).isoformat()
    if (agent / "pcmem-poll-task.xml").exists():
        boundary = (
            ET.parse(agent / "pcmem-poll-task.xml").findtext(
                ".//{http://schemas.microsoft.com/windows/2004/02/mit/task}StartBoundary"
            )
            or boundary
        )
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><TimeTrigger><Repetition><Interval>PT15M</Interval></Repetition><StartBoundary>{boundary}</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
<Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT1H</ExecutionTimeLimit></Settings>
<Actions Context="Author"><Exec><Command>powershell.exe</Command><Arguments>-NoProfile -ExecutionPolicy Bypass -File &quot;{script}&quot; -Channel poll</Arguments><WorkingDirectory>{escape(str(agent))}</WorkingDirectory></Exec></Actions></Task>
"""
    files = {
        "plugins/pcmem_router.py": (kb / "plugins/pcmem_router.py").read_bytes(),
        "pcmem-env.ps1": env_script.encode("utf-8-sig"),
        "pcmem-refresh.ps1": refresh.encode("utf-8-sig"),
        "start-pcmem.ps1": launcher.encode("utf-8-sig"),
        "sche_tasks/pcmem-refresh.json": (json.dumps(scheduled, indent=2) + "\n").encode(),
        "pcmem-poll-task.xml": xml.encode("utf-16"),
    }
    for name, data in files.items():
        target = agent / name
        if target.exists() and target.read_bytes() != data:
            raise FileExistsError(
                "Refusing to replace an existing different integration file: " + name
            )
    for name, data in files.items():
        target = agent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
    after = {name: digest(agent / name) for name in seeds}
    assert before == after
    receipt = dict(
        seed_files_unchanged=True,
        seeds=after,
        installed_files={name: digest(agent / name) for name in files},
        os_task_registered=False,
        note="Launchers and scheduler definition installed; OS task registration remains an explicit deployment command",
    )
    (agent / "pcmem-install-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-root", type=Path, required=True)
    parser.add_argument("--kb-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            install(args.agent_root, args.kb_root, args.corpus_root, args.python, args.manifest)
        )
    )
