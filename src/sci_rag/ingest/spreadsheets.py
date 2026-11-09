"""Streaming XLSX tables with explicit row limits and no formula evaluation."""

from __future__ import annotations

from datetime import date, datetime, time
from itertools import zip_longest
from pathlib import Path

from sci_rag.ingest.errors import ParserError
from sci_rag.ingest.office import _table_block
from sci_rag.ingest.parsers import Block, ParsedDocument

ROW_LIMIT = 500


def parse_xlsx(path: Path) -> ParsedDocument:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ParserError("office_unavailable", "xlsx") from exc
    values = formulas = None
    try:
        values = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        formulas = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        blocks: list[Block] = []
        missing: list[str] = []
        sheets = []
        dropped = 0
        for name in values.sheetnames:
            sheet, raw = values[name], formulas[name]
            sheet.reset_dimensions()
            raw.reset_dimensions()
            rows: list[list[str]] = []
            count = 0
            for number, (cached, source) in enumerate(
                zip_longest(sheet.iter_rows(), raw.iter_rows(), fillvalue=()), 1
            ):
                count = number
                if number > ROW_LIMIT:
                    continue
                cells = []
                for v, f in zip_longest(cached, source):
                    value = v.value if v is not None else None
                    if f is not None and f.data_type == "f" and value is None:
                        missing.append(f"{name}!{f.coordinate}")
                    if isinstance(value, (date, datetime, time)):
                        value = value.isoformat()
                    cells.append("" if value is None else str(value))
                rows.append(cells)
            omitted = max(0, count - ROW_LIMIT)
            dropped += omitted
            sheets.append({"name": name, "rows": count, "rows_truncated": omitted})
            blocks.append(Block(kind="heading", text=name, level=1))
            table = _table_block(rows)
            if table:
                blocks.append(table)
        return ParsedDocument(
            title=values.properties.title or path.stem,
            blocks=blocks,
            metadata={
                "parser": "xlsx",
                **(
                    {"modified": values.properties.modified.isoformat()}
                    if values.properties.modified
                    else {}
                ),
                "sheets": sheets,
                "truncated": {"rows": dropped},
                "formulas_unevaluated": missing,
                "formula_values_source": "stored cache; freshness unverified",
            },
        )
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError("invalid_xlsx", "xlsx") from exc
    finally:
        if values is not None:
            values.close()
        if formulas is not None:
            formulas.close()
