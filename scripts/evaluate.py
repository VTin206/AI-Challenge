from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamate.evaluation import evaluate_predictions


def load_jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    parser = argparse.ArgumentParser(description="Penalized Accuracy (official DataMate matching rules) on a labelled split")
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path, help="answers.jsonl of the split")
    parser.add_argument("--questions", type=Path, help="questions.jsonl, enables per-business breakdown")
    parser.add_argument("--only-predicted", action="store_true", help="score only ids present in predictions (subset runs)")
    args = parser.parse_args()
    gold = load_jsonl(args.gold)
    preds = load_jsonl(args.predictions)
    if args.only_predicted:
        ids = {str(p["id"]) for p in preds}
        gold = [g for g in gold if str(g["id"]) in ids]
    questions = load_jsonl(args.questions) if args.questions else None
    print(json.dumps(evaluate_predictions(gold, preds, questions), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
