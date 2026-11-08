"""Turn a model's ``<final>`` payload into a valid submission answer and a vote key."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Any

from ..evaluation.metrics import normalize_text
from .parsing import _plain_number, round2, round_money

TYPES = {"number", "percent", "string", "date", "boolean", "list", "table", "unanswerable"}
_TRUE = {"true", "yes", "co", "có", "dung", "đúng", "1"}
_FALSE = {"false", "no", "khong", "không", "sai", "0"}


class InvalidAnswer(ValueError):
    pass


def _item(raw: Any) -> Any:
    return raw.item() if hasattr(raw, "item") and not isinstance(raw, (str, bytes)) else raw


def _number(raw: Any, unit: str | None) -> int | float:
    raw = _item(raw)
    if isinstance(raw, bool):
        raise InvalidAnswer("boolean is not a number")
    if isinstance(raw, str):
        text = raw.strip().rstrip("%").strip()
        try:
            value = float(text)
        except ValueError:
            value = _plain_number(text)
        if value is None:
            raise InvalidAnswer(f"not a number: {raw!r}")
        raw = value
    if not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise InvalidAnswer(f"not a number: {raw!r}")
    if unit == "vnd":
        return round_money(raw)
    value = round2(raw)
    return int(value) if float(value).is_integer() else value


def _scalar(raw: Any, unit: str | None) -> Any:
    raw = _item(raw)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return _number(raw, unit)
    if isinstance(raw, (date, datetime)):
        return raw.strftime("%Y-%m-%d")
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        raise InvalidAnswer("null element")
    return str(raw).strip()


def _date(raw: Any) -> str:
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    text = str(raw).strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?(?:[ T].*)?", text)
    try:
        if m:
            if m[3] is None:
                return f"{int(m[1]):04d}-{int(m[2]):02d}"
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
    except ValueError as exc:
        raise InvalidAnswer(f"bad date {text!r}") from exc
    raise InvalidAnswer(f"not a date: {text!r}")


def _boolean(raw: Any) -> bool:
    raw = _item(raw)
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise InvalidAnswer(f"not a boolean: {raw!r}")


def _table(raw: Any, unit: str | None) -> dict:
    if hasattr(raw, "columns") and hasattr(raw, "values"):
        raw = {"columns": [str(c) for c in raw.columns], "rows": raw.values.tolist()}
    if isinstance(raw, list) and raw and all(isinstance(r, dict) for r in raw):
        cols = list(raw[0].keys())
        raw = {"columns": cols, "rows": [[r.get(c) for c in cols] for r in raw]}
    if not isinstance(raw, dict) or not isinstance(raw.get("columns"), list) or not isinstance(raw.get("rows"), list):
        raise InvalidAnswer("table needs {columns, rows}")
    cols = [str(c) for c in raw["columns"]]
    rows = []
    for row in raw["rows"]:
        if not isinstance(row, (list, tuple)) or len(row) != len(cols):
            raise InvalidAnswer("ragged table row")
        rows.append([_scalar(v, unit) for v in row])
    return {"columns": cols, "rows": rows}


def coerce(answer_type: str, raw: Any, unit: str | None = None, reason: str | None = None) -> dict:
    """Return ``{"type", "answer"}`` or ``{"type": "unanswerable", "reason"}``; raise InvalidAnswer."""
    t = (answer_type or "").strip().lower()
    if t not in TYPES:
        raise InvalidAnswer(f"unknown type {answer_type!r}")
    if t == "unanswerable":
        return {"type": t, "reason": (reason or "Dữ liệu của cửa hàng không có thông tin để trả lời.").strip()}
    if raw is None:
        raise InvalidAnswer("missing answer")
    if t == "number":
        value: Any = _number(raw, unit)
    elif t == "percent":
        value = _number(raw, "other")
    elif t == "string":
        if isinstance(raw, (list, dict, tuple)):
            raise InvalidAnswer("string answer is a container")
        value = str(_scalar(raw, unit))
        if not value:
            raise InvalidAnswer("empty string")
    elif t == "date":
        value = _date(raw)
    elif t == "boolean":
        value = _boolean(raw)
    elif t == "list":
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        if not isinstance(raw, (list, tuple)):
            raise InvalidAnswer("list answer is not a list")
        value = [_scalar(v, unit) for v in raw]
    else:
        value = _table(raw, unit)
    return {"type": t, "answer": value}


def _canon(x: Any) -> Any:
    if isinstance(x, str):
        return normalize_text(x)
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def vote_key(ans: dict) -> str:
    """Canonical form so equivalent answers fall into one bucket."""
    t, v = ans["type"], ans.get("answer")
    if t == "unanswerable":
        return t
    if t == "list":
        v = [_canon(x) for x in v]
    elif t == "table":
        v = {"columns": sorted(normalize_text(c) for c in v["columns"]),
             "rows": sorted(json.dumps([_canon(c) for c in r], ensure_ascii=False) for r in v["rows"])}
    else:
        v = _canon(v)
    return t + ":" + json.dumps(v, ensure_ascii=False, sort_keys=True)
