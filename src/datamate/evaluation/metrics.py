from __future__ import annotations

import math
from collections import Counter
from typing import Any


def evaluate_predictions(gold: list[dict[str, Any]], predictions: list[dict[str, Any]], latencies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    by_id = {str(row.get("id")): row for row in predictions}
    total = len(gold)
    correct = 0
    abstain = 0
    unanswerable_total = 0
    unanswerable_correct = 0
    by_type: Counter[str] = Counter()
    correct_by_type: Counter[str] = Counter()
    missing = 0
    for truth in gold:
        item_id = str(truth.get("id"))
        predicted = by_id.get(item_id)
        answer_type = str(truth.get("type", "unknown"))
        by_type[answer_type] += 1
        if predicted is None:
            missing += 1
        else:
            predicted_type = str(predicted.get("type", "unknown"))
            abstain += predicted_type == "abstain"
            is_correct = predicted_type == answer_type and predicted.get("answer") == truth.get("answer")
            correct += is_correct
            correct_by_type[answer_type] += is_correct
        if answer_type == "unanswerable":
            unanswerable_total += 1
            unanswerable_correct += bool(predicted and predicted.get("type") == "unanswerable")
    elapsed = sorted(float(row["latency_ms"]) for row in (latencies or []) if row.get("latency_ms") is not None)
    p95 = elapsed[max(0, math.ceil(0.95 * len(elapsed)) - 1)] if elapsed else None
    return {
        "official_score": None,
        "metric_note": "Non-official exact match. Replace with the competition evaluator and verified score formula.",
        "count": total,
        "correct": correct,
        "wrong_non_abstain": total - correct - abstain,
        "exact_match_rate": correct / total if total else None,
        "abstain_count": abstain,
        "abstain_rate": abstain / total if total else None,
        "answer_rate": (total - abstain) / total if total else None,
        "unanswerable_count": unanswerable_total,
        "unanswerable_correct": unanswerable_correct,
        "unanswerable_accuracy": unanswerable_correct / unanswerable_total if unanswerable_total else None,
        "missing_prediction_count": missing,
        "accuracy_by_gold_type": {
            key: correct_by_type[key] / count if count else None for key, count in sorted(by_type.items())
        },
        "latency_ms_mean": sum(elapsed) / len(elapsed) if elapsed else None,
        "latency_ms_p95": p95,
        "latency_count": len(elapsed),
    }
