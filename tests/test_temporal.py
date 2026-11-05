from datetime import date

from datamate.temporal import resolve_date_range


def test_month_ranges_at_month_start_and_end():
    assert resolve_date_range("doanh thu thang nay", date(2026, 3, 1)).start == date(2026, 3, 1)
    assert resolve_date_range("thang nay", date(2026, 3, 31)).end_exclusive == date(2026, 4, 1)
    previous = resolve_date_range("thang truoc", date(2026, 3, 1))
    assert (previous.start, previous.end_exclusive) == (date(2026, 2, 1), date(2026, 3, 1))


def test_week_is_monday_first_and_crosses_year_boundary():
    current = resolve_date_range("tuan nay", date(2026, 1, 1))
    previous = resolve_date_range("tuan roi", date(2026, 1, 1))
    assert (current.start, current.end_exclusive) == (date(2025, 12, 29), date(2026, 1, 5))
    assert (previous.start, previous.end_exclusive) == (date(2025, 12, 22), date(2025, 12, 29))


def test_quarter_and_year_ranges():
    quarter = resolve_date_range("quy truoc", date(2026, 1, 10))
    year = resolve_date_range("nam truoc", date(2026, 1, 10))
    assert (quarter.start, quarter.end_exclusive) == (date(2025, 10, 1), date(2026, 1, 1))
    assert (year.start, year.end_exclusive) == (date(2025, 1, 1), date(2026, 1, 1))


def test_leap_day_clamps_same_period_last_year():
    period = resolve_date_range("doanh thu cung ky nam ngoai", date(2024, 2, 29))
    assert (period.start, period.end_exclusive) == (date(2023, 1, 1), date(2023, 3, 1))


def test_explicit_range_in_vietnamese_is_inclusive_at_end():
    period = resolve_date_range("từ 28/02/2024 đến 01/03/2024", date(2026, 1, 1))
    assert (period.start, period.end_exclusive) == (date(2024, 2, 28), date(2024, 3, 2))

