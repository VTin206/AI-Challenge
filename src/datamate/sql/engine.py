from __future__ import annotations

import re
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from ..models import DataTable, Relation
from ..util import quote_identifier


class SQLSafetyError(ValueError):
    pass


class _DecimalAggregate:
    def __init__(self, operation: str = "sum"):
        self.values: list[Decimal] = []
        self.operation = operation

    def step(self, value: Any) -> None:
        if value is None:
            return
        try:
            text = str(value).strip()
            if not text:
                return
            self.values.append(Decimal(text))
        except (InvalidOperation, ValueError):
            raise ValueError(f"Cannot aggregate non-numeric value {value!r}")

    def finalize(self) -> str | None:
        if not self.values:
            return None
        if self.operation == "avg":
            result = sum(self.values, Decimal(0)) / len(self.values)
        elif self.operation == "max":
            result = max(self.values)
        elif self.operation == "min":
            result = min(self.values)
        else:
            result = sum(self.values, Decimal(0))
        return format(result, "f")


class SafeSQLiteEngine:
    def __init__(self, tables: list[DataTable], max_seconds: float = 2.0, max_vm_steps: int = 1_000_000, max_rows: int = 500, relations: list[Relation] | None = None):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.max_seconds = max_seconds
        self.max_vm_steps = max_vm_steps
        self.max_rows = max_rows
        self.tables = {table.name: table for table in tables}
        self.relations = relations or []
        self.query_log: list[dict[str, Any]] = []
        sqlite3.register_adapter(Decimal, lambda value: format(value, "f"))
        for table in tables:
            columns = ", ".join(quote_identifier(name) for name in table.columns)
            self.connection.execute(f"CREATE TABLE {quote_identifier(table.name)} ({columns})")
            if table.rows:
                placeholders = ",".join("?" for _ in table.columns)
                self.connection.executemany(
                    f"INSERT INTO {quote_identifier(table.name)} VALUES ({placeholders})",
                    table.rows,
                )
        self.connection.create_aggregate("dm_sum", 1, lambda: _DecimalAggregate("sum"))
        self.connection.create_aggregate("dm_avg", 1, lambda: _DecimalAggregate("avg"))
        self.connection.create_aggregate("dm_max", 1, lambda: _DecimalAggregate("max"))
        self.connection.create_aggregate("dm_min", 1, lambda: _DecimalAggregate("min"))
        self.connection.enable_load_extension(False)
        self.connection.execute("PRAGMA query_only = ON")
        self.connection.execute("PRAGMA trusted_schema = OFF")
        self.connection.set_authorizer(self._authorize)

    def _authorize(self, action: int, arg1: str | None, arg2: str | None, database: str | None, trigger: str | None) -> int:
        allowed_select = {getattr(sqlite3, name) for name in ("SQLITE_SELECT", "SQLITE_READ", "SQLITE_FUNCTION") if hasattr(sqlite3, name)}
        if action not in allowed_select:
            return sqlite3.SQLITE_DENY
        if action == getattr(sqlite3, "SQLITE_READ", -999):
            if database not in (None, "main") or arg1 not in self.tables:
                return sqlite3.SQLITE_DENY
        if action == getattr(sqlite3, "SQLITE_FUNCTION", -998):
            function_name = (arg2 or arg1 or "").casefold()
            if function_name in {"load_extension", "readfile", "writefile", "edit", "eval"}:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    @staticmethod
    def _strip_leading_comments(sql: str) -> str:
        value = sql.strip()
        while value:
            if value.startswith("--"):
                _, separator, rest = value.partition("\n")
                if not separator:
                    return ""
                value = rest.lstrip()
            elif value.startswith("/*"):
                end = value.find("*/", 2)
                if end < 0:
                    return ""
                value = value[end + 2 :].lstrip()
            else:
                break
        return value

    @staticmethod
    def _unquote_identifier(value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', '`', '[', "'"}:
            return value[1:-1].replace('""', '"')
        return value

    def _validate_join(self, statement: str) -> None:
        join_count = len(re.findall(r"\bJOIN\b", statement, re.IGNORECASE))
        if join_count == 0:
            return
        if join_count != 1:
            raise SQLSafetyError("Only a single verified join is supported by this baseline")
        if re.search(r"\b(?:RIGHT|FULL|CROSS)\s+(?:OUTER\s+)?JOIN\b", statement, re.IGNORECASE):
            raise SQLSafetyError("Only LEFT or INNER joins with a verified many-to-one direction are supported")
        ident = r'(?:"([^"\n]+)"|`([^`\n]+)`|\[([^\]\n]+)\]|([A-Za-z_][A-Za-z0-9_]*))'
        reserved = r"(?!LEFT\b|INNER\b|JOIN\b|ON\b|WHERE\b|GROUP\b|ORDER\b|HAVING\b|LIMIT\b|UNION\b)"
        from_match = re.search(rf"\bFROM\s+(?P<table>{ident})(?:\s+(?:AS\s+)?{reserved}(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?", statement, re.IGNORECASE)
        join_match = re.search(
            rf"\b(?P<kind>LEFT(?:\s+OUTER)?|INNER)?\s*JOIN\s+(?P<table>{ident})(?:\s+(?:AS\s+)?{reserved}(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?\s+ON\s+(?P<condition>.*?)(?=\b(?:WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|UNION|JOIN)\b|$)",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        if not from_match or not join_match:
            raise SQLSafetyError("Could not verify join structure; use one explicit table join")

        def ident_value(match, key: str) -> str:
            value = match.group(key)
            parts = re.fullmatch(ident, value, re.IGNORECASE)
            return next((item for item in parts.groups() if item is not None), "")

        base_table = ident_value(from_match, "table")
        joined_table = ident_value(join_match, "table")
        base_alias = from_match.group("alias") or base_table
        joined_alias = join_match.group("alias") or joined_table
        condition = join_match.group("condition")
        # Extract operands with a clearer pass; the equality must connect the declared FK to PK.
        operand = re.fullmatch(
            rf"\s*(?:(?P<a1>{ident})\.)?(?P<c1>{ident})\s*=\s*(?:(?P<a2>{ident})\.)?(?P<c2>{ident})\s*",
            condition,
            re.IGNORECASE,
        )
        if not operand:
            raise SQLSafetyError("Join condition must be one equality between discovered key columns")
        def group_ident(match, name: str) -> str | None:
            raw = match.group(name)
            if raw is None:
                return None
            parsed = re.fullmatch(ident, raw, re.IGNORECASE)
            return next((item for item in parsed.groups() if item is not None), "")
        alias1, col1 = group_ident(operand, "a1"), group_ident(operand, "c1")
        alias2, col2 = group_ident(operand, "a2"), group_ident(operand, "c2")
        if alias1 is None or alias2 is None:
            raise SQLSafetyError("Join condition must qualify both columns with table aliases")
        if not ((alias1.casefold() == base_alias.casefold() and alias2.casefold() == joined_alias.casefold()) or (alias2.casefold() == base_alias.casefold() and alias1.casefold() == joined_alias.casefold())):
            raise SQLSafetyError("Join condition aliases do not match the FROM/JOIN tables")
        if alias1.casefold() == base_alias.casefold():
            base_col, joined_col = col1, col2
        else:
            base_col, joined_col = col2, col1
        verified = any(
            rel.from_table == base_table
            and rel.to_table == joined_table
            and rel.from_column.casefold() == base_col.casefold()
            and rel.to_column.casefold() == joined_col.casefold()
            and rel.cardinality == "many-to-one candidate"
            and rel.confidence >= 0.8
            for rel in self.relations
        )
        if not verified:
            raise SQLSafetyError("Join does not match a high-confidence many-to-one schema relationship")

    def execute(self, sql: str) -> list[dict[str, Any]]:
        statement = self._strip_leading_comments(sql)
        first = re.match(r"([A-Za-z]+)", statement)
        if not first or first.group(1).casefold() not in {"select", "with"}:
            raise SQLSafetyError("Only SELECT or WITH ... SELECT statements are allowed")
        if re.search(r"\b(load_extension|readfile|writefile|edit|eval)\s*\(", statement, re.IGNORECASE):
            raise SQLSafetyError("External file and dynamic-code functions are prohibited")
        self._validate_join(statement)
        started = time.monotonic()
        steps = 0

        def progress() -> int:
            nonlocal steps
            steps += 1000
            return int(steps > self.max_vm_steps or time.monotonic() - started > self.max_seconds)

        self.connection.set_progress_handler(progress, 1000)
        try:
            cursor = self.connection.execute(sql)
            rows = cursor.fetchmany(self.max_rows + 1)
            if len(rows) > self.max_rows:
                raise SQLSafetyError(f"Query exceeded result row cap ({self.max_rows})")
            result = [dict(row) for row in rows]
            self.query_log.append({"sql": sql, "elapsed_seconds": round(time.monotonic() - started, 6), "rows": len(result), "ok": True})
            return result
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            self.query_log.append({"sql": sql, "elapsed_seconds": round(time.monotonic() - started, 6), "rows": 0, "ok": False, "error": message})
            if any(token in message.casefold() for token in ("not authorized", "readonly", "prohibited", "not authorized")):
                raise SQLSafetyError(message) from exc
            if "interrupted" in message.casefold():
                raise SQLSafetyError("Query exceeded its execution time or VM-step limit") from exc
            raise
        finally:
            self.connection.set_progress_handler(None, 0)

    def close(self) -> None:
        self.connection.close()

