"""Explicit period builders following the DataMate rulebook §2 (default rules).

Every function returns a half-open ``(start, end_exclusive)`` pair of ``date`` objects so callers
filter with ``start <= d < end``. ``today`` is always the question's as_of_date.
"""
from __future__ import annotations

import calendar as _calendar
import csv
from datetime import date, timedelta
from pathlib import Path

Period = tuple[date, date]
_ONE = timedelta(days=1)


def day(d: date) -> Period:
    return d, d + _ONE


def days_between(start: date, end_inclusive: date) -> Period:
    """'Từ X đến Y' includes both ends."""
    return start, end_inclusive + _ONE


def up_to(d: date) -> Period:
    """'Đến hết ngày X' for balances (debt, stock): from the beginning of data to end of X."""
    return date(1900, 1, 1), d + _ONE


def last_n_days(today: date, n: int) -> Period:
    """N consecutive days ending today (today included)."""
    return today - timedelta(days=n - 1), today + _ONE


def this_week(today: date) -> Period:
    """Monday of the week containing today → end of today."""
    return today - timedelta(days=today.weekday()), today + _ONE


def last_week(today: date) -> Period:
    """Whole previous Monday–Sunday week."""
    start = today - timedelta(days=today.weekday() + 7)
    return start, start + timedelta(days=7)


def month(year: int, month_: int) -> Period:
    """Whole calendar month M/Y."""
    start = date(year, month_, 1)
    return start, date(year + (month_ == 12), month_ % 12 + 1, 1)


def this_month(today: date) -> Period:
    """'Tháng này' = day 1 → end of today."""
    return date(today.year, today.month, 1), today + _ONE


def last_month(today: date) -> Period:
    """'Tháng trước' as a whole month."""
    prev = date(today.year, today.month, 1) - _ONE
    return month(prev.year, prev.month)


def last_month_same_days(today: date) -> Period:
    """Comparison base for 'tháng này so với tháng trước': day 1 → same day number of the previous
    month (clamped to that month's last day)."""
    prev = date(today.year, today.month, 1) - _ONE
    end_day = min(today.day, _calendar.monthrange(prev.year, prev.month)[1])
    return date(prev.year, prev.month, 1), date(prev.year, prev.month, end_day) + _ONE


def resolve_year(today: date, month_: int) -> int:
    """'Tháng M' / 'quý Q' without a year: this year unless that is after today, then last year."""
    return today.year if date(today.year, month_, 1) <= today else today.year - 1


def month_no_year(today: date, month_: int) -> Period:
    return month(resolve_year(today, month_), month_)


def quarter(year: int, q: int) -> Period:
    start = date(year, 3 * (q - 1) + 1, 1)
    end_month = 3 * q
    return start, date(year + (end_month == 12), end_month % 12 + 1, 1)


def quarter_no_year(today: date, q: int) -> Period:
    return quarter(resolve_year(today, 3 * (q - 1) + 1), q)


def year_to_date(today: date) -> Period:
    return date(today.year, 1, 1), today + _ONE


def whole_year(year: int) -> Period:
    return date(year, 1, 1), date(year + 1, 1, 1)


def shift_year(period: Period, years: int = -1) -> Period:
    """Same period last year (Feb 29 clamps to Feb 28)."""
    def move(d: date) -> date:
        y = d.year + years
        return date(y, d.month, min(d.day, _calendar.monthrange(y, d.month)[1]))
    return move(period[0]), move(period[1])


def previous_period(period: Period) -> Period:
    """Immediately preceding period of the same length (generic 'kỳ trước')."""
    length = period[1] - period[0]
    return period[0] - length, period[0]


def load_calendar(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def lunar_to_solar(cal: list[dict[str, str]], lunar_year: int, lunar_month: int, lunar_day: int, leap: bool = False) -> date | None:
    """Look up the solar date for a lunar date in calendar.csv (no conversion maths)."""
    for row in cal:
        if (int(row["lunar_year"]) == lunar_year and int(row["lunar_month"]) == lunar_month
                and int(row["lunar_day"]) == lunar_day and (row["lunar_leap"].strip().lower() == "true") == leap):
            return date.fromisoformat(row["date"])
    return None


def tet_window(cal: list[dict[str, str]], lunar_year: int) -> Period | None:
    """'Tết năm Y': solar date of 23 tháng Chạp (lunar year Y−1) → end of mùng 10 tháng Giêng (Y)."""
    start = lunar_to_solar(cal, lunar_year - 1, 12, 23)
    end = lunar_to_solar(cal, lunar_year, 1, 10)
    if start is None or end is None:
        return None
    return start, end + _ONE


def before_tet(cal: list[dict[str, str]], lunar_year: int) -> Period | None:
    """'So với trước Tết': the same number of days immediately before 23 tháng Chạp."""
    window = tet_window(cal, lunar_year)
    if window is None:
        return None
    length = window[1] - window[0]
    return window[0] - length, window[0]
