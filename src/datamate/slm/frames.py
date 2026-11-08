"""Load a business directory into pandas DataFrames for the SLM agent.

Reuses the readers in ``ingestion.loader`` (CSV decoding/sniffing, read-only SQLite) and adds
header-row detection for report-style sheets plus concatenation of same-schema sheets
(monthly tabs, split files) into one frame with a ``_source`` column.
Cells are kept raw: typing is done explicitly with ``datamate.slm.parsing`` helpers.
"""
from __future__ import annotations

import os
import pickle
import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from ..ingestion.loader import _read_text, _rows_from_csv, _sqlite_ident, discover_files

_HEADER_SCAN_ROWS = 30


def _cell_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def detect_header(rows: list[list[Any]]) -> int:
    """Index of the header row: first row whose non-empty cells are all strings and cover
    ≥60 % of the widest row among the first rows; falls back to the widest row."""
    scan = rows[:_HEADER_SCAN_ROWS]
    if not scan:
        return 0
    counts = [sum(not _cell_empty(v) for v in row) for row in scan]
    width = max(counts)
    for index, row in enumerate(scan):
        filled = [v for v in row if not _cell_empty(v)]
        if len(filled) >= max(2, 0.6 * width) and all(isinstance(v, str) for v in filled):
            return index
    return counts.index(width)


def _frame_from_rows(rows: list[list[Any]]) -> pd.DataFrame | None:
    rows = [list(r) for r in rows if any(not _cell_empty(v) for v in r)]
    if not rows:
        return None
    header_index = detect_header(rows)
    header = rows[header_index]
    width = max(len(r) for r in rows[header_index:])
    names, seen = [], {}
    for i in range(width):
        raw = header[i] if i < len(header) else None
        name = str(raw).strip() if not _cell_empty(raw) else f"col_{i + 1}"
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    body = [r[:width] + [None] * (width - len(r)) for r in rows[header_index + 1:]]
    frame = pd.DataFrame(body, columns=names, dtype=object)
    # Drop trailing all-empty columns that only came from ragged rows.
    keep = [c for c in frame.columns if not (c.startswith("col_") and frame[c].map(_cell_empty).all())]
    return frame[keep]


def _xlsx_sheets(path: Path) -> list[tuple[str, list[list[Any]]]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return [(sheet.title, [list(r) for r in sheet.iter_rows(values_only=True)]) for sheet in workbook.worksheets]
    finally:
        workbook.close()


def _sqlite_tables(path: Path) -> list[tuple[str, list[list[Any]]]]:
    uri = path.resolve().as_posix().replace("?", "%3F").replace("#", "%23")
    con = sqlite3.connect(f"file:{uri}?mode=ro", uri=True)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out = []
        for name in names:
            cur = con.execute(f"SELECT * FROM {_sqlite_ident(name)}")
            out.append((name, [[c[0] for c in cur.description]] + [list(r) for r in cur.fetchall()]))
        return out
    finally:
        con.close()


def _raw_frames(business_dir: Path) -> list[tuple[str, str, str, pd.DataFrame]]:
    """(label, file name, sheet/table name, frame) for every readable table.
    Label = file stem for single-table files, else the sheet/table name (prefixed by stem for xlsx)."""
    out = []
    for path in discover_files(business_dir):
        ext = path.suffix.lower()
        if ext in {".csv", ".tsv"}:
            rows, _ = _rows_from_csv(path)
            parts = [("", rows)]
        elif ext in {".xlsx", ".xlsm"}:
            parts = _xlsx_sheets(path)
        else:
            parts = _sqlite_tables(path)
        for sheet, rows in parts:
            frame = _frame_from_rows(rows)
            if frame is None or not len(frame.columns):
                continue
            if ext in {".sqlite", ".db"}:
                label = sheet
            elif len(parts) == 1 or not sheet:
                label = path.stem
            else:
                label = f"{path.stem}.{sheet}"
            out.append((label, path.name, sheet, frame))
    return out


def _group_name(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    prefix = os.path.commonprefix(labels)
    prefix = re.sub(r"[_\-. ]*[A-Za-z]?\d*$", "", prefix) if not prefix.endswith(tuple("_-. ")) else prefix
    prefix = prefix.rstrip("_-. ")
    return prefix if len(prefix) >= 3 else labels[0]


def load_frames(business_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Return {name: DataFrame}. Tables with identical headers (monthly sheets, split or per-year
    files) are concatenated; every frame gets ``_source`` = 'file' or 'file::sheet' for provenance
    (rulebook: a date without a year takes the year of its sheet)."""
    groups: dict[tuple[str, ...], list[tuple[str, pd.DataFrame]]] = {}
    for label, file_name, sheet, frame in _raw_frames(Path(business_dir)):
        frame = frame.copy()
        frame["_source"] = f"{file_name}::{sheet}" if sheet else file_name
        header = tuple(c for c in frame.columns if not c.startswith("col_"))
        groups.setdefault(header, []).append((label, frame))
    result: dict[str, pd.DataFrame] = {}
    for members in groups.values():
        base = _group_name([label for label, _ in members])
        name, suffix = base, 2
        while name in result:
            name, suffix = f"{base}_{suffix}", suffix + 1
        frames = [frame for _, frame in members]
        result[name] = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    return result


def read_readme(business_dir: str | Path) -> str:
    path = Path(business_dir) / "README.md"
    return _read_text(path) if path.exists() else ""


def cache_business(business_dir: str | Path, cache_root: str | Path) -> Path:
    """Load once and pickle to ``cache_root/<business>.pkl`` (object dtype survives pickling)."""
    business_dir = Path(business_dir)
    target = Path(cache_root) / f"{business_dir.name}.pkl"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        with tmp.open("wb") as stream:
            pickle.dump(load_frames(business_dir), stream, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(target)
    return target


def load_cached(path: str | Path) -> dict[str, pd.DataFrame]:
    with Path(path).open("rb") as stream:
        return pickle.load(stream)
