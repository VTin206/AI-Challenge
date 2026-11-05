from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..models import Answer, AnswerType
from ..util import json_dumps


def infer_answer_type(value) -> AnswerType:
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return AnswerType.TABLE
        return AnswerType.LIST
    if isinstance(value, bool):
        return AnswerType.BOOLEAN
    if isinstance(value, (int, float)) or value.__class__.__name__ == "Decimal":
        return AnswerType.NUMBER
    return AnswerType.STRING


def format_submission_record(answer: Answer, include_null_control_answer: bool = True) -> dict:
    record = {"id": answer.id, "type": answer.type.value}
    if answer.type not in {AnswerType.UNANSWERABLE, AnswerType.ABSTAIN} or include_null_control_answer:
        record["answer"] = answer.answer
    return record


def write_jsonl(path: str | Path, answers: Iterable[Answer], include_null_control_answer: bool = True) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as stream:
        for answer in answers:
            stream.write(json_dumps(format_submission_record(answer, include_null_control_answer)))
            stream.write("\n")

