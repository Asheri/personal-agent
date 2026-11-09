"""Fetch six exact public upstream files only for isolated integration checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen

COMMIT = "a9a36b4b219593369de01c3e5973e56ac02e568b"
FILES = {
    "agent_loop.py": "a744f0d2624e5f244927a2a03d66f41b56f94f85",
    "ga.py": "15fdb71bf9c7f45fd0be6236dd9a534072dce107",
    "agentmain.py": "3eb288c84e455d067327cd24bbb4e60228c9c837",
    "llmcore.py": "611e83556fb35a9f07ce5d13b092dacdebc35539",
    "plugins/hooks.py": "655fa3773fe39f0d9bfceeeceebd1db863832dc1",
    "reflect/scheduler.py": "a3ca622d3047a06f0d09f9493a641c63e77d4d34",
}


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


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def prepare(directory: Path) -> dict:
    directory = directory.resolve()
    root = data_root()
    if not directory.is_relative_to(root):
        raise ValueError(f"Keep fixtures under {root}; set PCMEM_DATA_DIR to change it")
    manifest = {}
    for name, expected in FILES.items():
        target = directory / name
        if target.exists():
            data = target.read_bytes()
            candidates = [data, data.rstrip(b"\n"), data.rstrip(b"\n") + b"\n"]
            data = next((value for value in candidates if blob(value) == expected), data)
        else:
            with urlopen(
                f"https://raw.githubusercontent.com/lsdefine/GenericAgent/{COMMIT}/{name}",
                timeout=60,
            ) as response:
                data = response.read()
        if blob(data) != expected:
            raise ValueError("Upstream file does not match its pinned Git blob: " + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = dict(git_blob=expected, sha256=hashlib.sha256(data).hexdigest())
    return dict(
        commit=COMMIT, repository="https://github.com/lsdefine/GenericAgent", files=manifest
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.directory), indent=2))
