from datamate.evaluation import evaluate_predictions


def test_evaluation_metrics_report_abstain_unanswerable_and_latency():
    gold = [
        {"id": "a", "type": "number", "answer": 3},
        {"id": "b", "type": "string", "answer": "x"},
        {"id": "c", "type": "unanswerable", "answer": None},
    ]
    predictions = [
        {"id": "a", "type": "number", "answer": 3},
        {"id": "b", "type": "abstain", "answer": None},
        {"id": "c", "type": "unanswerable", "answer": None},
    ]
    report = evaluate_predictions(gold, predictions, [{"latency_ms": 10}, {"latency_ms": 20}, {"latency_ms": 30}])
    assert report["official_score"] is None
    assert report["correct"] == 2
    assert report["wrong_non_abstain"] == 0
    assert report["abstain_count"] == 1
    assert report["unanswerable_correct"] == 1
    assert report["latency_ms_mean"] == 20
    assert report["latency_ms_p95"] == 30

