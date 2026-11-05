from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import DataTable, DateRange, SchemaCatalog
from ..rules.engine import Rulebook
from ..util import quote_identifier
from .analyzer import Intent


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    explanation: str
    confidence: float


_ALIASES = {
    "date": {"date", "ngay", "time", "thoi_gian", "created_at", "order_date", "invoice_date"},
    "quantity": {"quantity", "qty", "so_luong", "sl", "units", "san_luong"},
    "revenue": {"revenue", "doanh_thu", "amount", "total_amount", "thanh_tien", "sales"},
    "product": {"product", "product_name", "san_pham", "mat_hang", "item", "sku", "ten_hang"},
    "person": {"person", "customer", "khach_hang", "employee", "nhan_vien", "customer_name", "employee_name"},
    "order": {"order_id", "invoice_id", "ma_don", "so_don", "id_don_hang"},
    "status": {"status", "trang_thai", "state"},
}


def _column(table: DataTable, semantic: str) -> str | None:
    choices = _ALIASES.get(semantic, {semantic})
    for name in table.columns:
        normalized = name.casefold()
        if normalized in choices:
            return name
    for name in table.columns:
        normalized = name.casefold()
        if any(alias in normalized for alias in choices):
            return name
    return None


def _formula_sql(formula: str, table: DataTable) -> str | None:
    # Permit only normalized column identifiers, numeric literals, parentheses and basic arithmetic.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\s*[+*/-]\s*(?:[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?))*", formula.strip()):
        return None
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[+*/-]", formula)
    result = []
    for token in tokens:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            if token not in table.columns:
                return None
            result.append(quote_identifier(token))
        else:
            result.append(token)
    return " ".join(result)


def _filter_clause(table: DataTable, metric: str, rulebook: Rulebook) -> tuple[str, str | None]:
    rule, conflict = rulebook.executable(f"exclude.{metric}")
    if conflict:
        return "", conflict
    if not rule:
        return "", None
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.+)", rule.strip(), re.IGNORECASE)
    if not match:
        return "", f"Unsupported exclusion rule: {rule}"
    column, raw_values = match.groups()
    if column not in table.columns:
        return "", f"Rule references missing column {column}"
    values = [item.strip().strip("'\"") for item in raw_values.split(",") if item.strip()]
    if not values:
        return "", "Exclusion rule has no values"
    escaped = ", ".join("'" + value.replace("'", "''").casefold() + "'" for value in values)
    return f"lower(CAST({quote_identifier(column)} AS TEXT)) NOT IN ({escaped})", None


def _date_filter(table: DataTable, date_range: DateRange) -> tuple[str | None, str | None]:
    column = _column(table, "date")
    if not column:
        return None, "Question requires a date filter but no date column was found"
    return f"date({quote_identifier(column)}) >= '{date_range.start.isoformat()}' AND date({quote_identifier(column)}) < '{date_range.end_exclusive.isoformat()}'", None


class RuleBasedPlanner:
    def plan(self, intent: Intent, tables: list[DataTable], catalog: SchemaCatalog, rulebook: Rulebook) -> tuple[QueryPlan | None, str | None]:
        if intent.kind == "unknown" or not intent.measure:
            return None, "Intent is outside the deterministic baseline"
        if intent.kind == "top" and not intent.dimension:
            return None, "Top query has no explicit group/entity and is ambiguous"
        candidates = []
        for table in tables:
            if intent.measure == "count":
                measure_ok = True
            elif intent.measure in {"revenue", "average_revenue"}:
                formula, _ = rulebook.executable("metric.revenue")
                measure_ok = bool(formula and _formula_sql(formula, table)) or _column(table, "revenue") is not None
            else:
                measure_ok = _column(table, "quantity") is not None
            dimension_ok = intent.kind != "top" or (intent.dimension is not None and _column(table, intent.dimension) is not None)
            date_ok = not intent.date_range or _column(table, "date") is not None
            if measure_ok and dimension_ok and date_ok:
                candidates.append(table)
        if not candidates:
            return None, "Available columns do not support the requested measure, grouping, or time filter"
        if len(candidates) > 1:
            # Stable choice only when one table has strictly more relevant semantics.
            def score(table: DataTable) -> int:
                return sum(_column(table, key) is not None for key in ("date", "quantity", "revenue", "product", "order", "status"))
            ranked = sorted(candidates, key=lambda table: score(table), reverse=True)
            if len(ranked) > 1 and score(ranked[0]) == score(ranked[1]):
                return None, "Multiple tables fit the request equally; deterministic planner will not guess"
            table = ranked[0]
        else:
            table = candidates[0]

        clauses = []
        if intent.date_range:
            date_clause, error = _date_filter(table, intent.date_range)
            if error:
                return None, error
            clauses.append(date_clause)
        base_measure = intent.measure.removeprefix("average_")
        if base_measure in {"revenue", "quantity"}:
            exclude_clause, error = _filter_clause(table, base_measure, rulebook)
            if error:
                return None, error
            if exclude_clause:
                clauses.append(exclude_clause)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        table_sql = quote_identifier(table.name)

        if intent.measure == "count":
            order_column = _column(table, "order")
            expression = f"COUNT(DISTINCT {quote_identifier(order_column)})" if order_column else "COUNT(*)"
            return QueryPlan(f"SELECT {expression} AS value FROM {table_sql}{where}", "Count rows/orders in the selected table", 0.76), None

        if base_measure == "revenue":
            formula, conflict = rulebook.executable("metric.revenue")
            if conflict:
                return None, conflict
            if formula:
                measure_sql = _formula_sql(formula, table)
                if not measure_sql:
                    return None, f"Revenue formula cannot be mapped safely: {formula}"
            else:
                column = _column(table, "revenue")
                if not column:
                    return None, "No unambiguous revenue column or explicit metric.revenue rule was found"
                measure_sql = quote_identifier(column)
            aggregate = f"dm_avg({measure_sql})" if intent.measure.startswith("average_") else f"dm_sum({measure_sql})"
        else:
            measure_column = _column(table, "quantity")
            if not measure_column:
                return None, "No quantity column was found"
            aggregate = f"dm_avg({quote_identifier(measure_column)})" if intent.measure.startswith("average_") else f"dm_sum({quote_identifier(measure_column)})"

        if intent.kind == "top":
            dimension = _column(table, intent.dimension or "")
            if not dimension:
                return None, "No product/grouping column was found"
            if intent.entity_only:
                sql = (
                    f"SELECT {quote_identifier(dimension)} AS value FROM {table_sql}{where} "
                    f"GROUP BY {quote_identifier(dimension)} ORDER BY {aggregate} DESC LIMIT 1"
                )
                return QueryPlan(sql, f"Find the highest-ranked {dimension}", 0.72), None
            sql = (
                f"SELECT {quote_identifier(dimension)} AS label, {aggregate} AS value "
                f"FROM {table_sql}{where} GROUP BY {quote_identifier(dimension)} "
                f"ORDER BY value DESC LIMIT {max(1, min(intent.top_k, 50))}"
            )
            return QueryPlan(sql, f"Rank {dimension} by {intent.measure}", 0.70), None
        return QueryPlan(f"SELECT {aggregate} AS value FROM {table_sql}{where}", f"Aggregate {intent.measure}", 0.76), None


def llm_prompt(question: str, as_of_date: str, catalog: SchemaCatalog, rules: Rulebook) -> str:
    schema_lines = []
    for table in catalog.tables:
        columns = ", ".join(
            f"{column.name} [{column.inferred_type}; tags={','.join(column.semantic_tags) or '-'}]"
            for column in table.columns
        )
        schema_lines.append(f"TABLE {table.name} ({table.row_count} rows): {columns}")
    for relation in catalog.relations:
        schema_lines.append(
            f"RELATION CANDIDATE {relation.from_table}.{relation.from_column} -> "
            f"{relation.to_table}.{relation.to_column} ({relation.cardinality}, confidence={relation.confidence})"
        )
    return (
        "Return exactly one JSON object with a single string field `sql`. Write one read-only SQLite SELECT query only. "
        "Use only discovered tables/columns. Prefer dm_sum/dm_avg/dm_max/dm_min for exact decimal aggregation. "
        "Do not explain.\n\n"
        f"as_of_date: {as_of_date}\nquestion: {question}\n\nschema:\n{chr(10).join(schema_lines)}\n\n"
        f"business rules:\n{rules.context(question)}"
    )

