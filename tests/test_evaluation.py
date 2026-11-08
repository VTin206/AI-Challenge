from datamate.evaluation import evaluate_predictions
from datamate.evaluation.metrics import score_one


def test_penalized_accuracy_counts_wrong_as_minus_one():
    gold = [
        {"id": "a", "type": "number", "answer": 3},
        {"id": "b", "type": "string", "answer": "x"},
        {"id": "c", "type": "unanswerable", "answer": None},
        {"id": "d", "type": "percent", "answer": -12.45},
    ]
    predictions = [
        {"id": "a", "type": "number", "answer": 3.0},
        {"id": "b", "type": "abstain"},
        {"id": "c", "type": "unanswerable", "reason": "no cost data"},
        {"id": "d", "type": "percent", "answer": 12.45},
    ]
    report = evaluate_predictions(gold, predictions)
    assert (report["correct"], report["wrong"], report["abstain"]) == (2, 1, 1)
    assert report["pa"] == 0.25


def test_oracle_and_all_abstain():
    gold = [{"id": str(i), "type": "number", "answer": i} for i in range(5)]
    assert evaluate_predictions(gold, gold)["pa"] == 1.0
    assert evaluate_predictions(gold, [{"id": g["id"], "type": "abstain"} for g in gold])["pa"] == 0.0
    assert evaluate_predictions(gold, [])["pa"] == 0.0


def test_string_normalization_and_alias():
    gold = {"type": "string", "answer": "Sting dâu 330ml", "alias": ["SP0042"]}
    assert score_one({"type": "string", "answer": "STING  dâu, 330ml"}, gold) == 1
    assert score_one({"type": "string", "answer": "sp0042"}, gold) == 1
    assert score_one({"type": "string", "answer": "Sting dầu 330ml"}, gold) == -1
    assert score_one({"type": "string", "answer": ["Sting dâu 330ml"]}, gold) == -1


def test_list_is_ordered_with_per_element_alias():
    gold = {"type": "list", "answer": ["Cà phê sữa", "Bạc xỉu"], "alias": [["SP0003"], ["SP0017"]]}
    assert score_one({"type": "list", "answer": ["SP0003", "bạc xỉu"]}, gold) == 1
    assert score_one({"type": "list", "answer": ["Bạc xỉu", "Cà phê sữa"]}, gold) == -1
    assert score_one({"type": "list", "answer": [3, 10]}, {"type": "list", "answer": [3, 10]}) == 1


def test_table_rows_are_a_set_and_columns_match_by_name():
    gold = {"type": "table", "answer": {"columns": ["khach_hang", "so_tien_no"], "rows": [["Chị Lan", 3200000], ["Anh Tú", 1500000]]},
            "alias": [["KH01"], ["KH02"]]}
    swapped_rows = {"type": "table", "answer": {"columns": ["khach_hang", "so_tien_no"], "rows": [["KH02", 1500000], ["Chị Lan", 3200000]]}}
    swapped_cols = {"type": "table", "answer": {"columns": ["so_tien_no", "khach_hang"], "rows": [[3200000, "Chị Lan"], [1500000, "Anh Tú"]]}}
    wrong = {"type": "table", "answer": {"columns": ["khach_hang", "so_tien_no"], "rows": [["Chị Lan", 3200001], ["Anh Tú", 1500000]]}}
    assert score_one(swapped_rows, gold) == 1
    assert score_one(swapped_cols, gold) == 1
    assert score_one(wrong, gold) == -1


def test_type_mismatch_and_answer_to_unanswerable_is_wrong():
    assert score_one({"type": "number", "answer": 0}, {"type": "unanswerable", "answer": None}) == -1
    assert score_one({"type": "string", "answer": "2026-08-15"}, {"type": "date", "answer": "2026-08-15"}) == -1
    assert score_one({"type": "date", "answer": "2026-08-15"}, {"type": "date", "answer": "2026-08-15"}) == 1
    assert score_one({"type": "boolean", "answer": 1}, {"type": "boolean", "answer": True}) == -1
