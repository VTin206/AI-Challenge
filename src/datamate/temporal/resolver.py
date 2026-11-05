from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from ..models import DateRange
from ..util import fold_text


def _month_shift(value: date, months: int) -> date:
    index = value.year * 12 + (value.month - 1) + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _quarter_start(value: date) -> date:
    return date(value.year, ((value.month - 1) // 3) * 3 + 1, 1)


def lunar_expression_present(question: str) -> bool:
    q = fold_text(question)
    return any(token in q for token in ("am lich", "thang am", "nam am", "tet am"))


def resolve_date_range(question: str, as_of: date) -> DateRange | None:
    q = fold_text(question)
    today = as_of
    if "hom kia" in q:
        day = today - timedelta(days=2)
        return DateRange(day, day + timedelta(days=1), "two days ago")
    if "hom qua" in q:
        day = today - timedelta(days=1)
        return DateRange(day, day + timedelta(days=1), "yesterday")
    if "hom nay" in q or "ngay nay" in q:
        return DateRange(today, today + timedelta(days=1), "today")
    if any(token in q for token in ("tuan truoc", "tuan roi", "tuan qua", "last week")):
        start_this = today - timedelta(days=today.weekday())
        start = start_this - timedelta(days=7)
        return DateRange(start, start + timedelta(days=7), "previous week")
    if any(token in q for token in ("tuan nay", "this week")):
        start = today - timedelta(days=today.weekday())
        return DateRange(start, start + timedelta(days=7), "this week")
    if "thang truoc" in q or "thang roi" in q or "last month" in q:
        start = _month_start(_month_shift(today, -1))
        end = _month_start(today)
        return DateRange(start, end, "previous month")
    if "thang nay" in q or "this month" in q:
        start = _month_start(today)
        end = _month_start(_month_shift(today, 1))
        return DateRange(start, end, "this month")
    if "quy truoc" in q or "quy roi" in q or "last quarter" in q:
        start = _quarter_start(_month_shift(today, -3))
        return DateRange(start, _quarter_start(today), "previous quarter")
    if "quy nay" in q or "this quarter" in q:
        start = _quarter_start(today)
        end = _month_shift(start, 3)
        return DateRange(start, end, "this quarter")
    if any(token in q for token in ("cung ky nam ngoai", "cung ky nam truoc", "same period last year")):
        comparable_day = date(today.year - 1, today.month, min(today.day, calendar.monthrange(today.year - 1, today.month)[1]))
        if "thang nay" in q or "this month" in q:
            start = date(today.year - 1, today.month, 1)
        elif "quy nay" in q or "this quarter" in q:
            start = date(today.year - 1, ((today.month - 1) // 3) * 3 + 1, 1)
        else:
            start = date(today.year - 1, 1, 1)
        return DateRange(start, comparable_day + timedelta(days=1), "same period last year")
    if any(token in q for token in ("nam truoc", "nam ngoai", "last year")):
        start = date(today.year - 1, 1, 1)
        return DateRange(start, date(today.year, 1, 1), "previous year")
    if any(token in q for token in ("nam nay", "this year")):
        start = date(today.year, 1, 1)
        return DateRange(start, date(today.year + 1, 1, 1), "this year")
    range_match = re.search(r"(?:tu|from)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})\s+(?:den|toi|to|through)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})", q)
    if range_match:
        def parse(raw: str) -> date:
            if "-" in raw and len(raw.split("-")[0]) == 4:
                return date.fromisoformat(raw)
            parts = re.split(r"[/-]", raw)
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
        start, inclusive_end = map(parse, range_match.groups())
        if inclusive_end < start:
            return None
        return DateRange(start, inclusive_end + timedelta(days=1), "explicit range")
    return None

