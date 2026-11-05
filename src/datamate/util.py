from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def fold_text(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.casefold()).strip()


def safe_identifier(value: str, fallback: str = "column") -> str:
    folded = fold_text(value)
    name = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    if not name:
        name = fallback
    if name[0].isdigit():
        name = f"_{name}"
    return name


def unique_identifiers(values: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for index, value in enumerate(values, 1):
        base = safe_identifier(value, f"column_{index}")
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count + 1}")
    return result


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def json_dumps(value: Any) -> str:
    """Serialize Decimal as an exact JSON number rather than a quoted string/float."""
    if value is None or isinstance(value, (str, bool, int)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal is not valid JSON")
        return format(value, "f")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("Non-finite float is not valid JSON")
        return json.dumps(value, allow_nan=False)
    if isinstance(value, (date, datetime)):
        return json.dumps(value.isoformat(), ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(json_dumps(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(str(key), ensure_ascii=False) + ":" + json_dumps(item)
            for key, item in value.items()
        ) + "}"
    return json.dumps(str(value), ensure_ascii=False)

