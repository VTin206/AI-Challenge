from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..models import ColumnProfile, DataTable, Relation, SchemaCatalog, TableProfile
from ..util import fold_text

_DATE = ("date", "ngay", "time", "thoi_gian", "created_at", "updated_at")
_QTY = ("qty", "quantity", "so_luong", "sl", "count", "san_luong")
_AMOUNT = ("amount", "revenue", "doanh_thu", "gia", "tien", "total", "thanh_tien", "cost", "profit", "loi_nhuan")
_PRODUCT = ("product", "item", "san_pham", "hang_hoa", "mat_hang", "sku")
_PERSON = ("customer", "khach_hang", "person", "employee", "nhan_vien", "ten")
_STATUS = ("status", "trang_thai", "state")
_KEY = ("id", "_id", "code", "ma_")


def _semantic_tags(name: str, values: list[Any]) -> list[str]:
    normalized = fold_text(name).replace(" ", "_")
    tags = []
    for tag, vocab in (("date", _DATE), ("quantity", _QTY), ("amount", _AMOUNT), ("product", _PRODUCT), ("person", _PERSON), ("status", _STATUS)):
        if any(word in normalized for word in vocab):
            tags.append(tag)
    if any(word in normalized for word in _KEY) or normalized == "id":
        tags.append("key")
    nonnull = [value for value in values if value is not None]
    if nonnull and all(isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) for value in nonnull):
        tags.append("numeric")
    return tags


def _infer_type(values: list[Any]) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return "unknown"
    if all(isinstance(value, bool) for value in present):
        return "boolean"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in present):
        return "integer"
    if all(isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) for value in present):
        return "numeric"
    if all(isinstance(value, str) for value in present):
        return "text"
    if all(isinstance(value, (bytes, bytearray)) for value in present):
        return "binary"
    return "mixed"


def _name_similarity(a: str, b: str) -> float:
    a_tokens = set(fold_text(a).replace("_", " ").split())
    b_tokens = set(fold_text(b).replace("_", " ").split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def profile_tables(tables: list[DataTable]) -> SchemaCatalog:
    table_profiles: list[TableProfile] = []
    value_sets: dict[tuple[str, str], set[Any]] = {}
    key_cells: list[tuple[str, ColumnProfile, set[Any]]] = []
    for table in tables:
        profiles = []
        for index, (column, original) in enumerate(zip(table.columns, table.original_columns)):
            values = [row[index] for row in table.rows]
            present = [value for value in values if value is not None]
            try:
                distinct = set(present)
            except TypeError:
                distinct = {repr(value) for value in present}
            samples = []
            for value in present:
                if value not in samples:
                    samples.append(value)
                if len(samples) >= 5:
                    break
            unique_nonnull = bool(present) and len(distinct) == len(present)
            tags = _semantic_tags(column, values)
            profile = ColumnProfile(
                name=column,
                original_name=original,
                inferred_type=_infer_type(values),
                nullable_count=len(values) - len(present),
                distinct_count=len(distinct),
                samples=samples,
                semantic_tags=tags,
                primary_key_candidate=unique_nonnull and ("key" in tags or len(tables) == 1),
            )
            profiles.append(profile)
            value_sets[(table.name, column)] = distinct
            if profile.primary_key_candidate:
                key_cells.append((table.name, profile, distinct))
        table_profiles.append(TableProfile(table.name, table.source, len(table.rows), profiles))

    relations = []
    for table in table_profiles:
        for column in table.columns:
            if column.primary_key_candidate or column.inferred_type in {"unknown", "binary"}:
                continue
            values = value_sets.get((table.name, column.name), set())
            if len(values) < 2:
                continue
            for target_table, target_column, target_values in key_cells:
                if target_table == table.name or not target_values:
                    continue
                compatible = [v for v in values if type(v) is type(next(iter(target_values)))]
                if not compatible:
                    continue
                overlap = len(set(compatible) & target_values) / len(set(compatible))
                name_score = _name_similarity(column.name, target_column.name)
                if overlap >= 0.8 and (name_score >= 0.15 or column.name.casefold().endswith("_id")):
                    confidence = min(0.99, 0.60 * overlap + 0.40 * max(name_score, 0.5 if column.name.endswith("_id") else 0))
                    card = "many-to-one candidate" if table.row_count > column.distinct_count else "one-to-one candidate"
                    relations.append(Relation(table.name, column.name, target_table, target_column.name, round(confidence, 3), card))
    return SchemaCatalog(table_profiles, relations)


def catalog_as_dict(catalog: SchemaCatalog) -> dict[str, Any]:
    return {
        "tables": [
            {
                "name": table.name,
                "source": table.source,
                "row_count": table.row_count,
                "columns": [
                    {
                        "name": col.name,
                        "original_name": col.original_name,
                        "type": col.inferred_type,
                        "nulls": col.nullable_count,
                        "distinct": col.distinct_count,
                        "samples": col.samples,
                        "semantic_tags": col.semantic_tags,
                        "primary_key_candidate": col.primary_key_candidate,
                    }
                    for col in table.columns
                ],
            }
            for table in catalog.tables
        ],
        "relationships": [relation.__dict__ for relation in catalog.relations],
    }


def render_catalog(catalog: SchemaCatalog) -> str:
    lines = []
    for table in catalog.tables:
        lines.append(f"TABLE {table.name} ({table.row_count} rows)")
        for col in table.columns:
            samples = ", ".join(repr(value) for value in col.samples[:3])
            lines.append(f"  - {col.name} [{col.inferred_type}] tags={','.join(col.semantic_tags) or '-'} samples=[{samples}]")
    if catalog.relations:
        lines.append("RELATION CANDIDATES (heuristic):")
        for rel in catalog.relations:
            lines.append(f"  - {rel.from_table}.{rel.from_column} -> {rel.to_table}.{rel.to_column} confidence={rel.confidence} ({rel.cardinality})")
    return "\n".join(lines)



def _short(value: Any, limit: int = 40) -> str:
    text = repr(value) if not isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "...'"


def render_frame_card(frames: dict[str, Any], max_chars: int = 12000, sample_rows: int = 3000) -> str:
    """Compact schema card over pandas frames for the SLM prompt.

    For each column: non-null share, distinct count, sample values, and how much of the
    column parses as money/number or date (computed on a row sample). Low-cardinality text
    columns list all their values. Detail is reduced until the card fits ``max_chars``.
    """
    from ..slm.parsing import parse_date, parse_vnd

    def column_line(frame, column: str, samples: int, list_values: bool) -> str:
        series = frame[column]
        present = series[series.map(lambda v: v is not None and not (isinstance(v, float) and v != v) and not (isinstance(v, str) and not v.strip()))]
        if present.empty:
            return f"  - {column!r}: empty"
        head = present.iloc[: sample_rows] if len(present) > sample_rows else present
        try:
            distinct = present.astype(str).nunique()
        except TypeError:
            distinct = -1
        parts = [f"  - {column!r}: {len(present) / len(series):.0%} filled, {distinct} distinct"]
        num_rate = head.map(lambda v: parse_vnd(v) is not None).mean()
        date_values = head.map(lambda v: parse_date(v, 2000))
        date_rate = date_values.notna().mean()
        if date_rate >= 0.8 and not all(isinstance(v, (int, float)) for v in head.iloc[:50]):
            real = [parse_date(v) for v in present]
            real = [d for d in real if d is not None]
            span = f" {min(real)}..{max(real)}" if real else " (no year in cells)"
            parts.append(f"date {date_rate:.0%}{span}")
        elif num_rate >= 0.8:
            parts.append(f"number {num_rate:.0%}")
        if list_values and 0 < distinct <= 15 and present.map(lambda v: isinstance(v, str)).all():
            values = sorted(present.astype(str).unique())
            parts.append("values=[" + ", ".join(repr(v) for v in values) + "]")
        elif samples:
            uniq = list(dict.fromkeys(present.iloc[:200].tolist()))[:samples]
            parts.append("e.g. " + ", ".join(_short(v) for v in uniq))
        return "; ".join(parts)

    def build(samples: int, list_values: bool) -> str:
        lines = []
        for name, frame in frames.items():
            sources = frame["_source"].nunique() if "_source" in frame.columns else 1
            lines.append(f"FRAME dfs[{name!r}] — {len(frame)} rows, {sources} source sheet/file(s)")
            for column in frame.columns:
                if column == "_source":
                    continue
                lines.append(column_line(frame, column, samples, list_values))
        return "\n".join(lines)

    for samples, list_values in ((3, True), (2, True), (1, True), (1, False), (0, False)):
        card = build(samples, list_values)
        if len(card) <= max_chars:
            return card
    return card[:max_chars] + "\n  ... (card truncated; inspect frames with code)"
