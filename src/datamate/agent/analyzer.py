from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import DateRange
from ..temporal import lunar_expression_present, resolve_date_range
from ..util import fold_text


@dataclass(frozen=True)
class Intent:
    kind: str
    measure: str | None
    dimension: str | None
    date_range: DateRange | None
    top_k: int = 1
    question_folded: str = ""
    unsupported_temporal: bool = False
    entity_only: bool = False


def analyze_question(question: str, as_of_date) -> Intent:
    q = fold_text(question)
    unsupported_temporal = lunar_expression_present(question)
    date_range = resolve_date_range(question, as_of_date)
    top_match = re.search(r"\btop\s+(\d+)\b", q)
    top_k = int(top_match.group(1)) if top_match else 1
    top_markers = ("nhat", "nhieu nhat", "cao nhat", "ban chay", "top ", "it nhat", "thap nhat")
    is_top = any(marker in q for marker in top_markers)
    count_markers = ("dem so", "so don", "don hang", "count")
    average_markers = ("trung binh", "binh quan", "average", "avg")
    sum_markers = ("tong", "doanh thu", "ban duoc bao nhieu tien", "tien ban", "total", "sum")
    revenue_terms = ("doanh thu", "tien ban", "ban duoc bao nhieu tien", "revenue")
    quantity_terms = ("so luong", "quantity", "qty", "san luong")
    measure = None
    if any(marker in q for marker in average_markers):
        if any(token in q for token in quantity_terms):
            measure = "average_quantity"
        else:
            return Intent("unknown", None, None, date_range, top_k, q, unsupported_temporal)
    elif any(marker in q for marker in sum_markers):
        if any(token in q for token in revenue_terms):
            measure = "revenue"
        elif any(token in q for token in quantity_terms):
            measure = "quantity"
        else:
            return Intent("unknown", None, None, date_range, top_k, q, unsupported_temporal)
    elif is_top:
        if any(token in q for token in revenue_terms):
            measure = "revenue"
        elif any(token in q for token in quantity_terms) or any(token in q for token in ("ban nhieu nhat", "ban chay", "san pham", "mat hang", "sp ")):
            measure = "quantity"
        else:
            return Intent("unknown", None, None, date_range, top_k, q, unsupported_temporal)
    elif any(marker in q for marker in count_markers):
        measure = "count"
    else:
        return Intent("unknown", None, None, date_range, top_k, q, unsupported_temporal)
    if any(token in q for token in ("san pham", "mat hang", "hang nao", "sp ", "sp nao")) or (is_top and any(token in q for token in ("ban nhieu nhat", "ban chay"))):
        dimension = "product"
    elif any(token in q for token in ("nhan vien", "khach hang", "ai ", "ai co")):
        dimension = "person"
    else:
        dimension = None
    kind = "top" if is_top else "aggregate"
    entity_only = kind == "top" and top_k == 1 and any(token in q for token in ("la gi", "la mat hang nao", "san pham nao", "sp nao"))
    return Intent(kind, measure, dimension, date_range, top_k, q, unsupported_temporal, entity_only)

