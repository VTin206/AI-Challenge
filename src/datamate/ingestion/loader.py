from __future__ import annotations

import csv
import io
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from ..models import DataTable
from ..util import safe_identifier, unique_identifiers

SUPPORTED = {".csv", ".tsv", ".xlsx", ".xlsm", ".sqlite", ".db"}
_INTEGER = re.compile(r"^[+-]?\d+$")
_DECIMAL = re.compile(r"^[+-]?\d+\.\d+$")


@dataclass
class DataPackage:
    root: Path
    tables: list[DataTable]
    business_readme: str = ""
    shared_rulebook: str = ""
    calendar_path: Path | None = None


def discover_files(root: str | Path) -> list[Path]:
    base = Path(root).resolve()
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"Data package directory does not exist: {base}")
    found = []
    for path in base.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part.startswith(".") or part in {"outputs", "models", "__pycache__"} for part in path.relative_to(base).parts):
            continue
        if path.suffix.lower() in SUPPORTED:
            found.append(path)
    return sorted(found, key=lambda item: str(item).casefold())


def _decode_csv(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "cp1252"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1"), "latin-1"


def _rows_from_csv(path: Path) -> tuple[list[list[Any]], str]:
    content, encoding = _decode_csv(path)
    sample = content[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    rows = list(csv.reader(io.StringIO(content), dialect))
    rows = [row for row in rows if any(str(value).strip() for value in row)]
    if not rows:
        return [], encoding
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return rows, encoding


def _convert_column(values: list[Any], original_name: str) -> tuple[list[Any], str | None]:
    """Convert only strict numeric forms; leave locale-ambiguous values untouched."""
    present = [value for value in values if value is not None and str(value).strip() != ""]
    if not present:
        return [None if value is None or str(value).strip() == "" else value for value in values], None
    if any(not isinstance(value, str) for value in present):
        # SQLite and Excel may already provide typed values. Preserve them.
        if all(isinstance(value, (int, bool)) for value in present):
            return values, "integer"
        if all(isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) for value in present):
            return values, "numeric"
        if all(isinstance(value, (date, datetime)) for value in present):
            return [value.isoformat() if isinstance(value, (date, datetime)) else value for value in values], "date"
        if all(isinstance(value, (bytes, bytearray)) for value in present):
            return values, "binary"
        return values, None
    strings = [str(value).strip() for value in present]
    if all(_INTEGER.fullmatch(value) for value in strings):
        return [None if value is None or str(value).strip() == "" else int(str(value).strip()) for value in values], "integer"
    if all(_INTEGER.fullmatch(value) or _DECIMAL.fullmatch(value) for value in strings):
        converted = []
        for value in values:
            if value is None or str(value).strip() == "":
                converted.append(None)
                continue
            raw = str(value).strip()
            converted.append(int(raw) if _INTEGER.fullmatch(raw) else Decimal(raw))
        return converted, "decimal"
    # Normalize ISO dates only; do not guess day/month ordering.
    name = safe_identifier(original_name)
    if any(part in name for part in ("date", "ngay", "time", "thoi_gian")):
        try:
            converted = []
            for value in values:
                if value is None or str(value).strip() == "":
                    converted.append(None)
                else:
                    raw = str(value).strip()
                    converted.append(date.fromisoformat(raw[:10]).isoformat())
            return converted, "date"
        except ValueError:
            pass
    return [None if value is None or str(value).strip() == "" else str(value) for value in values], None


def _table_from_rows(path: Path, source_label: str, raw_rows: list[list[Any]], notes: Iterable[str] = ()) -> DataTable | None:
    if not raw_rows:
        return None
    headers = [str(value).strip() if value is not None else "" for value in raw_rows[0]]
    headers = [value if value else f"column_{index + 1}" for index, value in enumerate(headers)]
    columns = unique_identifiers(headers)
    body = raw_rows[1:]
    width = len(columns)
    body = [list(row[:width]) + [None] * max(0, width - len(row)) for row in body]
    converted_columns = []
    type_notes = []
    for index, original in enumerate(headers):
        values, inferred = _convert_column([row[index] for row in body], original)
        converted_columns.append(values)
        if inferred:
            type_notes.append(f"{columns[index]} conservatively inferred as {inferred}")
    cooked_rows = tuple(tuple(converted_columns[col][row] for col in range(width)) for row in range(len(body)))
    base = safe_identifier(source_label, path.stem)
    return DataTable(
        name=base,
        source=str(path),
        original_name=source_label,
        original_columns=tuple(headers),
        columns=tuple(columns),
        rows=cooked_rows,
        notes=tuple(notes) + tuple(type_notes),
    )


def _read_csv(path: Path) -> list[DataTable]:
    rows, encoding = _rows_from_csv(path)
    table = _table_from_rows(path, path.stem, rows, (f"decoded as {encoding}",))
    return [table] if table else []


def _read_excel(path: Path) -> list[DataTable]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("Reading Excel requires openpyxl; install requirements.txt") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    tables = []
    try:
        for sheet in workbook.worksheets:
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            table = _table_from_rows(path, f"{path.stem}_{sheet.title}", rows)
            if table:
                tables.append(table)
    finally:
        workbook.close()
    return tables


def _sqlite_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _read_sqlite(path: Path) -> list[DataTable]:
    uri_path = path.resolve().as_posix().replace("?", "%3F").replace("#", "%23")
    source_db = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True, timeout=2)
    source_db.execute("PRAGMA query_only = ON")
    tables = []
    try:
        names = [row[0] for row in source_db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table_name in names:
            cursor = source_db.execute(f"SELECT * FROM {_sqlite_ident(table_name)}")
            headers = [col[0] for col in cursor.description or []]
            rows = [headers]
            rows.extend([list(row) for row in cursor.fetchmany(500001)])
            if len(rows) > 500001:
                raise ValueError(f"Source SQLite table exceeds 500,000 row package limit: {path.name}:{table_name}")
            table = _table_from_rows(path, f"{path.stem}_{table_name}", rows)
            if table:
                tables.append(table)
    finally:
        source_db.close()
    return tables


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1")


def load_package(root: str | Path) -> DataPackage:
    base = Path(root).resolve()
    files = discover_files(base)
    tables: list[DataTable] = []
    for path in files:
        ext = path.suffix.lower()
        if ext in {".csv", ".tsv"}:
            tables.extend(_read_csv(path))
        elif ext in {".xlsx", ".xlsm"}:
            tables.extend(_read_excel(path))
        elif ext in {".sqlite", ".db"}:
            tables.extend(_read_sqlite(path))
    # Disambiguate normalized names without changing source labels.
    seen: dict[str, int] = {}
    unique = []
    for table in tables:
        count = seen.get(table.name, 0)
        seen[table.name] = count + 1
        if count:
            table = DataTable(**{**table.__dict__, "name": f"{table.name}_{count + 1}"})
        unique.append(table)
    readme_path = base / "README.md"
    rulebook_path = base / "RULEBOOK.md"
    shared_rule = base.parent / "RULEBOOK.md"
    calendar = next((candidate for candidate in (base / "solar_lunar_calendar.csv", base / "calendar.csv", base / "solar_lunar_calendar.json") if candidate.exists()), None)
    return DataPackage(
        root=base,
        tables=unique,
        business_readme=_read_text(readme_path) if readme_path.exists() else "",
        shared_rulebook=_read_text(rulebook_path) if rulebook_path.exists() else (_read_text(shared_rule) if shared_rule.exists() else ""),
        calendar_path=calendar,
    )

