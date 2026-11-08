"""Tolerant parsers for messy Vietnamese spreadsheet cells.

Every function returns ``None`` (scalar) or ``NaN``/``NaT`` (Series) when a value cannot be
parsed, so generated code can measure coverage instead of silently dropping rows.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd

from ..util import fold_text

_EXCEL_EPOCH = date(1899, 12, 30)
_TR = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*(tr|trieu|m)\s*(\d{1,3})?$")
_K = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*(k|nghin|ngan)$")
_TY = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*(ty|ti)$")
_QTY = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(.*)$")
_THG = re.compile(r"^(\d{1,2})\s*thg\s*(\d{1,2})(?:\s*,?\s*(\d{4}))?$")
_DMY = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def _plain_number(text: str) -> float | None:
    """Parse digits with thousands separators in either VN (1.234,5) or EN (1,234.5) style."""
    text = text.replace(" ", "")
    if not re.fullmatch(r"-?[\d.,]+", text) or not re.search(r"\d", text):
        return None
    dots, commas = text.count("."), text.count(",")
    if dots and commas:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
        thousands = "," if decimal_sep == "." else "."
        text = text.replace(thousands, "").replace(decimal_sep, ".")
    elif dots or commas:
        sep = "." if dots else ","
        parts = text.lstrip("-").split(sep)
        # Several separators, or exactly three digits after one separator → thousands grouping.
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3 and parts[0] not in ("", "0")):
            text = text.replace(sep, "")
        else:
            text = text.replace(sep, ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_vnd(value: Any) -> float | None:
    """Money/number cell → float. Handles 270.000đ, 55,000, 45,000.0000, 19tr990, 1,5tr, 120k, 2 tỷ."""
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = fold_text(str(value)).replace("vnd", "").replace("dong", "").replace("đ", "").strip()
    text = re.sub(r"(?<=\d)\s*d$", "", text).strip()
    match = _TR.match(text)
    if match:
        base = _plain_number(match.group(1)) or 0.0
        tail = match.group(3)
        extra = int(tail) * 10 ** (3 - len(tail)) * 1000 if tail else 0
        return base * 1_000_000 + extra
    match = _K.match(text)
    if match:
        base = _plain_number(match.group(1))
        return None if base is None else base * 1000
    match = _TY.match(text)
    if match:
        base = _plain_number(match.group(1))
        return None if base is None else base * 1_000_000_000
    return _plain_number(text)


def parse_qty(value: Any) -> tuple[float | None, str | None]:
    """Quantity cell → (number, unit text or None). '2 cái' → (2.0, 'cái'); 3 → (3.0, None)."""
    if _is_missing(value):
        return None, None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return float(value), None
    match = _QTY.match(str(value))
    if not match:
        return None, None
    number = _plain_number(match.group(1))
    unit = match.group(2).strip() or None
    return number, unit


def parse_date(value: Any, default_year: int | None = None) -> date | None:
    """Date cell → date. Handles datetime, ISO, dd/mm/yyyy, dd/mm (default_year), Excel serials, '1 thg 7 2025'."""
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _EXCEL_EPOCH + timedelta(days=int(value)) if 20000 < value < 80000 else None
    text = fold_text(str(value))
    if re.fullmatch(r"\d{5}(\.0+)?", text):
        serial = int(float(text))
        return _EXCEL_EPOCH + timedelta(days=serial) if 20000 < serial < 80000 else None
    try:
        match = _ISO.match(text)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        match = _THG.match(text)
        if match:
            year = int(match.group(3)) if match.group(3) else default_year
            return date(year, int(match.group(2)), int(match.group(1))) if year else None
        match = _DMY.match(text.split(" ")[0])
        if match:
            day, month, year = match.groups()
            if year is None:
                if default_year is None:
                    return None
                year_num = default_year
            else:
                year_num = int(year) + (2000 if len(year) == 2 else 0)
            return date(year_num, int(month), int(day))
    except ValueError:
        return None
    return None


def num(series: pd.Series) -> pd.Series:
    """Vectorised parse_vnd for a column; unparseable cells become NaN."""
    return series.map(parse_vnd).astype("float64")


def qty(series: pd.Series) -> pd.Series:
    """Vectorised quantity number (unit text dropped); use parse_qty when the unit matters."""
    return series.map(lambda v: parse_qty(v)[0]).astype("float64")


def dt(series: pd.Series, default_year: int | pd.Series | None = None) -> pd.Series:
    """Vectorised parse_date → datetime64 Series (NaT when unparseable)."""
    if isinstance(default_year, pd.Series):
        values = [parse_date(v, y) for v, y in zip(series, default_year)]
    else:
        values = [parse_date(v, default_year) for v in series]
    return pd.to_datetime(pd.Series(values, index=series.index), errors="coerce")


def round_money(value: float) -> int:
    """Round VND to whole đồng, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(value: float) -> float:
    """Round to 2 decimals, half up."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def pct_change(new: float, old: float) -> float | None:
    """Percent change new vs old, rounded to 2 decimals; None when old is 0."""
    if not old:
        return None
    return round2((new - old) / old * 100)
