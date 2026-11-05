from __future__ import annotations

from pathlib import Path

from ..ingestion import DataPackage, load_package
from ..models import Answer, AnswerType, QuestionInput
from ..rules import load_rulebook
from ..schema import profile_tables
from ..sql import SafeSQLiteEngine, SQLSafetyError
from ..temporal import lunar_expression_present
from ..validation import validate_result
from .analyzer import analyze_question
from .llm import OpenAICompatiblePlanner
from .planner import RuleBasedPlanner


class DataMateAgent:
    def __init__(self, package: DataPackage, max_sql_seconds: float = 2.0, max_sql_vm_steps: int = 1_000_000, max_result_rows: int = 500):
        self.package = package
        self.catalog = profile_tables(package.tables)
        self.rulebook = load_rulebook(package.root, package.shared_rulebook, package.business_readme)
        self.engine = SafeSQLiteEngine(package.tables, max_sql_seconds, max_sql_vm_steps, max_result_rows, self.catalog.relations)
        self.rule_planner = RuleBasedPlanner()
        self.llm_planner = OpenAICompatiblePlanner.from_environment()

    @classmethod
    def from_directory(cls, package_root: str | Path, **kwargs) -> "DataMateAgent":
        return cls(load_package(package_root), **kwargs)

    def answer(self, question: QuestionInput) -> Answer:
        if not self.package.tables:
            return Answer(question.id, AnswerType.UNANSWERABLE, None, "No supported data tables were discovered")
        intent = analyze_question(question.question, question.as_of_date)
        if intent.unsupported_temporal or lunar_expression_present(question.question):
            return Answer(question.id, AnswerType.ABSTAIN, None, "Lunar date resolution is not configured")
        sql = None
        confidence = 0.0
        reason = None
        if self.llm_planner:
            try:
                sql = self.llm_planner.propose_sql(question.question, question.as_of_date.isoformat(), self.catalog, self.rulebook)
                confidence = 0.52
            except Exception as exc:
                reason = f"Optional LLM planner unavailable; using deterministic fallback ({type(exc).__name__})"
        plan, plan_error = self.rule_planner.plan(intent, self.package.tables, self.catalog, self.rulebook)
        if sql is None and plan:
            sql = plan.sql
            confidence = plan.confidence
        if sql is None:
            kind = AnswerType.UNANSWERABLE if "do not support" in (plan_error or "") or "No " in (plan_error or "") else AnswerType.ABSTAIN
            return Answer(question.id, kind, None, reason or plan_error or "No safe plan was found")
        try:
            rows = self.engine.execute(sql)
        except (SQLSafetyError, Exception) as exc:
            return Answer(question.id, AnswerType.ABSTAIN, None, f"Query was rejected or failed: {type(exc).__name__}", confidence, sql)
        value, validation_error = validate_result(rows)
        if validation_error:
            return Answer(question.id, AnswerType.ABSTAIN, None, validation_error, confidence, sql)
        if value is None:
            return Answer(question.id, AnswerType.ABSTAIN, None, "Query result is null or unsupported", confidence, sql)
        answer_type = AnswerType.TABLE if isinstance(value, list) and value and isinstance(value[0], dict) else (
            AnswerType.LIST if isinstance(value, list) else AnswerType.NUMBER if isinstance(value, (int, float)) or value.__class__.__name__ == "Decimal" else AnswerType.STRING
        )
        return Answer(question.id, answer_type, value, reason, confidence, sql)

    def close(self) -> None:
        self.engine.close()

