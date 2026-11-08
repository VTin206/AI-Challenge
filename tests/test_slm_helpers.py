from datetime import date

import pandas as pd
import pytest

from datamate.slm import helpers as h


@pytest.mark.parametrize("cell,expected", [
    ("55,000", 55000), ("45,000.0000", 45000), ("90.000đ", 90000), ("19tr990", 19990000),
    ("120k", 120000), ("20,1tr", 20100000), (1500000, 1500000), ("", None), (None, None),
])
def test_parse_vnd(cell, expected):
    assert h.parse_vnd(cell) == expected


def test_parse_qty_and_dates():
    assert h.parse_qty("3 chai") == (3.0, "chai")
    assert h.parse_date(45839) == date(2025, 7, 1)
    assert h.parse_date("1 thg 6 2025") == date(2025, 6, 1)
    assert h.parse_date("2025-06-01") == date(2025, 6, 1)
    assert h.parse_date("05/06", default_year=2025) == date(2025, 6, 5)


def test_rounding():
    assert h.round_money(1234.5) == 1235
    assert h.round2(12.345) == 12.35
    assert h.pct_change(110, 100) == 10.0


def test_periods_follow_rulebook():
    today = date(2026, 3, 4)
    assert h.this_month(today) == (date(2026, 3, 1), date(2026, 3, 5))
    assert h.last_month_same_days(today) == (date(2026, 2, 1), date(2026, 2, 5))
    assert h.last_n_days(today, 7) == (date(2026, 2, 26), date(2026, 3, 5))
    assert h.this_week(today) == (date(2026, 3, 2), date(2026, 3, 5))
    assert h.last_week(today) == (date(2026, 2, 23), date(2026, 3, 2))
    assert h.month_no_year(today, 11) == (date(2025, 11, 1), date(2025, 12, 1))


def test_in_period_ffill_and_top_n():
    s = pd.Series([date(2026, 3, 1), None, date(2026, 3, 5)])
    assert h.in_period(s, (date(2026, 3, 1), date(2026, 3, 5))).tolist() == [True, False, False]
    raw = pd.Series(["2026-03-01", "x", "05/03/2026", 46082])
    assert h.in_period(h.dt(raw), h.this_month(date(2026, 3, 4))).tolist() == [True, False, False, True]
    df = pd.DataFrame({"don": ["HD1", "", "", "HD2", None], "sp": list("abcde")})
    assert h.ffill_group(df, "don")["don"].tolist() == ["HD1", "HD1", "HD1", "HD2", "HD2"]
    totals = pd.Series({"SP3": 5, "SP1": 5, "SP2": 9})
    assert h.top_n(totals, 2) == ["SP2", "SP1"]
