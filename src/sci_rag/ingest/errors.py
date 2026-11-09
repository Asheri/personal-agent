"""Content-free parser failures and shared offline-source checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ParserError(ValueError):
    def __init__(self, code: str, parser: str) -> None:
        super().__init__(code)
        self.code, self.parser = code, parser


class PlaceholderFileError(OSError):
    """The source needs a cloud recall before it can be read."""


def check_placeholder(info: Any) -> None:
    if getattr(info, "st_file_attributes", 0) & (0x1000 | 0x40000 | 0x400000):
        raise PlaceholderFileError("source_placeholder")


def check_source(path: Path) -> None:
    check_placeholder(path.stat())
