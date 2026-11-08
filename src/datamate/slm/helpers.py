"""Namespace exposed to model-generated code as ``h``.

Parsing (messy VND, quantities, dates), rulebook periods (half-open ``(start, end_exclusive)``),
lunar calendar lookups and rounding live here so the model writes short pandas, not parsers.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ..temporal.periods import (  # noqa: F401
    before_tet, day, days_between, last_month, last_month_same_days, last_n_days, last_week,
    load_calendar, lunar_to_solar, month, month_no_year, previous_period, quarter, quarter_no_year,
    resolve_year, shift_year, tet_window, this_month, this_week, up_to, whole_year, year_to_date,
)
from .parsing import dt, num, parse_date, parse_qty, parse_vnd, pct_change, qty, round2, round_money  # noqa: F401


def in_period(dates: pd.Series, period: tuple[date, date]) -> pd.Series:
    """Boolean mask: start <= d < end_exclusive. Accepts h.dt output, dates, strings; NaT → False."""
    start, end = period
    d = pd.to_datetime(dates, errors="coerce")
    return ((d >= pd.Timestamp(start)) & (d < pd.Timestamp(end))).fillna(False).astype(bool)


def ffill_group(df: pd.DataFrame, key: str, cols: list[str] | None = None) -> pd.DataFrame:
    """Fill blank continuation cells of grouped report rows (one header row, many item rows)."""
    out = df.copy()
    blank = out[key].map(lambda v: v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "")
    group = (~blank).cumsum()
    for col in cols or [key]:
        filled = out[col].where(~out[col].map(lambda v: v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ""))
        out[col] = filled.groupby(group).ffill()
    return out


def dedup_order_lines(df: pd.DataFrame, order_col: str, cols: list[str] | None = None) -> pd.DataFrame:
    """Drop rows duplicated across monthly/sheet exports (ignores the ``_source`` column)."""
    subset = cols or [c for c in df.columns if c != "_source"]
    return df.drop_duplicates(subset=subset).reset_index(drop=True) if order_col in df.columns else df


def to_base_units(quantity: pd.Series, factor: pd.Series | float) -> pd.Series:
    """Multiply parsed quantities by a pack/conversion factor (e.g. thùng → chai)."""
    return num(quantity) * (num(factor) if isinstance(factor, pd.Series) else float(factor))


def top_n(totals: pd.Series, n: int, ascending: bool = False) -> list[Any]:
    """Rank keys by value; ties broken by key ascending (rulebook)."""
    frame = totals.rename("v").reset_index()
    frame.columns = ["k", "v"]
    frame = frame.sort_values(["v", "k"], ascending=[ascending, True], kind="mergesort")
    return frame["k"].head(n).tolist()
