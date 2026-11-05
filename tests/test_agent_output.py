import json
from datetime import date

from datamate.agent import DataMateAgent
from datamate.models import AnswerType, QuestionInput
from datamate.output import format_submission_record, write_jsonl


def test_synthetic_end_to_end_answers_and_safe_abstention():
    from pathlib import Path
    root = Path(__file__).parents[1] / "examples" / "data" / "biz_demo"
    agent = DataMateAgent.from_directory(root)
    try:
        revenue = agent.answer(QuestionInput("r", "biz_demo", "Tổng doanh thu tháng này là bao nhiêu?", date(2026, 3, 4)))
        assert revenue.type == AnswerType.NUMBER
        assert revenue.answer == 469000
        average = agent.answer(QuestionInput("a", "biz_demo", "Số lượng trung bình là bao nhiêu?", date(2026, 3, 4)))
        assert average.type == AnswerType.NUMBER
        assert str(average.answer) == "3.2"
        top = agent.answer(QuestionInput("t", "biz_demo", "Sản phẩm bán nhiều nhất tuần rồi là gì?", date(2026, 3, 4)))
        assert top.type == AnswerType.STRING
        assert top.answer == "Trà sữa truyền thống"
        ambiguous = agent.answer(QuestionInput("u", "biz_demo", "Doanh thu cao nhất là bao nhiêu?", date(2026, 3, 4)))
        assert ambiguous.type == AnswerType.ABSTAIN
        lunar = agent.answer(QuestionInput("l", "biz_demo", "Doanh thu tháng âm lịch này là bao nhiêu?", date(2026, 3, 4)))
        assert lunar.type == AnswerType.ABSTAIN
    finally:
        agent.close()


def test_jsonl_output_and_control_type_contract(tmp_path):
    from datamate.models import Answer
    from decimal import Decimal
    destination = tmp_path / "out.jsonl"
    answers = [
        Answer("a", AnswerType.NUMBER, Decimal("123.40")),
        Answer("b", AnswerType.ABSTAIN),
    ]
    write_jsonl(destination, answers)
    records = [json.loads(line, parse_float=Decimal) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert records == [
        {"id": "a", "type": "number", "answer": Decimal("123.40")},
        {"id": "b", "type": "abstain", "answer": None},
    ]
    assert format_submission_record(answers[1], include_null_control_answer=False) == {"id": "b", "type": "abstain"}

