#!/usr/bin/env python
"""Refuse to commit a credential.

A provider key is the one file content that cannot be revoked by editing the
file: once it is in a commit, the clone, the fork, and the pull request all
carry it. CI installs a key for the test run, so a `.env` copied by accident
would look completely ordinary.

This check reads the files it is given (pre-commit passes staged paths, CI
passes the tree) and exits non-zero on a pattern that only a real credential
produces. Placeholders and test fixtures are allowed through by their shape,
not by an ignore list, so nothing rots: a fake key is one that is short or
obviously a word, and a real key is long and random.

    uv run python scripts/check_no_secrets.py            # whole tree
    uv run python scripts/check_no_secrets.py --staged   # pre-commit
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

#: The `.env` files this project tells people to create. They are ignored by
#: git, and finding one here means the ignore rule was bypassed.
SECRET_FILES = (".env",)

#: Shapes that only a live credential has. Length is the discriminator: the
#: test fixture `sk-topsecret1234567890` is 20 characters of words, a real
#: SiliconFlow key is 48 or more of noise.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("bilibili session", re.compile(r"\bSESSDATA=[A-Za-z0-9%]{20,}")),
    ("huggingface token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
)

#: Files that legitimately contain the word "password" and other decoys.
EXEMPT_SUFFIXES = (".lock", ".png", ".jpg", ".pdf", ".docx", ".pptx", ".xlsx")
EXEMPT_PARTS = {".git", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}

#: A line may opt out explicitly, which is a decision a reviewer can see.
ALLOW = re.compile(r"#\s*allow-secret\b")


def _tracked(staged: bool) -> list[Path]:
    if staged:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [Path(line) for line in result.stdout.splitlines() if line.strip()]
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def findings(paths: list[Path]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        if any(part in EXEMPT_PARTS for part in path.parts):
            continue
        if path.name in SECRET_FILES or path.suffix in EXEMPT_SUFFIXES:
            if path.name in SECRET_FILES:
                problems.append(f"{path}: a real .env must never be committed")
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if ALLOW.search(line):
                continue
            for label, pattern in PATTERNS:
                match = pattern.search(line)
                if match is not None:
                    problems.append(
                        f"{path}:{number}: {label} ({match.group(0)[:12]}...) "
                        "moved to a keychain entry or an uncommitted .env"
                    )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="only staged files")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)

    paths = args.paths or _tracked(args.staged)
    problems = findings(paths)
    if problems:
        print("Refusing: a credential-shaped string is tracked.", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"no credential-shaped strings in {len(paths)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
