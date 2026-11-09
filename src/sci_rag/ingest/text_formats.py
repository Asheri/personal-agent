"""Read code and structured text as data, without executing source content."""

from __future__ import annotations

import ast
import csv
import io
import json
import re
from pathlib import Path

import yaml

from sci_rag.ingest.errors import ParserError
from sci_rag.ingest.office import _table_block
from sci_rag.ingest.parsers import Block, ParsedDocument


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()

    def decoded(codec: str) -> str:
        return raw.decode(codec).replace("\r\n", "\n").replace("\r", "\n")

    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return decoded("utf-32"), "utf-32"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return decoded("utf-16"), "utf-16"
    if b"\x00" in raw:
        raise ParserError("binary_text", "text")
    try:
        return decoded("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return decoded("gb18030"), "gb18030"


def parse_code(path: Path) -> ParsedDocument:
    text, encoding = read_text(path)
    symbols: list[str] = []
    parse_status = "lexical"
    if path.suffix.lower() in {".py", ".pyi"}:
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    line = text.splitlines()[node.lineno - 1].strip()
                    symbols.append(f"{node.lineno}: {line}")
            parse_status = "python_ast"
        except (SyntaxError, ValueError):
            parse_status = "invalid_syntax_full_text_retained"
    else:
        for number, line in enumerate(text.splitlines(), 1):
            if re.match(
                r"\s*(?:(?:export|public|private|static|async)\s+)*(?:class|interface|function|def|fn|func|struct|enum)\b",
                line,
            ):
                symbols.append(f"{number}: {line.strip()}")
    # Full source is an evidence block, so bodies are indexed as well as signatures.
    return ParsedDocument(
        title=path.stem,
        blocks=[Block(kind="text", text=text)],
        metadata={
            "parser": "code",
            "encoding": encoding,
            "language": path.suffix.lower()[1:],
            "symbols": symbols,
            "head": text[:2000],
            "symbol_parser": parse_status,
        },
    )


def parse_data(path: Path) -> ParsedDocument:
    text, encoding = read_text(path)
    suffix = path.suffix.lower()
    parser = suffix[1:] if suffix != ".yml" else "yaml"
    metadata = {"parser": parser, "encoding": encoding}
    if suffix in {".csv", ".tsv"}:
        rows = list(
            csv.reader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ",", strict=True)
        )
        block = _table_block(rows)
        return ParsedDocument(
            title=path.stem,
            blocks=[block] if block else [],
            metadata={**metadata, "rows": len(rows)},
        )
    try:
        if suffix == ".json":
            json.loads(text)
        elif suffix == ".jsonl":
            for line in text.splitlines():
                if line.strip():
                    json.loads(line)
        else:
            yaml.safe_load(text)
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        raise ParserError("invalid_structured_text", parser) from exc
    return ParsedDocument(
        title=path.stem, blocks=[Block(kind="text", text=text)], metadata=metadata
    )
