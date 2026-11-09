"""Fetch the six upstream GenericAgent files an isolated protocol check needs.

GenericAgent is not vendored. This script downloads exactly the files the
acceptance run imports or hashes, so nothing else from that repository lands on
disk.

**Why a blob is the pin, and a commit is not.** The handoff recorded commit
`a9a36b4b...`. That object no longer resolves in the public repository, so a
download addressed to it is a 404. A git blob hash is content addressable and
survives history rewrites, so `plugins/hooks.py` is pinned by blob and fetched
from a ref that exists (`main` by default). It is the one file whose API this
project calls, and a mismatch means the hook bus moved on.

The other five files are checked against their archived blob and reported as
drifted, without failing: they come from three-year-old history that GitHub no
longer serves, and the acceptance run only needs them to import and hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen

OWNER_REPO = "lsdefine/GenericAgent"
REPOSITORY = f"https://github.com/{OWNER_REPO}"

# The commit the handoff claimed. Kept for provenance; it does not resolve, so
# nothing is fetched from it. See the module docstring.
HISTORICAL_COMMIT = "a9a36b4b219593369de01c3e5973e56ac02a568b"

# The ref a download uses. Override with --ref or PCMEM_GENERICAGENT_REF.
DEFAULT_REF = "main"

# name -> (git blob of the archived copy, strict?)
# strict means the file's content is part of the contract and a change must
# fail the run. Only the hook bus qualifies: `plugins/pcmem_router.py` imports
# it and calls seven of its functions.
PINNED: dict[str, tuple[str, bool]] = {
    "plugins/hooks.py": ("655fa3773fe39f0d9bfceeeceebd1db863832dc1", True),
    "agent_loop.py": ("a744f0d2624e5f244927a2a03d66f41b56f94f85", False),
    "ga.py": ("15fdb71bf9c7f45fd0be6236dd9a534072dce107", False),
    "agentmain.py": ("3eb288c84e455d067327cd24bbb4e60228c9c837", False),
    "llmcore.py": ("611e83556fb35a9f07ce5d13b092dacdebc35539", False),
    "reflect/scheduler.py": ("a3ca622d3047a06f0d09f9493a641c63e77d4d34", False),
}

# Files the acceptance run imports or reads. The rest of the repository (assets,
# frontends, memory seeds, the agent UI) is never downloaded.
FILES = tuple(PINNED)


def data_root() -> Path:
    """The one directory this tool may write under.

    The handoff machine used a fixed local root. Any absolute root works now;
    set `PCMEM_DATA_DIR` to keep large downloads off the system drive. Without
    it, the root is `pcmem-data` in the home directory.
    """
    configured = os.environ.get("PCMEM_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "pcmem-data").resolve()


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _as_blob(data: bytes, expected: str) -> bytes:
    """The bytes as archived, tolerating a trailing-newline difference."""
    candidates = [data, data.rstrip(b"\n"), data.rstrip(b"\n") + b"\n"]
    return next((value for value in candidates if blob(value) == expected), data)


def _download(name: str, ref: str) -> bytes:
    url = f"https://raw.githubusercontent.com/{OWNER_REPO}/{ref}/{name}"
    try:
        with urlopen(url, timeout=60) as response:
            return response.read()
    except OSError as exc:
        raise ValueError(
            f"Could not fetch {name} from ref {ref!r}: {exc}. "
            "Pass --ref <branch-or-tag> or --source-dir <existing GenericAgent checkout>."
        ) from exc


def prepare(directory: Path, *, ref: str | None = None, source_dir: Path | None = None) -> dict:
    """Place the six files in ``directory`` and report what each one matched."""
    directory = directory.expanduser().resolve()
    root = data_root()
    if not directory.is_relative_to(root):
        raise ValueError(f"Keep fixtures under {root}; set PCMEM_DATA_DIR to change it")
    resolved_ref = ref or os.environ.get("PCMEM_GENERICAGENT_REF") or DEFAULT_REF
    if source_dir is not None and not Path(source_dir).is_dir():
        raise ValueError(f"--source-dir is not a directory: {source_dir}")

    manifest: dict[str, dict[str, object]] = {}
    drifted: list[str] = []
    for name in FILES:
        expected, strict = PINNED[name]
        target = directory / name
        if source_dir is not None:
            origin = Path(source_dir) / name
            if not origin.is_file():
                raise ValueError(f"{origin} is missing from the source checkout")
            data = origin.read_bytes()
        elif target.exists():
            data = target.read_bytes()
        else:
            data = _download(name, resolved_ref)
        data = _as_blob(data, expected)
        actual = blob(data)
        if actual != expected:
            drifted.append(name)
            if strict:
                raise ValueError(
                    f"Upstream {name} no longer matches its pinned blob.\n"
                    f"  expected {expected}\n  actual   {actual}\n"
                    "The hook bus this project imports changed. Read the diff, "
                    "adjust plugins/pcmem_router.py if the API moved, then update "
                    "PINNED in this script and the contract test together."
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = {
            "pinned_blob": expected,
            "actual_blob": actual,
            "sha256": hashlib.sha256(data).hexdigest(),
            "strict": strict,
            "drifted": actual != expected,
        }

    return {
        "repository": REPOSITORY,
        "ref": resolved_ref,
        "historical_commit": HISTORICAL_COMMIT,
        "source": str(source_dir) if source_dir is not None else "download",
        "files": manifest,
        "drifted": sorted(drifted),
        "note": (
            "hooks.py is pinned by blob because the recorded commit no longer "
            "resolves. A strict mismatch fails the run; the other five are "
            "reported as drifted and still written."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument(
        "--ref", default=None, help=f"branch or tag to fetch (default {DEFAULT_REF})"
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="copy from an existing GenericAgent checkout instead of downloading",
    )
    args = parser.parse_args()
    print(json.dumps(prepare(args.directory, ref=args.ref, source_dir=args.source_dir), indent=2))
