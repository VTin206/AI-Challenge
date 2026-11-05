from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def normalize_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, tuple):
        return [normalize_scalar(item) for item in value]
    if isinstance(value, list):
        return [normalize_scalar(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_scalar(item) for key, item in value.items()}
    return value


def validate_result(rows: list[dict[str, Any]]) -> tuple[Any | None, str | None]:
    if not rows:
        return None, "Query returned no rows"
    if len(rows) == 1 and list(rows[0].keys()) == ["value"]:
        value = rows[0]["value"]
        if isinstance(value, str):
            try:
                value = Decimal(value)
            except InvalidOperation:
                pass
        return normalize_scalar(value), None
    if all(set(row.keys()) == {"label", "value"} for row in rows):
        values = []
        for row in rows:
            value = row["value"]
            if isinstance(value, str):
                try:
                    value = Decimal(value)
                except InvalidOperation:
                    pass
            values.append({"label": row["label"], "value": value})
        return values, None
    return None, "Unexpected result shape for this baseline question type"

