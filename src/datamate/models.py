from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any


class AnswerType(str, Enum):
    NUMBER = "number"
    PERCENT = "percent"
    STRING = "string"
    DATE = "date"
    BOOLEAN = "boolean"
    LIST = "list"
    TABLE = "table"
    UNANSWERABLE = "unanswerable"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class QuestionInput:
    id: str
    business_id: str
    question: str
    as_of_date: date

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QuestionInput":
        required = ("id", "business_id", "question", "as_of_date")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"Missing question fields: {', '.join(missing)}")
        return cls(
            id=str(value["id"]),
            business_id=str(value["business_id"]),
            question=str(value["question"]),
            as_of_date=date.fromisoformat(str(value["as_of_date"])),
        )


@dataclass
class Answer:
    id: str
    type: AnswerType
    answer: Any = None
    reason: str | None = None
    confidence: float = 0.0
    sql: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataTable:
    name: str
    source: str
    original_name: str
    original_columns: tuple[str, ...]
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DateRange:
    start: date
    end_exclusive: date
    label: str


@dataclass(frozen=True)
class Rule:
    key: str
    value: str
    source: str
    priority: int | None = None


@dataclass(frozen=True)
class Relation:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    confidence: float
    cardinality: str


@dataclass
class ColumnProfile:
    name: str
    original_name: str
    inferred_type: str
    nullable_count: int
    distinct_count: int
    samples: list[Any]
    semantic_tags: list[str] = field(default_factory=list)
    primary_key_candidate: bool = False


@dataclass
class TableProfile:
    name: str
    source: str
    row_count: int
    columns: list[ColumnProfile]


@dataclass
class SchemaCatalog:
    tables: list[TableProfile]
    relations: list[Relation]

